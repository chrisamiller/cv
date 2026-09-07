#!/usr/bin/env python3
"""Fetch per-publication citation counts from OpenAlex and write
src/data/citations.json (committed, consumed by build.py).

Usage:
    python3 fetch_citations.py            # fetch + write citations.json
    python3 fetch_citations.py --dry-run  # print the old -> new diff, write nothing

Decoupled from regenerate_html_pubs.py: this reads the publication id list out
of publications.json but writes a separate file, so the two can be run in any
order and regenerating the publication list never clobbers the counts.

OpenAlex: free, no API key. We use the "polite pool" (mailto= param). Counts run
a few percent under Google Scholar and converge for recent papers. Run this
occasionally (~quarterly); review the --dry-run diff before committing.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

PUBS_IN = Path("src/data/publications.json")
JSON_OUT = Path("src/data/citations.json")
MAILTO = "c.a.miller@wustl.edu"
API = "https://api.openalex.org/works"
CHUNK = 50  # OpenAlex OR-filter cap

# OpenAlex sometimes has duplicate work records for one DOI, and the DOI lookup
# can return the near-empty stub. Pin the right OpenAlex ID for those.
# key = cite key (lowercased DOI, or "pmid:<n>")  ->  OpenAlex work id
MANUAL = {
    "10.1038/ng.2764": "W2158485828",  # TCGA Pan-Cancer project (stub W1584451224 has 2 cites)
}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": f"chrismiller.science (mailto:{MAILTO})"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _bare_doi(doi_url):
    if not doi_url:
        return None
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", doi_url.strip(), flags=re.I).lower()


def _wid(openalex_id):
    return openalex_id.rstrip("/").rsplit("/", 1)[-1] if openalex_id else None


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def fetch_by_doi(dois):
    """{bare_lower_doi: {cited_by_count, openalex_id}}"""
    out = {}
    for group in _chunks(dois, CHUNK):
        values = "|".join(urllib.parse.quote(d, safe="") for d in group)
        url = f"{API}?filter=doi:{values}&select=id,doi,cited_by_count&per-page=200&mailto={MAILTO}"
        for w in _get(url).get("results", []):
            bd = _bare_doi(w.get("doi"))
            if bd:
                out[bd] = {"cited_by_count": w.get("cited_by_count", 0), "openalex_id": _wid(w["id"])}
        time.sleep(1)
    return out


def fetch_by_pmid(pmids):
    """{pmid_str: {cited_by_count, openalex_id}}"""
    out = {}
    for group in _chunks(pmids, CHUNK):
        values = "|".join(group)
        url = f"{API}?filter=pmid:{values}&select=id,ids,cited_by_count&per-page=200&mailto={MAILTO}"
        for w in _get(url).get("results", []):
            pm = (w.get("ids") or {}).get("pmid", "")
            m = re.search(r"(\d+)$", pm)
            if m:
                out[m.group(1)] = {"cited_by_count": w.get("cited_by_count", 0),
                                   "openalex_id": _wid(w["id"])}
        time.sleep(1)
    return out


def h_index(counts):
    h = 0
    for i, c in enumerate(sorted(counts, reverse=True), start=1):
        if c >= i:
            h = i
        else:
            break
    return h


def build_citations(entries):
    dois = sorted({e["doi"].lower() for e in entries if e.get("doi")})
    pmids = sorted({e["pmid"] for e in entries if e.get("pmid") and not e.get("doi")})

    by_doi = fetch_by_doi(dois)
    by_pmid = fetch_by_pmid(pmids)
    # second pass: entries with a DOI that OpenAlex didn't return, retried by PMID
    retry_pmids = sorted({e["pmid"] for e in entries
                          if e.get("pmid") and e.get("doi") and e["doi"].lower() not in by_doi})
    if retry_pmids:
        by_pmid.update(fetch_by_pmid(retry_pmids))

    by_id, unmatched = {}, []
    for e in entries:
        if e.get("doi"):
            key, hit = e["doi"].lower(), by_doi.get(e["doi"].lower())
        else:
            key, hit = f"pmid:{e['pmid']}", None
        if hit is None and e.get("pmid"):
            hit = by_pmid.get(e["pmid"])
            if e.get("doi"):
                key = e["doi"].lower()
        if hit is None:
            unmatched.append(e)
            continue
        if not e.get("doi"):
            key = f"pmid:{e['pmid']}"
        by_id[key] = {"cited_by_count": hit["cited_by_count"], "openalex_id": hit["openalex_id"]}

    # apply MANUAL overrides (fetch the pinned work so the count stays fresh)
    entry_keys = {key_for(e) for e in entries}
    unmatched = [e for e in unmatched if key_for(e) not in MANUAL]
    for key, wid in MANUAL.items():
        if key not in entry_keys:
            continue
        w = _get(f"{API}/{wid}?select=id,cited_by_count&mailto={MAILTO}")
        by_id[key] = {"cited_by_count": w.get("cited_by_count", 0), "openalex_id": _wid(w["id"])}
        time.sleep(1)

    counts = [v["cited_by_count"] for v in by_id.values()]
    totals = {
        "citations": sum(counts),
        "h_index": h_index(counts),
        "i10_index": sum(1 for c in counts if c >= 10),
        "counted": len(by_id),
    }
    return {
        "source": "OpenAlex",
        "generated": date.today().isoformat(),
        "as_of": date.today().strftime("%B %Y"),
        "totals": totals,
        "by_id": dict(sorted(by_id.items())),
    }, unmatched


def key_for(e):
    return e["doi"].lower() if e.get("doi") else f"pmid:{e['pmid']}"


def print_diff(entries, old, new):
    old_by = (old or {}).get("by_id", {})
    new_by = new["by_id"]
    title = {key_for(e): e["title"] for e in entries}
    rows = []
    for k in sorted(set(old_by) | set(new_by)):
        o = old_by.get(k, {}).get("cited_by_count")
        n = new_by.get(k, {}).get("cited_by_count")
        if o != n:
            rows.append((title.get(k, k), o, n))
    if rows:
        print(f"\n{'change':>14}  publication")
        for t, o, n in sorted(rows, key=lambda r: -((r[2] or 0) - (r[1] or 0))):
            print(f"{str(o):>6} -> {str(n):<4}  {t[:70]}")
    else:
        print("\nno per-publication changes")
    ot = (old or {}).get("totals", {})
    nt = new["totals"]
    print(f"\ntotals: {nt['citations']:,} citations (was {ot.get('citations', 0):,}) "
          f"| h-index {nt['h_index']} (was {ot.get('h_index', 0)}) "
          f"| i10 {nt['i10_index']} | counted {nt['counted']}/{len(entries)}")


def main():
    dry = "--dry-run" in sys.argv[1:]
    entries = json.loads(PUBS_IN.read_text())["entries"]
    old = json.loads(JSON_OUT.read_text()) if JSON_OUT.exists() else None

    payload, unmatched = build_citations(entries)
    print(f"matched {payload['totals']['counted']}/{len(entries)} publications")
    if unmatched:
        print("unmatched (no OpenAlex record yet — usually brand-new preprints):")
        for e in unmatched:
            print(f"  #{e['n']}  {e['title'][:72]}")

    print_diff(entries, old, payload)

    if dry:
        print("\n--dry-run: citations.json not written")
        return
    JSON_OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    print(f"\nwrote {JSON_OUT}")


if __name__ == "__main__":
    main()
