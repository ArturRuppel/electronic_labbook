"""Static-bundle export (Roadmap step 12).

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

# Refs we never copy: external, in-page, or inline data URIs.
_EXTERNAL = re.compile(r"^(?:[a-z]+:|//|#)")
_REF = re.compile(r'(?:src|href)="([^"]+)"')
# The three fixed, known server-only literals a generated page carries.
_AUTH_JS = re.compile(r'[ \t]*<script src="auth\.js"></script>\n?')
_NAV_GRAPH_LINK = re.compile(r'[ \t]*<a href="/">Data Graph</a>\n?')
_HOME_GRAPH_CARD = re.compile(r'[ \t]*<a href="/" class="card">.*?</a>\s*?\n?', re.DOTALL)
_NAV_BLOCK = re.compile(r'[ \t]*<div class="nav">.*?</div>\s*?\n?', re.DOTALL)


def _local_refs(html):
    """Return in-order local (copyable) ``src``/``href`` targets, query/fragment
    stripped. External (`http:`, `//`, `mailto:`, `#`, `data:`) refs are dropped."""
    out = []
    for raw in _REF.findall(html):
        if _EXTERNAL.match(raw):
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


_HTML_SUFFIXES = {".html", ".htm"}


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
    missing, total = [], 0
    queue = list(start_pages)
    while queue:
        base, html = queue.pop()
        for ref in _local_refs(html):
            rel = os.path.normpath(os.path.join(base, ref)).replace(os.sep, "/")
            if rel in seen or rel.startswith(".."):
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
    _seen, missing, total = _collect_assets(start_pages, root, dest, generated)
    return {"files": len(_seen) - len(generated), "bytes": total, "missing": missing}
