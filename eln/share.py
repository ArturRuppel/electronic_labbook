"""Static-bundle export.

Turns the rendered catalog into a self-contained, relative-linked static HTML
bundle openable via ``file://`` or hostable on GitHub Pages. Three granularities:
the whole catalog (:func:`export_all`), a single report, or a single presentation
(:func:`export_item`). The bundle mirrors the live server's flat-at-root URL space
so the generators' relative media links (``reports/…``, ``presentations/…``) work
untouched. Only files the pages actually reference are copied.
"""

import os
import re
import shutil
from pathlib import Path

from eln.generators import generate_all
from eln.generators.protocols import generate_protocol_catalog
from eln.generators.reports import generate_reports

# Refs we never copy: external, in-page, or inline data URIs.
_EXTERNAL = re.compile(r"^(?:[a-z]+:|//|#)")
# Copyable references in a page. Covers double- and single-quoted ``src``/``href``
# and reveal.js ``data-background*`` slide attributes, plus CSS ``url(...)`` in
# inline <style>/.css. Each match yields one populated capture group; the rest empty.
_ATTR = r"(?:src|href|data-background(?:-image|-video|-iframe|-color)?)"
_REF = re.compile(
    rf"""{_ATTR}\s*=\s*"([^"]+)"|{_ATTR}\s*=\s*'([^']+)'|"""
    r"""url\(\s*['"]?([^'")]+)['"]?\s*\)"""
)
# A reference that lands inside a self-contained presentation deck directory.
_PRES_DECK = re.compile(r"^(presentations/[^/]+)/")
# The three fixed, known server-only literals a generated page carries.
_AUTH_JS = re.compile(r'[ \t]*<script src="auth\.js"></script>\n?')
_NAV_GRAPH_LINK = re.compile(r'[ \t]*<a href="/">Data Graph</a>\n?')
_HOME_GRAPH_CARD = re.compile(r'[ \t]*<a href="/" class="card">.*?</a>\s*?\n?', re.DOTALL)
_NAV_BLOCK = re.compile(r'[ \t]*<div class="nav">.*?</div>\s*?\n?', re.DOTALL)


def _local_refs(html):
    """Return in-order local (copyable) ``src``/``href`` targets, query/fragment
    stripped. External (`http:`, `//`, `mailto:`, `#`, `data:`) refs are dropped."""
    out = []
    for groups in _REF.findall(html):
        raw = next((g for g in groups if g), "")
        if not raw or _EXTERNAL.match(raw):
            continue
        ref = raw.split("#", 1)[0].split("?", 1)[0]
        if ref:
            out.append(ref)
    return out


def _staticize(html):
    """Drop the three server-only literals from a generated page (the Data Graph
    nav link + home card, and the ``auth.js`` script). Media links are untouched."""
    html = _AUTH_JS.sub("", html)
    html = _NAV_GRAPH_LINK.sub("", html)
    html = _HOME_GRAPH_CARD.sub("", html)
    return html


def _strip_nav(html):
    """Remove the entire ``<div class="nav">…</div>`` block (single-item exports
    are standalone, with no catalog nav)."""
    return _NAV_BLOCK.sub("", html)


def _copy_tree(src_dir, dest_dir):
    """Copy an entire directory tree verbatim, returning ``(relpaths, bytes)`` of
    the files written. Used for self-contained presentation decks, where reference
    scraping misses assets (CSS ``url()``, reveal.js ``data-background``, etc.)."""
    src_dir, dest_dir = Path(src_dir), Path(dest_dir)
    rels, total = [], 0
    for src in sorted(src_dir.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(src_dir)
        out = dest_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        rels.append(str(rel).replace(os.sep, "/"))
        total += src.stat().st_size
    return rels, total


_HTML_SUFFIXES = {".html", ".htm"}

# Top-level catalog pages. In a single-item bundle these siblings are
# intentionally absent; their cross-links are inert and must not be flagged as
# missing assets.
_CATALOG_PAGES = {"index.html", "experiments.html", "protocols.html",
                  "reports.html", "presentations.html", "admin.html", "sdgl.html"}


def _collect_assets(start_pages, root, dest, generated):
    """Transitively copy every referenced in-tree file into ``dest``.

    ``start_pages`` is a list of ``(base, html)`` where ``base`` is the page's
    directory relative to ``root`` (``""`` for a flat-at-root page); refs resolve
    against it. ``generated`` is the set of relpaths already produced by the
    generators (sibling pages like ``experiments.html``) — referenced but neither
    copied nor flagged missing. Recurses into any copied HTML so nested decks are
    followed. Returns ``(seen, missing, total_bytes)``.
    """
    root, dest = Path(root), Path(dest)
    seen = set(generated)
    decks = set()
    missing, total = [], 0
    queue = list(start_pages)
    while queue:
        base, html = queue.pop()
        for ref in _local_refs(html):
            rel = os.path.normpath(os.path.join(base, ref)).replace(os.sep, "/")
            if rel in seen or rel.startswith(".."):
                continue
            # A reference into a presentation deck pulls the *whole* deck dir in
            # one shot — decks are self-contained and reference their slides in
            # ways the scraper can't fully see (CSS url(), data-background, …).
            m = _PRES_DECK.match(rel)
            if m:
                deck = m.group(1)
                if deck not in decks:
                    decks.add(deck)
                    deck_dir = root / deck
                    if deck_dir.is_dir():
                        rels, nbytes = _copy_tree(deck_dir, dest / deck)
                        total += nbytes
                        seen.update(f"{deck}/{r}" for r in rels)
                    elif not (dest / rel).exists():
                        missing.append(rel)
                continue
            seen.add(rel)
            src = root / rel
            if src.is_file():
                out = dest / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, out)
                total += src.stat().st_size
                if src.suffix.lower() in _HTML_SUFFIXES:
                    queue.append((os.path.dirname(rel), src.read_text(errors="ignore")))
            elif not (dest / rel).exists():
                missing.append(rel)
    return seen, missing, total


def _bundle_stats(dest):
    """Count files and total bytes actually written under ``dest`` — the true
    size of the produced bundle (generated pages + copied assets)."""
    files = [p for p in Path(dest).rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def _assert_dest_outside_root(dest, root):
    """Refuse a destination inside the data-repo tree (so an export can't land in
    reports/ and get published). Raises ValueError; otherwise returns resolved dest."""
    dest, root = Path(dest).resolve(), Path(root).resolve()
    if dest == root or root in dest.parents:
        raise ValueError(f"export destination {dest} is inside the data repo {root}")
    return dest


def export_all(root, dest):
    """Write the full static catalog bundle to ``dest``. Returns a result dict
    ``{files, bytes, missing}``."""
    root = Path(root)
    dest = _assert_dest_outside_root(dest, root)
    dest.mkdir(parents=True, exist_ok=True)

    # 1. Render every catalog page straight into the bundle (flat at root).
    written = generate_all(root, catalog_out=dest)

    # 2. Staticize each generated page in place + collect them as walk seeds.
    generated = set()
    start_pages = []
    for path in written.values():
        rel = Path(path).name
        generated.add(rel)
        text = _staticize(Path(path).read_text())
        Path(path).write_text(text)
        start_pages.append(("", text))

    # 3. Transitively copy referenced assets.
    _seen, missing, _total = _collect_assets(start_pages, root, dest, generated)
    files, total = _bundle_stats(dest)
    return {"files": files, "bytes": total, "missing": missing}


_REDIRECT = ('<!doctype html><meta charset="utf-8">'
             '<meta http-equiv="refresh" content="0; url={target}">'
             '<title>Redirecting…</title><a href="{target}">Open</a>\n')


def export_item(root, dest, kind, ident):
    """Write a standalone bundle for a single ``report``, ``presentation`` or
    ``protocol``.

    ``ident`` is the report path relative to ``root`` (e.g.
    ``reports/weekly/tfm_progress.md``), the presentation directory name under
    ``presentations/``, or the protocol id (the latest version's id). Returns
    ``{files, bytes, missing}``.
    """
    root = Path(root)
    dest = _assert_dest_outside_root(dest, root)
    dest.mkdir(parents=True, exist_ok=True)

    if kind == "report":
        # Render just this report flat at the bundle root as index.html, nav-less.
        path = generate_reports(root, catalog_out=dest, only=ident,
                                output_name="index.html")
        html = _strip_nav(_staticize(Path(path).read_text()))
        Path(path).write_text(html)
        _seen, missing, _total = _collect_assets([("", html)], root, dest,
                                                 generated={"index.html"} | _CATALOG_PAGES)
    elif kind == "protocol":
        # Render just this protocol flat at the bundle root as index.html, nav-less.
        path = generate_protocol_catalog(root, catalog_out=dest, only=ident,
                                         output_name="index.html")
        html = _strip_nav(_staticize(Path(path).read_text()))
        if 'class="protocol-group"' not in html:
            raise ValueError(f"protocol not found: {ident}")
        Path(path).write_text(html)
        _seen, missing, _total = _collect_assets([("", html)], root, dest,
                                                 generated={"index.html"} | _CATALOG_PAGES)
    elif kind == "presentation":
        # Mirror the whole self-contained deck verbatim + a root redirect to it.
        deck = f"presentations/{ident}"
        rel = f"{deck}/index.html"
        deck_dir = root / deck
        if not (deck_dir / "index.html").is_file():
            raise ValueError(f"presentation not found: {rel}")
        _copy_tree(deck_dir, dest / deck)
        (dest / "index.html").write_text(_REDIRECT.format(target=rel))
        missing = []
    else:
        raise ValueError(f"unknown export kind: {kind!r}")

    files, total = _bundle_stats(dest)
    return {"files": files, "bytes": total, "missing": missing}
