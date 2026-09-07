#!/usr/bin/env python3
"""Add publication(s) to the CV from PMIDs / DOIs, in one shot.

    python3 add_publication.py 42659646 10.1056/EVIDoa2500352 ...
    python3 add_publication.py --dry-run 42659646        # show citation(s), change nothing
    python3 add_publication.py --no-pdf 42659646         # skip the Word -> PDF step
    python3 add_publication.py --no-site 42659646        # skip regenerate + build

What it does, for each id (order preserved, appended after the current last entry):
  1. resolve DOI -> PMID (PubMed esearch) if needed, then one PubMed efetch
  2. format an NLM-style citation string (see update.md) with "Miller CA" bolded
  3. append numbered <w:p> paragraph(s) to word/document.xml in MillerCurriculumVitae.docx
  4. refresh the date: "Month D, YYYY" on the first page + "M/DD/YYYY" in the footer
  5. re-export the PDF via Microsoft Word (AppleScript) to ./MillerCurriculumVitae.pdf
  6. run regenerate_html_pubs.py --json and build.py so the Publications page updates

A timestamped backup of the docx (and pdf) is written to ./_cv_backups/ before any edit.
Stdlib only; steps 1/5/6 need network / Word.
"""
import argparse
import datetime
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCX = ROOT / "MillerCurriculumVitae.docx"
PDF = ROOT / "MillerCurriculumVitae.pdf"
BACKUPS = ROOT / "_cv_backups"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

PREPRINT_ABBREVS = {"arxiv", "biorxiv", "medrxiv", "res sq", "research square"}
MONTHS = {m: m for m in ("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
MONTHS.update({f"{i:02d}": n for i, n in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)})


# --------------------------------------------------------------- PubMed ------
def _get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def resolve_to_pmid(token):
    token = token.strip()
    if re.fullmatch(r"\d+", token):
        return token
    # treat as DOI (strip any URL prefix)
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", token, flags=re.I)
    q = urllib.parse.quote(f'"{doi}"[AID]')
    data = _get(f"{EUTILS}/esearch.fcgi?db=pubmed&retmode=json&term={q}")
    import json
    ids = json.loads(data).get("esearchresult", {}).get("idlist", [])
    if not ids:
        # fall back to a plain-term search
        data = _get(f"{EUTILS}/esearch.fcgi?db=pubmed&retmode=json&term={urllib.parse.quote(doi)}")
        ids = json.loads(data).get("esearchresult", {}).get("idlist", [])
    if not ids:
        sys.exit(f"add_publication: no PubMed record found for '{token}'")
    return ids[0]


def efetch(pmids):
    url = f"{EUTILS}/efetch.fcgi?db=pubmed&retmode=xml&id={','.join(pmids)}"
    root = ET.fromstring(_get(url))
    out = {}
    for art in root.findall("PubmedArticle"):
        out[art.findtext(".//MedlineCitation/PMID")] = art
    missing = [p for p in pmids if p not in out]
    if missing:
        sys.exit(f"add_publication: PubMed returned nothing for {missing}")
    return out


def node_text(el):
    return "".join(el.itertext()).strip() if el is not None else ""


def format_citation(art, pmid):
    a = art.find(".//Article")
    title = node_text(a.find("ArticleTitle")).rstrip(" .")
    jabbrev = (a.findtext(".//Journal/ISOAbbreviation")
               or a.findtext(".//MedlineJournalInfo/MedlineTA") or "").strip()

    # authors (all of them; collectives kept verbatim)
    names, eq_names = [], []
    for au in a.findall(".//AuthorList/Author"):
        coll = au.findtext("CollectiveName")
        if coll:
            names.append(coll.strip().rstrip("."))
            continue
        last, init = au.findtext("LastName"), au.findtext("Initials") or ""
        if not last:
            continue
        nm = f"{last} {init}".strip()
        names.append(nm)
        if au.get("EqualContrib") == "Y":
            eq_names.append(nm)
    # mark co-first authorship only when Miller is one of the equal contributors
    if any(n.startswith("Miller ") for n in eq_names):
        names = [n + "*" if n in eq_names else n for n in names]
    authors = ", ".join(names)

    # publication date
    pd = a.find(".//JournalIssue/PubDate")
    if pd is not None and pd.findtext("Year"):
        date = pd.findtext("Year")
        mon = MONTHS.get((pd.findtext("Month") or "").strip())
        if mon:
            date += f" {mon}"
            if pd.findtext("Day"):
                date += f" {int(pd.findtext('Day'))}"
    else:
        date = (pd.findtext("MedlineDate") if pd is not None else "") or ""

    vol = a.findtext(".//JournalIssue/Volume") or ""
    iss = a.findtext(".//JournalIssue/Issue") or ""
    pages = a.findtext(".//Pagination/MedlinePgn") or a.findtext(".//Pagination/StartPage") or ""
    loc = vol + (f"({iss})" if iss else "") + (f":{pages}" if pages else "")

    doi = pmcid = ""
    for aid in art.findall(".//ArticleIdList/ArticleId"):
        if aid.get("IdType") == "doi":
            doi = aid.text.strip()
        elif aid.get("IdType") == "pmc":
            pmcid = aid.text.strip()
            if not pmcid.upper().startswith("PMC"):
                pmcid = "PMC" + pmcid

    ptypes = {node_text(p).lower() for p in a.findall(".//PublicationTypeList/PublicationType")}
    is_preprint = jabbrev.lower() in PREPRINT_ABBREVS or "preprint" in ptypes

    tail = ""
    if doi:
        tail += f" doi: {doi}."
    tail += f" PMID: {pmid}"
    if pmcid:
        tail += f"; PMCID: {pmcid}"
    tail += "."

    if is_preprint:
        cite = f"{authors}. {title}. {jabbrev} [Preprint]. {date}.{tail}"
    elif loc:
        cite = f"{authors}. {title}. {jabbrev}. {date};{loc}.{tail}"
    else:
        cite = f"{authors}. {title}. {jabbrev}. {date}.{tail}"
    return cite


# ------------------------------------------------------------ docx surgery ---
def xml_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


RPR = '<w:rPr><w:rFonts w:ascii="Helvetica" w:hAnsi="Helvetica"/></w:rPr>'
RPR_B = '<w:rPr><w:rFonts w:ascii="Helvetica" w:hAnsi="Helvetica"/><w:b/></w:rPr>'
PPR = ('<w:pPr><w:spacing w:line="288" w:lineRule="auto"/>'
       '<w:ind w:left="720" w:hanging="720"/>'
       '<w:rPr><w:rFonts w:ascii="Helvetica" w:hAnsi="Helvetica"/></w:rPr></w:pPr>')


def pub_paragraph(num, citation, pid):
    """Build one numbered <w:p>. If 'Miller CA' appears in the author list it is
    split into its own bold run (matching every existing entry)."""
    head = f'<w:p w14:paraId="{pid}" w14:textId="77777777" w:rsidR="001E2D0D" w:rsidRDefault="001E2D0D" w:rsidP="00337CDF">{PPR}'
    num_run = f'<w:r>{RPR}<w:t>{num}.</w:t></w:r>'

    m = re.search(r"Miller C[A-Z]?\*?", citation)
    if m:
        before, mid, after = citation[:m.start()], m.group(0), citation[m.end():]
        runs = (
            f'<w:r>{RPR}<w:tab/><w:t xml:space="preserve">{xml_escape(before)}</w:t></w:r>'
            f'<w:r>{RPR_B}<w:t xml:space="preserve">{xml_escape(mid)}</w:t></w:r>'
            f'<w:r>{RPR}<w:t xml:space="preserve">{xml_escape(after)}</w:t></w:r>'
        )
    else:
        runs = f'<w:r>{RPR}<w:tab/><w:t xml:space="preserve">{xml_escape(citation)}</w:t></w:r>'
    return f"{head}{num_run}{runs}</w:p>"


def next_paraid(seed):
    return f"{(0x1C7D2001 + seed * 7) & 0xFFFFFFFF:08X}"


def edit_document_xml(xml, citations, today_long):
    # locate the numbered publication list: paragraphs whose first run text is "N."
    last_num, last_end = 0, None
    for m in re.finditer(
        r'<w:p\b[^>]*>(?:<w:pPr>.*?</w:pPr>)?<w:r>(?:(?!</w:r>).)*?<w:t>(\d{1,3})\.</w:t></w:r>',
        xml, re.S,
    ):
        n = int(m.group(1))
        end = xml.index("</w:p>", m.start()) + len("</w:p>")
        if n >= last_num:
            last_num, last_end = n, end
    if last_end is None:
        sys.exit("add_publication: could not find the numbered publication list in the docx")

    new_paras = "".join(
        pub_paragraph(last_num + i + 1, c, next_paraid(last_num + i + 1))
        for i, c in enumerate(citations)
    )
    xml = xml[:last_end] + new_paras + xml[last_end:]
    added = list(range(last_num + 1, last_num + 1 + len(citations)))

    # first-page date: keep the "DATE :   <spaces>" runs, replace the value with one run
    date_run = (f'<w:r><w:rPr><w:rFonts w:ascii="Helvetica" w:hAnsi="Helvetica"/>'
                f'<w:sz w:val="22"/></w:rPr><w:t>{today_long}</w:t></w:r>')
    xml, n = re.subn(
        r'(<w:p\b(?:(?!</w:p>).)*?<w:t>DATE</w:t>(?:(?!</w:p>).)*?'
        r'<w:t xml:space="preserve"> {5,}</w:t></w:r>)(?:(?!</w:p>).)*?(</w:p>)',
        r'\1' + date_run + r'\2', xml, count=1, flags=re.S,
    )
    if n != 1:
        sys.exit("add_publication: could not locate the first-page DATE field")
    return xml, added


def edit_footer_xml(xml, today_slash):
    # footer line 1: "Curriculum Vitae <tab><tab> <date runs>"
    xml, n = re.subn(
        r'(<w:p w14:paraId="7C99D362"(?:(?!</w:p>).)*?<w:r><w:tab/></w:r><w:r><w:tab/></w:r>)'
        r'(?:(?!</w:p>).)*?(</w:p>)',
        r'\1<w:r><w:t>' + today_slash + r'</w:t></w:r>\2', xml, count=1, flags=re.S,
    )
    if n != 1:
        sys.exit("add_publication: could not locate the footer date")
    return xml


def rewrite_docx(path, replacements):
    tmp = path.with_suffix(".docx.tmp")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = replacements.get(item.filename)
            zout.writestr(item, data.encode("utf-8") if data is not None else zin.read(item.filename))
    tmp.replace(path)


# ---------------------------------------------------------------- pdf --------
def make_pdf(docx_path, pdf_path):
    """Export via Microsoft Word to a temp file; only replace pdf_path on success
    (so a failed/blocked run never destroys the existing PDF)."""
    out = Path(pdf_path).with_suffix(".new.pdf")
    if out.exists():
        out.unlink()
    script = (
        'tell application "Microsoft Word"\n'
        '  activate\n'
        f'  open "{docx_path}"\n'
        '  set d to active document\n'
        f'  save as d file name "{out}" file format format PDF\n'
        '  close d saving no\n'
        'end tell\n'
    )
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        if out.exists():
            out.unlink()
        print("  ! PDF export via Word failed:", (r.stderr or r.stdout).strip() or "(no output)")
        print("    Grant Automation permission (System Settings > Privacy & Security >")
        print("    Automation > [your terminal] > Microsoft Word), then run:")
        print("      python3 add_publication.py --pdf-only")
        print("    or export the PDF from Word by hand to", pdf_path)
        return False
    out.replace(pdf_path)
    print("  PDF written:", pdf_path)
    return True


def run(cmd):
    print("  $", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


# --------------------------------------------------------------- main -------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*", help="PMIDs and/or DOIs")
    ap.add_argument("--dry-run", action="store_true", help="print citations, change nothing")
    ap.add_argument("--no-pdf", action="store_true", help="skip the Word -> PDF step")
    ap.add_argument("--no-site", action="store_true", help="skip regenerate + build")
    ap.add_argument("--pdf-only", action="store_true",
                    help="just (re-)export the PDF from the current docx and rebuild the site")
    args = ap.parse_args()

    if args.pdf_only:
        print("exporting PDF via Microsoft Word...")
        if make_pdf(DOCX, PDF) and not args.no_site:
            run([sys.executable, "build.py"])
        return
    if not args.ids:
        ap.error("give at least one PMID/DOI (or use --pdf-only)")

    pmids = [resolve_to_pmid(t) for t in args.ids]
    arts = efetch(pmids)
    citations = [format_citation(arts[p], p) for p in pmids]

    print(f"\n{len(citations)} citation(s):\n")
    for c in citations:
        print("  " + c + "\n")

    if args.dry_run:
        print("--dry-run: nothing written")
        return

    BACKUPS.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(DOCX, BACKUPS / f"MillerCurriculumVitae.{stamp}.docx")
    if PDF.exists():
        shutil.copy2(PDF, BACKUPS / f"MillerCurriculumVitae.{stamp}.pdf")
    print(f"backup: {BACKUPS}/MillerCurriculumVitae.{stamp}.docx")

    today = datetime.date.today()
    today_long = f"{today.strftime('%B')} {today.day}, {today.year}"
    today_slash = f"{today.month}/{today.day:02d}/{today.year}"

    with zipfile.ZipFile(DOCX) as z:
        doc_xml = z.read("word/document.xml").decode("utf-8")
        foot_xml = z.read("word/footer1.xml").decode("utf-8")

    doc_xml, added = edit_document_xml(doc_xml, citations, today_long)
    foot_xml = edit_footer_xml(foot_xml, today_slash)
    rewrite_docx(DOCX, {"word/document.xml": doc_xml, "word/footer1.xml": foot_xml})
    print(f"docx: added #{added[0]}"
          + (f"-#{added[-1]}" if len(added) > 1 else "")
          + f"; date set to {today_long} / {today_slash}")

    if not args.no_pdf:
        print("\nexporting PDF via Microsoft Word...")
        make_pdf(DOCX, PDF)

    if not args.no_site:
        print("\nupdating the website...")
        run([sys.executable, "regenerate_html_pubs.py", "--json"])
        run([sys.executable, "build.py"])

    print("\ndone.")


if __name__ == "__main__":
    main()
