#!/usr/bin/env python3
"""Generate the reports catalog page (``reports.html``) with rendered markdown.

Reports are markdown files under ``ROOT/reports``. A report may embed a DB-generated
experiment overview by declaring ``**Series:** CODE`` and placing a ``{{experiments}}``
token (Plan F): the token is replaced with a series header, a table of active
repetitions (dates derived from raw-file mtimes), and the deduplicated protocols used.
"""

import argparse
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from eln.sdgl import format_experiment_id, parse_code_folder
from eln.generators.catalog import get_experiment_date_from_files
from eln.generators.nav import render_nav

DEFAULT_DB_NAME = "experiments.db"
DEFAULT_SDGL_DB_NAME = "sdgl.db"


def markdown_to_html(text):
    """Simple markdown to HTML converter."""
    if not text:
        return ""

    # Escape HTML
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # Videos (.mp4, .webm, .ogg)
    def replace_media(m):
        alt, src = m.group(1), m.group(2)
        if re.search(r'\.(mp4|webm|ogg)$', src, re.IGNORECASE):
            return f'<video controls style="max-width: 100%; height: auto; margin: 1rem 0;"><source src="{src}" type="video/mp4">{alt}</video>'
        return f'<img src="{src}" alt="{alt}" style="max-width: 100%; height: auto; margin: 1rem 0;">'
    text = re.sub(r'!\[([^\]]*)\]\(([^\)]+)\)', replace_media, text)

    # Links
    text = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', text)

    # Headers
    text = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', text, flags=re.MULTILINE)
    text = re.sub(r'^### (.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^## (.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
    text = re.sub(r'^# (.+)$', r'<h1>\1</h1>', text, flags=re.MULTILINE)

    # Bold and italic
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)

    # Lists
    text = re.sub(r'^\- (.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\. (.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)

    # Wrap consecutive <li> in <ul>
    text = re.sub(r'(<li>.*?</li>\n)+', lambda m: '<ul>' + m.group(0) + '</ul>\n', text, flags=re.DOTALL)

    # Blockquotes
    text = re.sub(r'^&gt; (.+)$', r'<blockquote>\1</blockquote>', text, flags=re.MULTILINE)

    # Code blocks
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # Paragraphs
    text = re.sub(r'\n\n+', '</p><p>', text)
    text = '<p>' + text + '</p>'

    # Clean up empty paragraphs around block elements
    text = re.sub(r'<p>(</?(?:h[1-6]|ul|blockquote|img)>)', r'\1', text)
    text = re.sub(r'(</?(?:h[1-6]|ul|blockquote)>)</p>', r'\1', text)
    text = re.sub(r'<p>\s*</p>', '', text)

    return text


REPORTS_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Progress Reports - Electronic Lab Notebook</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #27313a;
            background: #eef1f4;
        }}
        .header {{
            background: #263646;
            color: white;
            padding: 1.25rem 1.5rem;
        }}
        .header h1 {{
            font-size: 1.55rem;
            margin-bottom: 0.25rem;
        }}
        .header p {{
            color: #d7e0e7;
        }}
        .nav {{
            display: flex;
            flex-wrap: wrap;
            gap: 1rem;
            background: white;
            padding: 0.8rem 1.5rem;
            border-bottom: 1px solid #d7dde2;
        }}
        .nav a {{
            color: #286b9f;
            text-decoration: none;
            font-weight: 650;
        }}
        .nav a:hover {{
            text-decoration: underline;
        }}
        .container {{
            max-width: 1000px;
            margin: 0 auto;
            padding: 1.5rem;
        }}
        .reports-list {{
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }}
        .report-content {{
            line-height: 1.8;
        }}
        .report-content h1 {{
            font-size: 1.8rem;
            margin-top: 1.5rem;
            margin-bottom: 1rem;
            color: #24313d;
        }}
        .report-content h2 {{
            font-size: 1.5rem;
            margin-top: 1.5rem;
            margin-bottom: 0.75rem;
            color: #53616d;
        }}
        .report-content h3 {{
            font-size: 1.2rem;
            margin-top: 1rem;
            margin-bottom: 0.5rem;
            color: #53616d;
        }}
        .report-content h4 {{
            font-size: 1.1rem;
            margin-top: 0.75rem;
            margin-bottom: 0.5rem;
            color: #53616d;
        }}
        .report-content ul {{
            margin: 0.5rem 0 0.5rem 2rem;
        }}
        .report-content li {{
            margin-bottom: 0.25rem;
        }}
        .report-content code {{
            background: #f3f6f8;
            padding: 0.2rem 0.4rem;
            border-radius: 3px;
            font-family: monospace;
            font-size: 0.9em;
        }}
        .report-content blockquote {{
            border-left: 3px solid #2d6f9f;
            padding-left: 1rem;
            margin: 1rem 0;
            color: #53616d;
            background: #f9fbfc;
            padding: 0.5rem 1rem;
            border-radius: 4px;
        }}
        .report-content img {{
            max-width: 100%;
            height: auto;
            display: block;
            margin: 1rem auto;
        }}
        .report-card {{
            background: white;
            border: 1px solid #d7dde2;
            border-radius: 8px;
            margin-bottom: 1rem;
            overflow: hidden;
        }}
        .report-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            padding: 1rem 1.5rem;
            transition: background-color 0.2s;
        }}
        .report-header:hover {{
            background-color: #f3f6f8;
        }}
        .report-title-row {{
            font-size: 1.15rem;
            font-weight: 650;
            color: #24313d;
            display: flex;
            align-items: center;
            gap: 1rem;
        }}
        .report-date {{
            font-size: 0.9rem;
            color: #6a7884;
            font-weight: 500;
        }}
        .expand-icon {{
            display: inline-block;
            margin-right: 0.75rem;
            font-size: 1rem;
            transition: transform 0.2s;
            color: #286b9f;
        }}
        .report-details {{
            display: none;
            padding: 0 1.5rem 1.5rem 1.5rem;
            border-top: 1px solid #e0e5e9;
            margin: 0 1rem;
        }}
        .no-reports {{
            text-align: center;
            padding: 3rem;
            color: #6a7884;
            background: white;
            border: 1px solid #d7dde2;
            border-radius: 8px;
        }}
        .exp-overview {{
            margin: 1.5rem 0;
            padding: 1rem 1.25rem;
            background: #f9fbfc;
            border: 1px solid #e0e5e9;
            border-radius: 8px;
        }}
        .exp-overview-header {{
            display: flex;
            align-items: baseline;
            gap: 0.75rem;
            margin-bottom: 0.75rem;
        }}
        .exp-overview-code {{
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-weight: 650;
            font-size: 0.9rem;
            color: #2b5878;
            background: #e5edf4;
            border-radius: 4px;
            padding: 0.15rem 0.5rem;
        }}
        .exp-overview-title {{
            font-size: 1.15rem;
            font-weight: 650;
            color: #24313d;
        }}
        .exp-overview table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.88rem;
            background: white;
            border: 1px solid #e0e5e9;
            border-radius: 6px;
            overflow: hidden;
        }}
        .exp-overview th {{
            background: #f3f6f8;
            color: #53616d;
            text-align: left;
            padding: 0.5rem 0.65rem;
            font-size: 0.72rem;
            font-weight: 600;
            text-transform: uppercase;
            border-bottom: 1px solid #e0e5e9;
        }}
        .exp-overview td {{
            padding: 0.5rem 0.65rem;
            border-bottom: 1px solid #eef1f4;
            vertical-align: top;
        }}
        .exp-overview tr:last-child td {{
            border-bottom: none;
        }}
        .exp-overview .exp-id {{
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-weight: 650;
            color: #2b5878;
            white-space: nowrap;
        }}
        .exp-overview .tag-chips {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.25rem;
        }}
        .exp-overview .tag-chip {{
            display: inline-block;
            border-radius: 999px;
            background: #e5edf4;
            color: #2b5878;
            font-size: 0.72rem;
            font-weight: 600;
            padding: 0.1rem 0.5rem;
        }}
        .exp-overview .date-missing {{
            color: #9aa8b3;
        }}
        .exp-overview-protocols {{
            margin-top: 0.75rem;
            font-size: 0.9rem;
            color: #53616d;
        }}
        .exp-overview-protocols a {{
            color: #286b9f;
            text-decoration: none;
            font-weight: 600;
        }}
        .exp-overview-protocols a:hover {{
            text-decoration: underline;
        }}
        .exp-overview-error {{
            color: #9a3b3b;
            background: #fbeaea;
            border: 1px solid #e6c4c4;
            border-radius: 6px;
            padding: 0.6rem 0.9rem;
            font-size: 0.9rem;
        }}
        .exp-overview-empty {{
            color: #6a7884;
            font-style: italic;
        }}
        .footer {{
            text-align: center;
            padding: 1.5rem;
            color: #6a7884;
            font-size: 0.85rem;
            margin-top: 2rem;
        }}
    </style>
</head>
<body>
    <script src="auth.js"></script>
    <div class="header">
        <h1>Progress Reports</h1>
        <p>Experimental documentation and updates</p>
    </div>

    {nav}

    <div class="container">
        <div class="reports-list">
            {reports_html}
        </div>
    </div>

    <div class="footer">
        Electronic Lab Notebook
    </div>

    <script>
        function toggleReport(slug) {{
            const details = document.getElementById('details-' + slug);
            const icon = document.getElementById('icon-' + slug);
            if (details.style.display === 'none' || details.style.display === '') {{
                details.style.display = 'block';
                icon.style.transform = 'rotate(90deg)';
            }} else {{
                details.style.display = 'none';
                icon.style.transform = 'rotate(0deg)';
            }}
        }}

        window.addEventListener('DOMContentLoaded', function() {{
            const hash = window.location.hash.substring(1);
            if (hash) {{
                const details = document.getElementById('details-' + hash);
                if (details) {{
                    details.style.display = 'block';
                    document.getElementById('icon-' + hash).style.transform = 'rotate(90deg)';
                    setTimeout(function() {{
                        document.getElementById('report-' + hash).scrollIntoView({{behavior: 'smooth'}});
                    }}, 100);
                }}
            }}
        }});
    </script>
</body>
</html>
"""


# The series declaration captures any 5-char token; the SDGL code grammar (which
# allows letters and digits, e.g. COV2D) is the authority on whether it is a code.
SERIES_RE = re.compile(r'\*\*Series:\*\*\s*(\S{5})')
PLACEHOLDER = "{{experiments}}"


def parse_series(content):
    """Return the declared series code (e.g. 'COV2D') from a '**Series:** CODE'
    line, or None if the report declares no valid series code."""
    m = SERIES_RE.search(content)
    if not m:
        return None
    parsed = parse_code_folder(m.group(1))
    return parsed["code"] if parsed else None


def lookup_series_title(code, eln_conn):
    """Canonical title for a series ``code`` from ``experiment_codes``, or None
    when no code is given or it isn't a known series."""
    if not code:
        return None
    row = eln_conn.execute(
        "SELECT title FROM experiment_codes WHERE code = ?", (code,)
    ).fetchone()
    return row["title"] if row else None


def _chips(items):
    """Render a list of strings as tag chips, matching the catalog styling."""
    items = [i for i in items if i]
    if not items:
        return '<span class="date-missing">-</span>'
    return (
        '<div class="tag-chips">'
        + ''.join(f'<span class="tag-chip">{i}</span>' for i in items)
        + '</div>'
    )


def build_experiments_block(code, eln_conn, sdgl_conn):
    """Build the self-contained HTML overview for a series: header (code + title),
    a table of active repetitions, and the deduplicated protocols used.

    A typo'd / unknown series code renders an inline error note rather than
    crashing, so the mistake is visible in the rendered report.
    """
    title_row = eln_conn.execute(
        "SELECT title FROM experiment_codes WHERE code = ?", (code,)
    ).fetchone()
    if not title_row:
        return (
            f'<div class="exp-overview-error">Unknown experiment series '
            f'<code>{code}</code> — no matching code in the database.</div>'
        )
    series_title = title_row["title"]

    # Active repetitions only (excluded = 0), ordered by repetition number.
    experiments = eln_conn.execute(
        "SELECT * FROM experiments WHERE experiment_type = ? AND excluded = 0 "
        "ORDER BY repetition",
        (series_title,),
    ).fetchall()

    rows = []
    protocols = {}  # protocol_id -> name (deduplicated union across experiments)
    for exp in experiments:
        experiment_code = format_experiment_id(code, exp["repetition"], False)
        node_id = "experiment:" + experiment_code
        derived_date = get_experiment_date_from_files(sdgl_conn, node_id)
        date_cell = (
            f'<span title="Start date, derived from earliest raw file">{derived_date}</span>'
            if derived_date else '<span class="date-missing">—</span>'
        )

        cell_types = [c.strip() for c in (exp["cell_types"] or "").split(",") if c.strip()]

        channel_parts = []
        for ch in eln_conn.execute(
            "SELECT channel_label, target, modality FROM experiment_channels "
            "WHERE experiment_id = ? ORDER BY channel_order",
            (exp["id"],),
        ):
            value = ch["target"] or ch["modality"]
            if value:
                channel_parts.append(f'{ch["channel_label"]}: {value}')

        tags = [
            r["name"] for r in eln_conn.execute(
                "SELECT t.name FROM tags t "
                "INNER JOIN experiment_tags et ON t.id = et.tag_id "
                "WHERE et.experiment_id = ? ORDER BY t.name",
                (exp["id"],),
            )
        ]

        for pr in eln_conn.execute(
            "SELECT p.id, p.name FROM protocols p "
            "INNER JOIN experiment_protocols ep ON p.id = ep.protocol_id "
            "WHERE ep.experiment_id = ?",
            (exp["id"],),
        ):
            protocols[pr["id"]] = pr["name"]

        rows.append(f"""
                <tr>
                    <td><span class="exp-id">{experiment_code}</span></td>
                    <td>{date_cell}</td>
                    <td>{_chips(cell_types)}</td>
                    <td>{exp["microscope"] or '<span class="date-missing">-</span>'}</td>
                    <td>{_chips(channel_parts)}</td>
                    <td>{_chips(tags)}</td>
                </tr>""")

    if rows:
        table = f"""
            <table>
                <thead>
                    <tr>
                        <th>ID</th><th>Date</th><th>Cell Types</th>
                        <th>Microscope</th><th>Channels</th><th>Tags</th>
                    </tr>
                </thead>
                <tbody>{''.join(rows)}
                </tbody>
            </table>"""
    else:
        table = '<p class="exp-overview-empty">No active repetitions recorded for this series.</p>'

    if protocols:
        links = ', '.join(
            f'<a href="protocols.html#{pid}">{protocols[pid]}</a>'
            for pid in sorted(protocols)
        )
        protocols_html = f'<div class="exp-overview-protocols"><strong>Protocols used:</strong> {links}</div>'
    else:
        protocols_html = ''

    return f"""<div class="exp-overview">
            <div class="exp-overview-header">
                <span class="exp-overview-code">{code}</span>
                <span class="exp-overview-title">{series_title}</span>
            </div>{table}{protocols_html}
        </div>"""


def extract_report_date(content, report_file):
    """
    Extract report date from related experiments or file metadata.
    
    Priority:
    1. Explicit "**Date:**" declaration (single date or "X to Y" range)
    2. Extract dates from "Related Experiments" links in markdown
    3. Fall back to directory name if it contains a date
    4. Fall back to file modification time

    Returns a date string (single date or range like "YYYY-MM-DD to YYYY-MM-DD")
    """
    # Explicit "**Date:**" declaration takes priority. Supports a single date or
    # an "X to Y" range; reports converted to the **Series:** format no longer
    # carry [date](experiments.html) links, so this is the stable date source.
    date_decl = re.search(
        r'\*\*Date:\*\*\s*(\d{4}-\d{2}-\d{2})(?:\s+to\s+(\d{4}-\d{2}-\d{2}))?',
        content,
    )
    if date_decl:
        start, end = date_decl.group(1), date_decl.group(2)
        return f"{start} to {end}" if end else start

    # Try to extract dates from Related Experiments links
    # Pattern: [YYYY-MM-DD](experiments.html) or similar
    exp_date_pattern = r'\[(\d{4}-\d{2}-\d{2})\]\(experiments\.html\)'
    exp_dates = re.findall(exp_date_pattern, content)
    
    if exp_dates:
        # Sort dates and create range
        sorted_dates = sorted(exp_dates)
        if len(sorted_dates) == 1:
            return sorted_dates[0]
        else:
            return f"{sorted_dates[0]} to {sorted_dates[-1]}"
    
    # Try to extract date from directory name (e.g., "2026-02_NestinKO" or "2026-05-05_Bluesky")
    dir_name = report_file.parent.name
    date_match = re.match(r'(\d{4}-\d{2}-\d{2})', dir_name)
    if date_match:
        return date_match.group(1)
    
    # Try to extract date from filename (e.g., "2026-05-05_Bluesky_thread.md")
    file_date_match = re.match(r'(\d{4}-\d{2}-\d{2})', report_file.stem)
    if file_date_match:
        return file_date_match.group(1)
    
    # Fall back to file modification time
    mtime = report_file.stat().st_mtime
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")


# Markers delimiting the generator-owned region of an auto series report. The
# scaffolder only ever rewrites the text *between* these markers, so prose a human
# adds outside them survives regeneration.
AUTO_START = "<!-- AUTO:START -->"
AUTO_END = "<!-- AUTO:END -->"
AUTO_SUBDIR = "auto"
_AUTO_BLOCK_RE = re.compile(re.escape(AUTO_START) + r".*?" + re.escape(AUTO_END), re.DOTALL)


def _series_earliest_date(code, title, eln_conn, sdgl_conn):
    """Earliest file-derived start date across a series' active repetitions, or
    None when no raw-file dates are known (same source as the overview table)."""
    dates = []
    for exp in eln_conn.execute(
        "SELECT repetition FROM experiments WHERE experiment_type = ? AND excluded = 0",
        (title,),
    ):
        node_id = "experiment:" + format_experiment_id(code, exp["repetition"], False)
        derived = get_experiment_date_from_files(sdgl_conn, node_id)
        if derived:
            dates.append(derived)
    return min(dates) if dates else None


def _auto_block(code, date):
    """The generator-owned skeleton for a series report: the ``**Series:** CODE``
    line the scanner keys off, an optional ``**Date:**``, and the
    ``{{experiments}}`` token rendered by :func:`generate_reports`."""
    lines = [AUTO_START, f"**Series:** {code}", ""]
    if date:
        lines += [f"**Date:** {date}", ""]
    lines += [PLACEHOLDER, AUTO_END]
    return "\n".join(lines)


def generate_series_reports(root):
    """Scaffold/refresh one auto report per experiment series under
    ``reports/auto/<CODE>.md``.

    Each stub carries a marker-delimited generated block (``**Series:** CODE`` +
    ``{{experiments}}``) that the existing report pipeline renders and the SDGL
    scanner indexes — no extra wiring. A series already covered by a hand-authored
    report (any report *outside* ``reports/auto/`` that declares it) is skipped, so
    there is exactly one report per series. Regeneration rewrites only the marked
    block (refreshing the date), preserving any prose a human added around it.
    Returns the list of written stub paths.
    """
    root = Path(root)
    reports_dir = root / "reports"
    auto_dir = reports_dir / AUTO_SUBDIR
    database_path = root / DEFAULT_DB_NAME
    sdgl_db_path = root / DEFAULT_SDGL_DB_NAME

    eln_conn = sqlite3.connect(database_path)
    eln_conn.row_factory = sqlite3.Row
    sdgl_conn = None
    if sdgl_db_path.exists():
        sdgl_conn = sqlite3.connect(sdgl_db_path)
        sdgl_conn.row_factory = sqlite3.Row

    # Series already claimed by a hand-authored report (declared outside auto/).
    human_claimed = set()
    if reports_dir.exists():
        for f in reports_dir.glob("**/*.md"):
            if f.name.lower() == "readme.md" or auto_dir in f.parents:
                continue
            declared = parse_series(f.read_text())
            if declared:
                human_claimed.add(declared)

    written = []
    for row in eln_conn.execute("SELECT code, title FROM experiment_codes ORDER BY code"):
        code, title = row["code"], row["title"]
        if code in human_claimed:
            continue
        block = _auto_block(code, _series_earliest_date(code, title, eln_conn, sdgl_conn))
        auto_path = auto_dir / f"{code}.md"
        if auto_path.exists():
            text = auto_path.read_text()
            # Replace only the marked block; never use re.sub's template (the block
            # holds literal braces/backslashes), so pass a function replacement.
            if _AUTO_BLOCK_RE.search(text):
                text = _AUTO_BLOCK_RE.sub(lambda _m: block, text, count=1)
            else:
                text = block + "\n\n" + text
        else:
            text = block + "\n"
        auto_dir.mkdir(parents=True, exist_ok=True)
        auto_path.write_text(text)
        written.append(auto_path)

    eln_conn.close()
    if sdgl_conn is not None:
        sdgl_conn.close()
    return written


def notebook_markdown(nb):
    """Concatenated source of a notebook's **markdown cells**, blank-line joined.

    Code cells and all cell outputs are dropped entirely — a notebook report is
    rendered as prose + embedded figures, never as code. The returned text is fed
    through the same markdown pipeline as a .md report (so ``**Series:**``,
    ``{{experiments}}``, ``**Date:**`` and relative-image rewriting all apply)."""
    parts = []
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "markdown":
            continue
        source = cell.get("source", [])
        if isinstance(source, list):
            source = "".join(source)
        parts.append(source)
    return "\n\n".join(parts)


def generate_reports(root, catalog_out=None, plugins=None, only=None,
                     output_name="reports.html"):
    """Generate ``reports.html`` from markdown reports under *root*.

    *root* is the data-repo directory holding ``reports/``, ``experiments.db`` and
    the optional ``sdgl.db``. Output is written to *catalog_out* (default ``root/catalog``).
    *plugins* (default: discovered) supply extra nav links. *only* (a path relative
    to *root*, e.g. ``reports/weekly/x.md``) restricts the page to a single report —
    used by the static-bundle export — and *output_name* names the output file.
    """
    root = Path(root)
    reports_dir = root / "reports"
    database_path = root / DEFAULT_DB_NAME
    sdgl_db_path = root / DEFAULT_SDGL_DB_NAME
    catalog_dir = Path(catalog_out) if catalog_out else root / "catalog"

    if not reports_dir.exists():
        reports_dir.mkdir(parents=True)

    # Reports are markdown or notebook files under reports/ (recursively).
    # README.md is the folder's own documentation, not a report — skip it.
    report_files = sorted(
        (p for p in reports_dir.glob("**/*")
         if p.suffix in (".md", ".ipynb") and p.name.lower() != "readme.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if only is not None:
        only_path = (root / only).resolve()
        report_files = [p for p in report_files if p.resolve() == only_path]

    if not report_files:
        reports_html = '<div class="no-reports">No reports available yet. Create markdown files in the reports/ directory.</div>'
    else:
        # Open the ELN DB (series/experiment/protocol data) and the SDGL DB
        # (file-mtime date derivation) once, reused across reports. SDGL is
        # optional — guarded like generate_catalog.py.
        eln_conn = sqlite3.connect(database_path)
        eln_conn.row_factory = sqlite3.Row
        sdgl_conn = None
        if sdgl_db_path.exists():
            sdgl_conn = sqlite3.connect(sdgl_db_path)
            sdgl_conn.row_factory = sqlite3.Row

        reports_html_list = []
        for report_file in report_files:
            if report_file.suffix == ".ipynb":
                content = notebook_markdown(json.loads(report_file.read_text()))
            else:
                content = report_file.read_text()

            # Fix relative image paths to be relative to catalog directory
            report_dir = report_file.parent.relative_to(root)
            content = re.sub(
                r'!\[([^\]]*)\]\((?!http|/)([^\)]+)\)',
                lambda m: f'![{m.group(1)}]({report_dir}/{m.group(2)})',
                content
            )

            html_content = markdown_to_html(content)

            # The declared series ('**Series:** CODE') is the single coverage
            # signal, shared by the card title below and the {{experiments}} block.
            series_code = parse_series(content)

            # Inject the DB-generated experiment overview where the author placed
            # the {{experiments}} token. The token survives markdown conversion as
            # literal text, so we substitute here (post-escaping) to keep the
            # generated HTML intact. No token → pass-through (e.g. Bluesky thread).
            if PLACEHOLDER in html_content:
                if series_code:
                    block = build_experiments_block(series_code, eln_conn, sdgl_conn)
                else:
                    block = ('<div class="exp-overview-error">No <code>**Series:**</code> '
                             'declared for this overview.</div>')
                # The token sits on its own line, so the paragraph pass wraps it
                # as <p>{{experiments}}</p>; strip that wrapper so the block isn't
                # nested inside a <p>.
                wrapped = f"<p>{PLACEHOLDER}</p>"
                if wrapped in html_content:
                    html_content = html_content.replace(wrapped, block)
                else:
                    html_content = html_content.replace(PLACEHOLDER, block)

            # Card title: a series-linked report uses the canonical experiment
            # identity ("CODE — title" from experiment_codes) so the header matches
            # the Experiments page; the markdown H1 is ignored for the header (it
            # still renders in the body). Reports with no series — or an unknown
            # series code — fall back to the H1, then the filename.
            series_title = lookup_series_title(series_code, eln_conn)
            if series_title:
                title = f"{series_code} — {series_title}"
            else:
                title_match = re.search(r'^# (.+)$', content, re.MULTILINE)
                title = title_match.group(1).strip() if title_match else report_file.stem.replace('_', ' ').replace('-', ' ').title()
            slug = report_file.stem
            
            # Auto-populate date from related experiments or file metadata
            report_date = extract_report_date(content, report_file)

            rel_src = report_file.relative_to(root).as_posix()
            reports_html_list.append(f"""
                <div class="report-card" id="report-{slug}" data-report-src="{rel_src}">
                    <div class="report-header" onclick="toggleReport('{slug}')">
                        <div class="report-title-row">
                            <span class="expand-icon" id="icon-{slug}">&#9658;</span>
                            {title}
                        </div>
                        <div class="report-date">{report_date}</div>
                    </div>
                    <div class="report-details" id="details-{slug}">
                        <div class="report-content">
                            {html_content}
                        </div>
                    </div>
                </div>
            """)

        reports_html = '\n'.join(reports_html_list)

        eln_conn.close()
        if sdgl_conn is not None:
            sdgl_conn.close()

    # Generate final HTML
    html = REPORTS_HTML_TEMPLATE.format(
        nav=render_nav(plugins),
        reports_html=reports_html,
    )

    # Write to file
    catalog_dir.mkdir(parents=True, exist_ok=True)
    output_file = catalog_dir / output_name
    output_file.write_text(html)

    print(f"Reports page generated at: {output_file}")
    print(f"Total reports: {len(report_files)}")
    return output_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="data-repo root (holds reports/, experiments.db)")
    parser.add_argument("--catalog-out", type=Path, default=None,
                        help="output directory (default: ROOT/catalog)")
    parser.add_argument("--scaffold-series", action="store_true",
                        help="create/refresh one auto report per series under "
                             "reports/auto/ before rendering")
    args = parser.parse_args(argv)
    if args.scaffold_series:
        written = generate_series_reports(args.root)
        print(f"Scaffolded {len(written)} series report(s) under reports/auto/.")
    generate_reports(args.root, args.catalog_out)


if __name__ == "__main__":
    main()
