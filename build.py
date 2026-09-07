#!/usr/bin/env python3
"""Static-site generator for chrismiller.science.

Assembles src/pages/*.html into build/*.html using src/partials/*.html and two
data files, then copies assets and writes a search index. Python 3 stdlib only.

    python3 build.py            # build into build/
    python3 build.py --serve    # build, then serve on :8000

Publications come from src/data/publications.json, produced by
    python3 regenerate_html_pubs.py --json
(run that first, and only when the publication list changes — it needs network).
"""
import json
import re
import shutil
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
OUT = ROOT / "build"
TOKEN = re.compile(r"\{\{\s*(include:)?([a-z_]+)\s*\}\}")
FRONT = re.compile(r"^\s*<!--\s*(.*?)\s*-->\s*\n?", re.S)


def die(msg):
    print(f"build.py: ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------- rendering ---
def render(text, ctx, depth=0):
    if depth > 12:
        die("include recursion too deep")

    def sub(m):
        is_include, name = m.group(1), m.group(2)
        if is_include:
            frag = ctx["_inc"].get(name)
            if frag is None:
                p = SRC / "partials" / f"{name}.html"
                if not p.exists():
                    die(f"missing include: {name}")
                frag = p.read_text()
            return render(frag, ctx, depth + 1)
        if name not in ctx:
            die(f"unknown variable {{{{ {name} }}}} (page {ctx.get('page_file', '?')})")
        return str(ctx[name])

    return TOKEN.sub(sub, text)


# ------------------------------------------------------------ computed bits ---
def nav_links(site, active):
    out = []
    for item in site["nav"]:
        cls = "nav-link active" if item["id"] == active else "nav-link"
        out.append(
            f'<li class="nav-item"><a class="{cls}" href="{item["file"]}">{item["label"]}</a></li>'
        )
    return "\n".join(out)


def profile_links(site):
    out = []
    for s in site["socials"]:
        if s.get("disabled") or not s.get("href"):
            out.append(
                f'<!-- {s["label"]}: add URL in site.json to show this icon -->'
            )
            continue
        href = s["href"].replace("&", "&amp;")
        if s.get("mask"):
            inner = f'<span class="icon-mask icon-mask-{s["mask"]}"></span>'
        else:
            inner = f'<i class="{s["icon"]}"></i>'
        ext = "" if href.startswith("mailto:") else ' target="_blank" rel="noopener"'
        out.append(
            f'<a href="{href}" class="icon-link" title="{s["label"]}"'
            f' aria-label="{s["label"]}"{ext}>{inner}</a>'
        )
    return "\n".join(out)


def news_items(news, limit=None, cls="news-item"):
    items = news[:limit] if limit else news
    return "\n".join(
        f'<div class="{cls}"><div class="news-date">{n["date"]}</div>'
        f'<div class="news-headline">{n["headline"]}</div></div>'
        for n in items
    )


def cite_key(e):
    return e["doi"].lower() if e.get("doi") else (f'pmid:{e["pmid"]}' if e.get("pmid") else "")


def _pill(cls, href, label):
    return f'<a class="btn-pill {cls}" href="{href}" target="_blank" rel="noopener">{label}</a>'


def render_pub(e, cites=None):
    meta = f'{e["authors_html"]}. <span class="pub-venue">{e["journal"]}</span>. {e["year"]}.'

    actions = []
    if e.get("doi"):
        actions.append(_pill("btn-doi", f'https://doi.org/{e["doi"]}', "DOI"))
    elif e.get("link_kind") == "arxiv":
        actions.append(_pill("btn-arxiv", e["url"], "arXiv"))
    if e.get("pmid"):
        actions.append(_pill("btn-pubmed", f'https://pubmed.ncbi.nlm.nih.gov/{e["pmid"]}/', "PubMed"))
    if not actions:
        actions.append(_pill("btn-doi", e["url"], "Link"))

    hit = (cites or {}).get(cite_key(e)) if cites else None
    n_cites = hit["cited_by_count"] if hit and hit.get("cited_by_count") else 0
    if n_cites:
        href = f'https://openalex.org/works/{hit["openalex_id"]}'
        actions.append(f'<a class="pub-cites" href="{href}" target="_blank" '
                       f'rel="noopener">Cited by {n_cites:,}</a>')

    return (
        f'<div class="pub-entry fade-in-section" data-pub-searchable '
        f'data-year="{e["year"]}" data-n="{e["n"]}" data-cites="{n_cites}">\n'
        f'<span class="year-badge">{e["year"]}</span>\n'
        f'<a class="pub-title" href="{e["url"]}">{e["title"]}</a>\n'
        f'<div class="pub-meta">{meta}</div>\n'
        f'<div class="pub-actions">\n' + "\n".join(actions) + '\n</div>\n</div>'
    )


def recent_publications(pubs, limit=4):
    """Short references (no author list) for the N most recent papers."""
    entries = pubs["entries"][:limit]
    if not entries:
        return '<p class="pub-empty">No publications loaded.</p>'
    return "\n".join(
        f'<div class="recent-pub">\n'
        f'<a class="recent-pub-title" href="{e["url"]}">{e["title"]}</a>\n'
        f'<div class="recent-pub-meta"><span class="pub-venue">{e["journal"]}</span>. {e["year"]}.</div>\n'
        f'</div>'
        for e in entries
    )


def pub_stats(pubs, citations=None):
    entries = pubs["entries"]
    bits = [f'<span id="pubCount">{len(entries)} publications</span>']
    asof = ''
    totals = (citations or {}).get("totals")
    if totals and totals.get("citations"):
        bits += [f'{totals["citations"]:,} citations',
                 f'h-index {totals["h_index"]}',
                 f'i10-index {totals["i10_index"]}']
        asof = (f'<br><span class="pub-stats-asof">as of {citations.get("as_of", "")} '
                f'({citations.get("source", "")})</span>')
    return '<p class="pub-stats">' + ' &nbsp;&middot;&nbsp; '.join(bits) + asof + '</p>'


def publications_block(pubs, citations=None):
    entries = pubs["entries"]
    cites = (citations or {}).get("by_id", {})
    body = "\n".join(render_pub(e, cites) for e in entries) or '<p class="pub-empty">No publications loaded.</p>'

    toolbar = (
        '<div class="pub-toolbar">\n'
        '<label class="pub-sort-label" for="pubSort">Sort by</label>\n'
        '<select id="pubSort" class="pub-sort">\n'
        '<option value="date">Date</option>\n'
        '<option value="cites">Citations</option>\n'
        '</select>\n'
        '</div>\n'
    )
    search = ('<input type="text" class="pub-search" id="pubSearch" '
              'placeholder="Filter by title, author, journal, or year…" '
              'aria-label="Filter publications">\n')
    return toolbar + search + f'<div class="pub-list" id="pubList">\n{body}\n</div>'


# ---------------------------------------------------------------- search ------
class TextExtractor(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "head"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)

    def text(self):
        return re.sub(r"\s+", " ", " ".join(self.parts)).strip()


def build_search_index(pages_meta):
    idx = []
    for meta in pages_meta:
        html = (OUT / meta["page_file"]).read_text()
        tx = TextExtractor()
        tx.feed(html)
        idx.append(
            {"title": meta["search_title"], "url": meta["page_file"], "content": tx.text()[:4000]}
        )
    (OUT / "assets" / "search.json").write_text(json.dumps(idx, ensure_ascii=False))


# ---------------------------------------------------------------- favicon -----
# the initials are drawn in the page background color so they read as a "cutout"
# of the accent tile: near-black on the dark theme, near-white on the light one.
FAVICON_FG_DARK = "#1c1b18"
FAVICON_FG_LIGHT = "#f9fafb"


def brand_initials(site):
    words = [w for w in re.split(r"\s+", site["short_name"]) if w]
    if len(words) >= 2:
        return (words[0][0] + words[-1][0]).upper()
    parts = re.findall(r"[A-Za-z]", site["short_name"])
    return (parts[0] + (parts[1] if len(parts) > 1 else "")).upper() if parts else "CM"


def write_favicon(site):
    """Standalone favicon.svg for the browser tab. Can't see the site's theme
    toggle, so it follows the OS via prefers-color-scheme."""
    initials = brand_initials(site)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<style>.fg{{fill:{FAVICON_FG_DARK}}}'
        f'@media(prefers-color-scheme:light){{.fg{{fill:{FAVICON_FG_LIGHT}}}}}</style>'
        f'<rect width="64" height="64" rx="14" fill="{site["accent"]}"/>'
        '<text class="fg" x="32" y="44" font-family="Georgia,serif" font-size="28" '
        f'font-weight="700" text-anchor="middle">{initials}</text></svg>'
    )
    (OUT / "favicon.svg").write_text(svg)


def brand_icon_svg(site):
    """Inline SVG for the navbar brand. Uses CSS custom properties so it tracks
    the live data-bs-theme toggle, not just the OS setting."""
    initials = brand_initials(site)
    return (
        '<svg class="brand-icon" width="24" height="24" viewBox="0 0 64 64" '
        'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        '<rect width="64" height="64" rx="14" fill="var(--accent)"/>'
        '<text x="32" y="44" font-family="Georgia,serif" font-size="28" font-weight="700" '
        f'text-anchor="middle" fill="var(--bg-primary)">{initials}</text></svg>'
    )


# ---------------------------------------------------------------- main --------
def parse_front_matter(raw):
    m = FRONT.match(raw)
    meta = {}
    if m:
        for pair in m.group(1).split("|"):
            if ":" in pair:
                k, v = pair.split(":", 1)
                meta[k.strip()] = v.strip()
        raw = raw[m.end():]
    return meta, raw


def main():
    site = json.loads((SRC / "site.json").read_text())
    news = json.loads((SRC / "data" / "news.json").read_text())

    pub_path = SRC / "data" / "publications.json"
    if pub_path.exists():
        pubs = json.loads(pub_path.read_text())
    else:
        pubs = {"count": 0, "entries": []}
        print("build.py: WARNING: src/data/publications.json missing — run "
              "`python3 regenerate_html_pubs.py --json` first.", file=sys.stderr)

    cite_path = SRC / "data" / "citations.json"
    if cite_path.exists():
        citations = json.loads(cite_path.read_text())
    else:
        citations = None
        print("build.py: note: src/data/citations.json missing — publications render "
              "without citation counts. Run `python3 fetch_citations.py` to add them.",
              file=sys.stderr)

    # fresh output
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    shutil.copytree(SRC / "assets", OUT / "assets")

    # cache-busting token for main.css / site.js (they change often; no query
    # string means browsers serve a stale copy after every edit)
    import hashlib
    h = hashlib.sha1()
    for f in ("css/main.css", "js/site.js"):
        h.update((OUT / "assets" / f).read_bytes())
    asset_v = h.hexdigest()[:8]

    # bundled CV download (from repo root) — PDF only; the .docx is not published
    files_dir = OUT / "assets" / "files"
    files_dir.mkdir(exist_ok=True)
    for fn in ("MillerCurriculumVitae.pdf",):
        src = ROOT / fn
        if src.exists():
            shutil.copy(src, files_dir / fn)

    write_favicon(site)

    github = next((s["href"] for s in site["socials"] if s["id"] == "github"), "")
    enabled_sameas = [s["href"] for s in site["socials"]
                      if s.get("href") and not s.get("disabled")
                      and not s["href"].startswith("mailto:")]
    jsonld_sameas = (', "sameAs": [' + ", ".join(f'"{u}"' for u in enabled_sameas) + "]") if enabled_sameas else ""

    base_ctx = {
        "name": site["name"],
        "short_name": site["short_name"],
        "title": site["title"],
        "institution": site["institution"],
        "email": site["email"],
        "url": site["url"].rstrip("/"),
        "photo": site["photo"],
        "accent": site["accent"],
        "accent_hover": site["accent_hover"],
        "year": str(date.today().year),
        "github_url": github,
        "address_html": "<br>".join(site["address_lines"]),
        "societies_html": ", ".join(site["societies"]),
        "pub_count": str(len(pubs["entries"])),
        "jsonld_sameas": jsonld_sameas,
        "asset_v": asset_v,
        "_inc": {
            "navlinks": "",  # placeholder, set per page
            "brand_icon": brand_icon_svg(site),
            "profile_links": profile_links(site),
            "news_timeline": news_items(news, limit=3),
            "news_full": news_items(news, cls="news-item"),
            "publications": publications_block(pubs, citations),
            "pub_stats": pub_stats(pubs, citations),
            "recent_publications": recent_publications(pubs, limit=5),
        },
    }

    shell = (SRC / "partials" / "_page.html").read_text()
    pages = sorted((SRC / "pages").glob("*.html"))
    if not pages:
        die("no pages in src/pages/")

    pages_meta = []
    active_seen = set()
    for page_path in pages:
        raw = page_path.read_text()
        meta, body_src = parse_front_matter(raw)
        page_file = page_path.name
        active = meta.get("active", "")
        active_seen.add(active)
        page_title = meta.get("title", "")
        desc = meta.get("desc", site["description"])
        is_home = active == "home"

        ctx = dict(base_ctx)
        ctx["_inc"] = dict(base_ctx["_inc"])
        ctx["_inc"]["navlinks"] = nav_links(site, active)
        ctx["page_file"] = page_file
        ctx["page_title"] = page_title
        ctx["page_desc"] = desc
        ctx["active"] = active
        ctx["head_title"] = site["name"] if is_home else f"{page_title} · {site['name']}"
        ctx["og_title"] = site["name"] if is_home else page_title
        ctx["body_class"] = ("allnews " if active == "news" else "") + f"page-{active}"

        if is_home:
            body = (
                '<div class="home-grid">\n<div class="home-content">\n'
                + body_src
                + '\n</div>\n<div>\n'
                + render((SRC / "partials" / "sidebar.html").read_text(), ctx, 1)
                + "\n</div>\n</div>"
            )
        else:
            # No page-level fade wrapper: a single element taller than the
            # viewport can never satisfy an IntersectionObserver and would
            # leave the whole page stuck at opacity 0. Instead the top-level
            # card blocks each animate in on scroll (.pub-entry already does).
            body_src = re.sub(
                r'<div class="(section-card|research-card|card-academic)"',
                r'<div class="\1 fade-in-section"',
                body_src,
            )
            body = f'<div class="page-body">\n{body_src}\n</div>'
        ctx["_inc"]["body"] = body

        html = render(shell, ctx)
        stray = TOKEN.search(html)
        if stray:
            die(f"unresolved token {stray.group(0)} in {page_file}")
        (OUT / page_file).write_text(html)
        pages_meta.append({
            "page_file": page_file,
            "search_title": page_title or site["short_name"],
        })

    # asserts
    for item in site["nav"]:
        if item["id"] not in active_seen:
            die(f'nav item "{item["id"]}" has no page with active: {item["id"]}')

    build_search_index(pages_meta)

    print(f"built {len(pages_meta)} pages -> {OUT}")
    print(f"  publications: {len(pubs['entries'])}  (generated {pubs.get('generated', '?')})")
    print(f"  news items:   {len(news)}")

    if "--serve" in sys.argv:
        import functools
        import http.server
        import socketserver

        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(OUT))
        for port in range(8000, 8011):
            try:
                httpd = socketserver.TCPServer(("", port), handler)
            except OSError:
                continue
            print(f"serving http://localhost:{port}  (Ctrl-C to stop)")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\nstopped")
            httpd.server_close()
            break
        else:
            die("ports 8000-8010 are all busy — free one with: lsof -ti tcp:8000 | xargs kill")


if __name__ == "__main__":
    main()
