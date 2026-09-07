#!/usr/bin/env python3
"""Regenerate Chris Miller's publication list from the numbered Publications
section of MillerCurriculumVitae.docx (the master), via one PubMed efetch call.

Usage:
    python3 regenerate_html_pubs.py               # write src/data/publications.json (default)
    python3 regenerate_html_pubs.py --json        # same, explicit
    python3 regenerate_html_pubs.py --legacy-html # also splice <li class="pub"> into oldsite/index.html

Pipeline: docx -> per-publication citation text -> PMID/DOI -> PubMed efetch XML ->
structured entries (authors/title/journal/year/doi), newest first.
See update.md for the style rules.
"""
import json, re, sys, urllib.request, zipfile
from datetime import date
from pathlib import Path
import xml.etree.ElementTree as ET

DOCX = "MillerCurriculumVitae.docx"
HTML = "oldsite/index.html"
JSON_OUT = Path("src/data/publications.json")

# Publications whose docx PMID is wrong/missing or that have no usable PubMed record.
MANUAL = {
    18: dict(title="The cancer genome atlas pan-cancer analysis project",
             journal="Nature Genetics", year="2013", doi="10.1038/ng.2764",
             authors="The Cancer Genome Atlas Research Network"),
    107: dict(title="Bam-readcount: rapid generation of basepair-resolution sequence metrics",
              journal="Journal Of Open Source Software", year="2022", doi="10.21105/joss.03722",
              authors="Khanna A, Larson DE, Srivatsan SN, Mosior M, Abbott TE, Kiwala S, Ley TJ, "
                      "Duncavage EJ, Walter MJ, Walker JR, Griffith OL, Griffith M, Miller CA"),
    137: dict(title="Automating neoantigen selection for personalized cancer vaccine design",
              journal="medRxiv", year="2026", doi="10.64898/2026.06.24.26356293",
              authors="Yao JX, Singhal K, Kiwala S, Schmidt E, Goedegebuure S, Miller CA, Xia H, "
                      "Cotto K, Coffman A, Hoang MH, Khanfar M, Li J, Hendrickson L, Risch I, "
                      "Davies SR, Du F, Chang G, Hundal J, Ward JP, Inabinett WB, Hoos WA, "
                      "Johanns TM, Dunn GP, Pachynski RK, Fehniger TA, Foltz JA, Gillanders WE, "
                      "Griffith M, Griffith OL"),
}


def extract_docx_pubs():
    with zipfile.ZipFile(DOCX) as z:
        doc = z.read("word/document.xml").decode("utf-8")
    paras = re.findall(r"<w:p[ >].*?</w:p>", doc, re.S)
    rows = []
    for i, p in enumerate(paras):
        t = re.sub(r"<w:tab/>", " ", p)
        t = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", t, re.S))
        t = (t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
             .replace("&#8217;", "'").replace("’", "'")).strip()
        m = re.match(r"^(\d+)[.\s]", t)
        if m and 118 < i < len(paras) - 1:
            n = int(m.group(1))
            body = re.sub(r"^\d+\.?\s*", "", t).strip()
            pmid = re.search(r"PMID:\s*(\d+)", body)
            doi = re.search(r"10\.\d{4,9}/[^\s,;]+", body)
            rows.append([n, body, pmid.group(1) if pmid else None,
                         doi.group(0).rstrip(".") if doi else None])
    assert [r[0] for r in rows] == list(range(1, len(rows) + 1)), "docx numbering not 1..N"
    return rows


def fetch_pubmed(pmids):
    url = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&retmode=xml&id="
           + ",".join(pmids))
    with urllib.request.urlopen(url) as r:
        xml = r.read()
    root = ET.fromstring(xml)
    return {a.findtext(".//MedlineCitation/PMID"): a for a in root.findall("PubmedArticle")}


def cap_each(s):
    return " ".join(w.capitalize() for w in s.split()).replace("Plos", "PLoS").replace("Bmc", "BMC")


def clean_journal(title):
    t = title.split(" : ")[0]
    t = re.sub(r"\s*\([^)]*\)\s*$", "", t)
    t = cap_each(t)
    t = re.sub(r"^The ", "", t)
    t = re.sub(r" Of The United States Of America$", "", t)
    t = t.replace("Iscience", "iScience")
    low = t.lower()
    for pre, fixed in (("biorxiv", "bioRxiv"), ("medrxiv", "medRxiv"), ("arxiv", "arXiv"),
                       ("research square", "Research Square")):
        if low.startswith(pre):
            return fixed
    if low == "nejm evidence":
        return "NEJM Evidence"
    return t


def is_miller(last, init):
    return last == "Miller" and init.startswith("C")


def cofirst_set(body):
    return {(m.group(1), m.group(2))
            for m in re.finditer(r"([A-Z][A-Za-z'À-ž-]+) ([A-Z]{1,3})\*", body[:320])}


def authors_from_pubmed(art):
    al = art.find(".//Article/AuthorList")
    if al is None:
        return []
    people, collectives = [], []
    for a in al.findall("Author"):
        coll = a.findtext("CollectiveName")
        if coll:
            c = coll.strip().rstrip(".").strip()
            if "@" in c or c.lower().startswith("electronic address"):
                continue
            if c not in collectives:
                collectives.append(c)
            continue
        last = a.findtext("LastName")
        if not last:
            continue
        people.append({"last": last, "init": a.findtext("Initials") or "",
                       "name": f"{last} {a.findtext('Initials') or ''}".strip(),
                       "eq": a.get("EqualContrib") == "Y"})
    if people:
        return people
    out = []
    for c in collectives:
        if c.lower().startswith("cancer genome atlas"):
            c = "The " + c
        out.append({"last": None, "init": None, "name": c, "eq": False})
    return out


def authors_from_str(s):
    res = []
    for tok in s.split(", "):
        tok = tok.strip().rstrip(".")
        star = tok.endswith("*")
        tok = tok.rstrip("*")
        parts = tok.rsplit(" ", 1)
        if len(parts) == 2 and re.fullmatch(r"[A-Z]{1,4}", parts[1]):
            res.append({"last": parts[0], "init": parts[1], "name": tok, "eq": star})
        else:
            res.append({"last": None, "init": None, "name": tok, "eq": star})
    return res


def fmt_authors(authors, cofirst):
    def render(a):
        eq = a["eq"] or (a["last"], a["init"]) in cofirst
        if a["last"] and is_miller(a["last"], a["init"]):
            return f"<strong>Miller CA{'*' if eq else ''}</strong>"
        return a["name"] + ("*" if eq else "")
    shown = authors[:10]
    names = [render(a) for a in shown]
    if len(authors) > 10:
        if not any(a["last"] and is_miller(a["last"], a["init"]) for a in shown):
            m = next((a for a in authors if a["last"] and is_miller(a["last"], a["init"])), None)
            if m:
                names.append(render(m))
        names.append("<em>et al.</em>")
    return ", ".join(names)


def node_text(el):
    return "".join(el.itertext()) if el is not None else ""


def build_entries(rows, pm):
    entries = []
    for n, body, pmid, doi_scr in rows:
        cofirst = cofirst_set(body)
        alt_href = None
        if n in MANUAL:
            md = MANUAL[n]
            authors = authors_from_str(md["authors"])
            title, journal, year, doi = md["title"], md["journal"], md["year"], md["doi"]
        else:
            art = pm[pmid]
            title = node_text(art.find(".//Article/ArticleTitle")).strip().rstrip(".").strip()
            journal = clean_journal(art.findtext(".//Article/Journal/Title") or "")
            year = art.findtext(".//Article/Journal/JournalIssue/PubDate/Year")
            if not year:
                md_ = art.findtext(".//Article/Journal/JournalIssue/PubDate/MedlineDate") or ""
                mm = re.search(r"(19|20)\d\d", md_)
                year = mm.group(0) if mm else ""
            doi = None
            for aid in art.findall(".//PubmedData/ArticleIdList/ArticleId"):
                if aid.get("IdType") == "doi":
                    doi = aid.text
            if not doi:
                el = art.find('.//Article/ELocationID[@EIdType="doi"]')
                doi = el.text if el is not None else doi_scr
            authors = authors_from_pubmed(art)
            cga = re.match(r"^(The )?Cancer Genome Atlas[\w ]*?(Network|Group)", body)
            if cga:
                name = cga.group(0).strip().rstrip(".").replace("Atlast", "Atlas")
                authors = [{"last": None, "init": None, "name": name, "eq": False}]
            if not doi and journal == "arXiv":
                for aid in art.findall(".//PubmedData/ArticleIdList/ArticleId"):
                    if aid.get("IdType") == "pii":
                        alt_href = f"https://arxiv.org/abs/{aid.text}"
        doi = (doi or "").strip().rstrip(".")
        a_str = fmt_authors(authors, cofirst)
        title_esc = title.replace("&", "&amp;")
        if doi:
            href, kind = f"https://doi.org/{doi}", "doi"
            details = f"{a_str}. {journal}. {year}. doi:{doi}"
        elif alt_href:
            href, kind = alt_href, "arxiv"
            details = f"{a_str}. {journal}. {year}."
        elif pmid:
            href, kind = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "pubmed"
            details = f"{a_str}. {journal}. {year}."
        else:
            href, kind = "#", "doi"
            details = f"{a_str}. {journal}. {year}."
        li = (f'<li class="pub"><a href="{href}">{title_esc}</a><br />\n'
              f'<span class="pubdetails">{details}</span>\n</li>')
        entries.append({
            "n": n, "li": li,
            "year": year, "title": title_esc, "authors_html": a_str,
            "journal": journal, "doi": doi, "url": href,
            "link_kind": kind, "pmid": pmid or "",
        })
    entries.sort(key=lambda e: -e["n"])
    return entries


def write_json(entries):
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated": date.today().isoformat(),
        "count": len(entries),
        "entries": [{k: e[k] for k in
                     ("n", "year", "title", "authors_html", "journal", "doi", "url", "link_kind", "pmid")}
                    for e in entries],
    }
    JSON_OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    print(f"wrote {JSON_OUT} ({len(entries)} entries)")


def splice(entries):
    lis = [e["li"] for e in entries]
    lines = open(HTML).read().split("\n")
    start = next(i for i, l in enumerate(lines) if l.startswith('<li class="pub">'))
    end = next(i for i, l in enumerate(lines) if l.strip() == "</ul>" and i > start)
    assert lines[end - 1] == "</li>"
    out = lines[:start] + "\n".join(lis).split("\n") + lines[end:]
    open(HTML, "w").write("\n".join(out))


def main():
    rows = extract_docx_pubs()
    pmids = [r[2] for r in rows if r[2]]
    pm = fetch_pubmed(pmids)
    missing = [p for p in pmids if p not in pm]
    if missing:
        print("WARNING: PMIDs not returned by PubMed:", missing)
    entries = build_entries(rows, pm)
    print(f"{len(entries)} entries generated (docx has {len(rows)})")

    args = sys.argv[1:]
    did = False
    if "--legacy-html" in args:
        splice(entries)
        print(f"spliced <li class=\"pub\"> list into {HTML}")
        did = True
    if "--json" in args or not args:
        write_json(entries)
        did = True
    if not did:
        print("\n".join(e["li"] for e in entries[:2]))
        print("...\n(pass --json to write publications.json, --legacy-html to update index.html)")


if __name__ == "__main__":
    main()
