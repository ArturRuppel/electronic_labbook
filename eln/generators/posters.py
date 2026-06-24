#!/usr/bin/env python3
"""Generate the posters catalog page (``posters.html``).

Posters are SVG files dropped into ``ROOT/posters/``. Unlike presentations or
documents, a poster's display title is *not* derivable from its filename, so the
curated list of ``{title, file}`` entries is stored in an index file,
``ROOT/posters/posters.json``. The page is a simple SVG displayer: one card per
entry, rendering the SVG. Entries are added via the viewer's Add button (pick a
title and a file already in the posters folder), which writes the index.
"""

import argparse
import html
import json
from pathlib import Path

from eln.generators.nav import render_nav

POSTERS_DIRNAME = "posters"
INDEX_FILENAME = "posters.json"

# A self-contained, full-viewport lightbox: clicking a poster opens it over the
# whole screen (above the edit toolbar) with scroll-to-zoom and drag-to-pan; the
# raw <a href> stays as a no-JS fallback. Defined as plain strings — not inside
# the page f-string — so the JS/HTML braces need no escaping. Works on the live
# server and in static exports alike (no overlay dependency).
POSTER_MODAL = '''
    <div class="poster-modal" id="poster-modal" hidden>
        <div class="poster-modal-stage" id="poster-modal-stage" role="dialog" aria-modal="true" aria-label="Poster preview">
            <div class="poster-modal-paper" id="poster-modal-paper">
                <img class="poster-modal-img" id="poster-modal-img" src="" alt="" draggable="false">
            </div>
        </div>
        <div class="poster-modal-bar">
            <span class="poster-modal-title" id="poster-modal-title"></span>
            <span class="poster-modal-actions">
                <span class="poster-modal-hint">Scroll to zoom · drag to pan · double-click to reset</span>
                <button class="poster-modal-close" type="button" data-close aria-label="Close">&times;</button>
            </span>
        </div>
    </div>'''

POSTER_MODAL_SCRIPT = '''
    <script>
    (function () {
        var modal = document.getElementById('poster-modal');
        if (!modal) return;
        var stage = document.getElementById('poster-modal-stage');
        var paper = document.getElementById('poster-modal-paper');
        var img = document.getElementById('poster-modal-img');
        var titleEl = document.getElementById('poster-modal-title');
        var scale = 1, tx = 0, ty = 0;
        var dragging = false, moved = false, lastX = 0, lastY = 0;
        var MIN = 0.2, MAX = 20;

        function apply() {
            paper.style.transform = 'translate(' + tx + 'px,' + ty + 'px) scale(' + scale + ')';
        }
        function fit() {
            // Center the white paper (sized to the file) in the stage at 1:1.
            scale = 1;
            tx = Math.max(0, (stage.clientWidth - paper.clientWidth) / 2);
            ty = Math.max(0, (stage.clientHeight - paper.clientHeight) / 2);
            apply();
        }
        function openModal(src, title) {
            titleEl.textContent = title || '';
            img.alt = title || '';
            modal.hidden = false;
            document.body.style.overflow = 'hidden';
            scale = 1; tx = 0; ty = 0; apply();
            if (img.getAttribute('src') !== src) {
                img.onload = fit;
                img.src = src;
            } else if (img.complete) {
                fit();
            }
        }
        function closeModal() {
            modal.hidden = true;
            document.body.style.overflow = '';
        }

        stage.addEventListener('wheel', function (e) {
            e.preventDefault();
            var rect = stage.getBoundingClientRect();
            var dx = e.clientX - rect.left, dy = e.clientY - rect.top;
            var ns = Math.min(MAX, Math.max(MIN, scale * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
            var ratio = ns / scale;
            // Keep the point under the cursor fixed while zooming.
            tx = dx - ratio * (dx - tx);
            ty = dy - ratio * (dy - ty);
            scale = ns;
            apply();
        }, { passive: false });

        stage.addEventListener('pointerdown', function (e) {
            dragging = true; moved = false;
            lastX = e.clientX; lastY = e.clientY;
            stage.classList.add('grabbing');
            stage.setPointerCapture(e.pointerId);
        });
        stage.addEventListener('pointermove', function (e) {
            if (!dragging) return;
            tx += e.clientX - lastX;
            ty += e.clientY - lastY;
            lastX = e.clientX; lastY = e.clientY;
            moved = true;
            apply();
        });
        function endDrag() {
            dragging = false;
            stage.classList.remove('grabbing');
        }
        stage.addEventListener('pointerup', endDrag);
        stage.addEventListener('pointercancel', endDrag);
        stage.addEventListener('dblclick', fit);

        // A click on the empty dark stage (not the paper, and not a drag) closes.
        stage.addEventListener('click', function (e) {
            if (!moved && e.target === stage) closeModal();
        });
        modal.querySelectorAll('[data-close]').forEach(function (el) {
            el.addEventListener('click', closeModal);
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && !modal.hidden) closeModal();
        });
        window.addEventListener('resize', function () { if (!modal.hidden) fit(); });

        document.querySelectorAll('.poster-open').forEach(function (a) {
            a.addEventListener('click', function (e) {
                e.preventDefault();
                openModal(a.getAttribute('data-full'), a.getAttribute('data-title'));
            });
        });
    })();
    </script>'''


def _posters_dir(root):
    return Path(root) / POSTERS_DIRNAME


def _index_path(root):
    return _posters_dir(root) / INDEX_FILENAME


def load_index(root):
    """Return the curated poster entries (``[{title, file}, …]``).

    Tolerant of a missing/malformed index: returns ``[]`` so a fresh data repo
    (no posters yet) still generates an empty page instead of erroring.
    """
    path = _index_path(root)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    entries = []
    for item in data if isinstance(data, list) else []:
        title = (item.get("title") or "").strip() if isinstance(item, dict) else ""
        file = (item.get("file") or "").strip() if isinstance(item, dict) else ""
        if title and file:
            entries.append({"title": title, "file": file})
    return entries


def save_index(root, entries):
    """Write the poster entries to the index, creating ``posters/`` if needed."""
    posters_dir = _posters_dir(root)
    posters_dir.mkdir(parents=True, exist_ok=True)
    clean = [
        {"title": e["title"].strip(), "file": e["file"].strip()}
        for e in entries
        if (e.get("title") or "").strip() and (e.get("file") or "").strip()
    ]
    _index_path(root).write_text(
        json.dumps(clean, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return clean


def list_poster_files(root):
    """SVG filenames physically present in ``ROOT/posters/`` (sorted)."""
    posters_dir = _posters_dir(root)
    if not posters_dir.is_dir():
        return []
    return sorted(p.name for p in posters_dir.iterdir()
                  if p.is_file() and p.suffix.lower() == ".svg")


def generate_posters(root, catalog_out=None):
    """Generate ``posters.html`` from the index at ``ROOT/posters/posters.json``.

    Output is written to *catalog_out* (default ``root/catalog``). An entry whose
    SVG file is missing from the folder is rendered with a "file missing" note
    rather than a broken image, so the page never silently drops a poster.
    """
    root = Path(root)
    catalog_dir = Path(catalog_out) if catalog_out else root / "catalog"

    entries = load_index(root)
    present = set(list_poster_files(root))

    if entries:
        cards = ""
        for entry in entries:
            title = html.escape(entry["title"])
            file = entry["file"]
            src = f"{POSTERS_DIRNAME}/{html.escape(file, quote=True)}"
            if file in present:
                figure = (
                    f'<a class="poster-open" href="{src}" target="_blank" rel="noopener" '
                    f'data-full="{src}" data-title="{title}">'
                    f'<img class="poster-img" src="{src}" alt="{title}" loading="lazy"></a>'
                )
            else:
                figure = '<div class="poster-missing">SVG file not found in posters/</div>'
            cards += f"""
            <div class="poster-card" data-poster-file="{html.escape(file, quote=True)}">
                {figure}
                <div class="poster-title">{title}</div>
            </div>"""
        body = f'<div class="poster-grid">{cards}\n        </div>'
    else:
        body = ('<div class="empty">No posters yet. Drop an SVG into the '
                '<code>posters/</code> folder, then use “+ Add poster”.</div>')

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Posters</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #27313a; background: #eef1f4; }}
        .header {{ background: #263646; color: white; padding: 1.25rem 1.5rem; }}
        .header h1 {{ font-size: 1.55rem; margin-bottom: 0.25rem; }}
        .header p {{ color: #d7e0e7; }}
        .nav {{ display: flex; flex-wrap: wrap; gap: 1rem; background: white; padding: 0.8rem 1.5rem; border-bottom: 1px solid #d7dde2; }}
        .nav a {{ color: #286b9f; text-decoration: none; font-weight: 650; }}
        .nav a:hover {{ text-decoration: underline; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 1.5rem; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }}
        .stat-card {{ background: white; padding: 1rem 1.25rem; border: 1px solid #d7dde2; border-radius: 8px; }}
        .stat-card .number {{ font-size: 1.5rem; font-weight: 700; color: #2d6f9f; }}
        .stat-card .label {{ color: #6a7884; margin-top: 0.25rem; font-size: 0.85rem; }}
        .poster-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1.25rem; }}
        .poster-card {{ background: white; border: 1px solid #d7dde2; border-radius: 8px; overflow: hidden; display: flex; flex-direction: column; }}
        .poster-open {{ display: block; background: #f3f6f8; cursor: zoom-in; }}
        .poster-img {{ display: block; width: 100%; height: 260px; object-fit: contain; background: white; }}
        .poster-missing {{ height: 260px; display: flex; align-items: center; justify-content: center; color: #b04a4a; background: #fbf3f3; font-size: 0.9rem; }}
        .poster-title {{ padding: 0.75rem 1rem; font-weight: 600; border-top: 1px solid #e0e5e9; display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }}
        .empty {{ background: white; border: 1px dashed #c3ccd3; border-radius: 8px; padding: 2.5rem; text-align: center; color: #6a7884; }}
        .empty code {{ background: #eef1f4; padding: 0.1rem 0.35rem; border-radius: 4px; }}
        .footer {{ text-align: center; padding: 1.5rem; color: #6a7884; font-size: 0.85rem; margin-top: 2rem; }}
        .poster-modal {{ position: fixed; inset: 0; z-index: 10001; }}
        .poster-modal[hidden] {{ display: none; }}
        .poster-modal-stage {{ position: absolute; inset: 0; overflow: hidden; background: rgba(18, 25, 34, 0.94); cursor: grab; touch-action: none; }}
        .poster-modal-stage.grabbing {{ cursor: grabbing; }}
        .poster-modal-paper {{ position: absolute; top: 0; left: 0; transform-origin: 0 0; background: white; box-shadow: 0 6px 30px rgba(0, 0, 0, 0.45); }}
        .poster-modal-img {{ display: block; max-width: 92vw; max-height: 86vh; user-select: none; -webkit-user-drag: none; }}
        .poster-modal-bar {{ position: absolute; top: 0; left: 0; right: 0; display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 0.7rem 1rem; color: white; pointer-events: none; background: linear-gradient(rgba(18, 25, 34, 0.78), rgba(18, 25, 34, 0)); }}
        .poster-modal-title {{ font-weight: 650; text-shadow: 0 1px 2px rgba(0, 0, 0, 0.45); }}
        .poster-modal-actions {{ display: flex; align-items: center; gap: 1rem; }}
        .poster-modal-hint {{ font-size: 0.8rem; color: #cdd6de; }}
        .poster-modal-close {{ pointer-events: auto; background: rgba(0, 0, 0, 0.4); border: none; color: white; width: 2rem; height: 2rem; border-radius: 50%; font-size: 1.4rem; line-height: 1; cursor: pointer; }}
        .poster-modal-close:hover {{ background: rgba(0, 0, 0, 0.6); }}
    </style>
</head>
<body>
    <script src="auth.js"></script>
    <div class="header">
        <div style="display: flex; align-items: center; gap: 0.8rem;">
            <svg width="34" height="34" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><rect x="12" y="8" width="40" height="48" rx="4" fill="#eef1f4"></rect><line x1="21" y1="8" x2="21" y2="56" stroke="#8aa0b3" stroke-width="1.6"></line><circle cx="16.5" cy="20" r="1.6" fill="#8aa0b3"></circle><circle cx="16.5" cy="32" r="1.6" fill="#8aa0b3"></circle><circle cx="16.5" cy="44" r="1.6" fill="#8aa0b3"></circle><line x1="27" y1="24" x2="46" y2="24" stroke="#42566b" stroke-width="2.4" stroke-linecap="round"></line><line x1="27" y1="32" x2="46" y2="32" stroke="#42566b" stroke-width="2.4" stroke-linecap="round"></line><line x1="27" y1="40" x2="40" y2="40" stroke="#42566b" stroke-width="2.4" stroke-linecap="round"></line></svg>
            <h1>Electronic Lab Notebook</h1>
        </div>
        <p style="margin-left: calc(34px + 0.8rem);">Posters</p>
    </div>

    {render_nav()}

    <div class="container">
        <div class="stats">
            <div class="stat-card">
                <div class="number">{len(entries)}</div>
                <div class="label">Total Posters</div>
            </div>
        </div>

        {body}
    </div>

    <div class="footer">
        Electronic Lab Notebook
    </div>
{POSTER_MODAL}
{POSTER_MODAL_SCRIPT}
</body>
</html>"""

    catalog_dir.mkdir(parents=True, exist_ok=True)
    output_file = catalog_dir / "posters.html"
    output_file.write_text(html_doc)
    print(f"Posters catalog generated at: {output_file}")
    return output_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="data-repo root (holds posters/)")
    parser.add_argument("--catalog-out", type=Path, default=None,
                        help="output directory (default: ROOT/catalog)")
    args = parser.parse_args(argv)
    generate_posters(args.root, args.catalog_out)


if __name__ == "__main__":
    main()
