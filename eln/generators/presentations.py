#!/usr/bin/env python3
"""Generate the presentations catalog page (``presentations.html``).

Scans ``ROOT/presentations``; each subdirectory containing an ``index.html`` is
treated as a presentation. No database is read.
"""

import argparse
import re
from pathlib import Path

from eln.generators.nav import render_nav


def parse_presentation_dir(dirname):
    """Extract date and title from directory name like '2026-01-21_QBio_seminar_Pasteur'."""
    match = re.match(r'(\d{4}-\d{2}-\d{2})_(.*)', dirname)
    if match:
        date = match.group(1)
        title = match.group(2).replace('_', ' ')
        return date, title
    return None, dirname.replace('_', ' ')


def count_slides(pres_dir):
    """Count PNG files in the slides/ subdirectory."""
    slides_dir = pres_dir / "slides"
    if slides_dir.exists():
        return len(list(slides_dir.glob("*.png")))
    return 0


def generate_presentations(root, catalog_out=None):
    """Generate ``presentations.html`` by scanning ``root/presentations``.

    Output is written to *catalog_out* (default ``root/catalog``).
    """
    root = Path(root)
    presentations_dir = root / "presentations"
    catalog_dir = Path(catalog_out) if catalog_out else root / "catalog"

    presentations = []

    if presentations_dir.exists():
        for pres_dir in sorted(presentations_dir.iterdir(), reverse=True):
            if pres_dir.is_dir() and (pres_dir / "index.html").exists():
                date, title = parse_presentation_dir(pres_dir.name)
                slide_count = count_slides(pres_dir)
                presentations.append({
                    'dirname': pres_dir.name,
                    'date': date or '',
                    'title': title,
                    'slide_count': slide_count,
                })

    # Build HTML
    rows = ""
    for p in presentations:
        rows += f"""
            <tr data-pres-dir="{p['dirname']}">
                <td>{p['date']}</td>
                <td><a href="presentations/{p['dirname']}/index.html" class="presentation-link">{p['title']}</a></td>
                <td>{p['slide_count']}</td>
            </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Presentations</title>
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
        .table-container {{ background: white; border: 1px solid #d7dde2; border-radius: 8px; overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; }}
        th {{ background: #f3f6f8; color: #53616d; padding: 0.65rem; text-align: left; font-size: 0.8rem; font-weight: 600; text-transform: uppercase; border-bottom: 1px solid #e0e5e9; }}
        td {{ padding: 0.65rem; border-bottom: 1px solid #e0e5e9; vertical-align: top; }}
        tr:hover {{ background: #f9fbfc; }}
        .presentation-link {{ color: #286b9f; text-decoration: none; font-weight: 600; }}
        .presentation-link:hover {{ text-decoration: underline; }}
        .footer {{ text-align: center; padding: 1.5rem; color: #6a7884; font-size: 0.85rem; margin-top: 2rem; }}
    </style>
</head>
<body>
    <script src="auth.js"></script>
    <div class="header">
        <div style="display: flex; align-items: center; gap: 0.8rem;">
            <svg width="34" height="34" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><rect x="12" y="8" width="40" height="48" rx="4" fill="#eef1f4"></rect><line x1="21" y1="8" x2="21" y2="56" stroke="#8aa0b3" stroke-width="1.6"></line><circle cx="16.5" cy="20" r="1.6" fill="#8aa0b3"></circle><circle cx="16.5" cy="32" r="1.6" fill="#8aa0b3"></circle><circle cx="16.5" cy="44" r="1.6" fill="#8aa0b3"></circle><line x1="27" y1="24" x2="46" y2="24" stroke="#42566b" stroke-width="2.4" stroke-linecap="round"></line><line x1="27" y1="32" x2="46" y2="32" stroke="#42566b" stroke-width="2.4" stroke-linecap="round"></line><line x1="27" y1="40" x2="40" y2="40" stroke="#42566b" stroke-width="2.4" stroke-linecap="round"></line></svg>
            <h1>Electronic Lab Notebook</h1>
        </div>
        <p style="margin-left: calc(34px + 0.8rem);">Presentations</p>
    </div>

    {render_nav()}

    <div class="container">
        <div class="stats">
            <div class="stat-card">
                <div class="number">{len(presentations)}</div>
                <div class="label">Total Presentations</div>
            </div>
        </div>

        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th style="width: 15%;">Date</th>
                        <th>Title</th>
                        <th style="width: 10%;">Slides</th>
                    </tr>
                </thead>
                <tbody>{rows}
                </tbody>
            </table>
        </div>
    </div>

    <div class="footer">
        Electronic Lab Notebook
    </div>
</body>
</html>"""

    catalog_dir.mkdir(parents=True, exist_ok=True)
    output_file = catalog_dir / "presentations.html"
    output_file.write_text(html)
    print(f"Presentations catalog generated at: {output_file}")
    return output_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="data-repo root (holds presentations/)")
    parser.add_argument("--catalog-out", type=Path, default=None,
                        help="output directory (default: ROOT/catalog)")
    args = parser.parse_args(argv)
    generate_presentations(args.root, args.catalog_out)


if __name__ == "__main__":
    main()
