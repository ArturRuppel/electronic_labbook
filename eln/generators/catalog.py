#!/usr/bin/env python3
"""Generate the experiments catalog page (``experiments.html``) from the database.

Paths are resolved relative to a *data-repo root* that holds ``experiments.db``,
the optional ``sdgl.db`` build artifact, and the output ``catalog/`` directory.
The experiment start date is always derived from the earliest raw-file mtime via
SDGL (see :func:`get_experiment_date_from_files`); it is never stored in the DB.
"""

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

from eln.sdgl import allocate_experiment_codes, format_experiment_id

DEFAULT_DB_NAME = "experiments.db"
DEFAULT_SDGL_DB_NAME = "sdgl.db"


def get_experiment_date_from_files(sdgl_conn, node_id):
    """
    Derive the experiment date: the earliest raw-file mtime, which marks the start
    of the experiment.

    The date is a property of the files, not the experiment, so it is always
    derived here and never read from the database. Only raw acquisition files
    (qualifier='raw') count; processed/derived outputs carry later mtimes.

    Args:
        sdgl_conn: Open sqlite3 connection to the SDGL database (row_factory=Row),
                   or None when the SDGL database is unavailable.
        node_id: The canonical SDGL experiment node id (e.g. "experiment:NESFM-01"),
                 or None when the experiment has no resolvable code.

    Returns:
        str | None: YYYY-MM-DD start date, or None when no raw files are known.
    """
    if sdgl_conn is None or not node_id:
        return None

    try:
        row = sdgl_conn.execute("""
            SELECT MIN(mtime) as min_mtime
            FROM file_locations
            WHERE node_id = ? AND mtime IS NOT NULL AND is_dir = 0
              AND qualifier = 'raw'
        """, (node_id,)).fetchone()

        if not row or row['min_mtime'] is None:
            return None

        return datetime.fromtimestamp(row['min_mtime']).strftime('%Y-%m-%d')

    except Exception:
        return None


def _format_date_cell(derived_date):
    """Render the (file-derived) experiment start date, or a dash when unknown."""
    if derived_date:
        return f'<span title="Start date, derived from earliest raw file">{derived_date}</span>'
    return '<span class="date-missing" title="No raw files found">-</span>'


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Electronic Lab Notebook - Data Catalog</title>
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
            font-weight: 650;
            text-decoration: none;
        }}
        .nav a:hover {{
            text-decoration: underline;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 1.5rem;
        }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }}
        .stat-card {{
            background: white;
            padding: 1rem 1.25rem;
            border: 1px solid #d7dde2;
            border-radius: 8px;
        }}
        .stat-card .number {{
            font-size: 1.5rem;
            font-weight: 700;
            color: #2d6f9f;
        }}
        .stat-card .label {{
            color: #6a7884;
            margin-top: 0.25rem;
            font-size: 0.85rem;
        }}
        .filters {{
            background: white;
            padding: 1rem 1.25rem;
            border: 1px solid #d7dde2;
            border-radius: 8px;
            margin-bottom: 1.5rem;
        }}
        .filter-group {{
            margin-bottom: 1rem;
        }}
        .filter-group label {{
            display: block;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }}
        .filter-group input {{
            width: 100%;
            padding: 0.5rem 0.65rem;
            border: 1px solid #b8c3cc;
            border-radius: 6px;
            font-size: 1rem;
        }}
        .table-container {{
            background: white;
            border: 1px solid #d7dde2;
            border-radius: 8px;
            overflow-x: auto;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.92rem;
            table-layout: fixed;
        }}
        th[data-column="thumbnail"] {{ width: 6%; }}
        th[data-column="experiment_id"] {{ width: 7%; }}
        .exp-id {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-weight: 650; color: #2b5878; white-space: nowrap; }}
        th[data-column="experiment_type"] {{ width: 11%; }}
        th[data-column="date"] {{ width: 7%; }}
        th[data-column="sample"] {{ width: 8%; }}
        th[data-column="cell_types"] {{ width: 10%; }}
        th[data-column="microscope"] {{ width: 11%; }}
        th[data-column="channels"] {{ width: 11%; }}
        th[data-column="protocol"] {{ width: 10%; }}
        th[data-column="tags"] {{ width: 9%; }}
        th[data-column="comments"] {{ width: 17%; }}
        th {{
            background: #f3f6f8;
            color: #53616d;
            padding: 0.65rem;
            text-align: left;
            font-size: 0.8rem;
            font-weight: 600;
            text-transform: uppercase;
            border-bottom: 1px solid #e0e5e9;
            position: sticky;
            top: 0;
            cursor: pointer;
            user-select: none;
        }}
        th:hover {{
            background: #e9eef2;
        }}
        th::after {{
            content: ' ↕';
            opacity: 0.5;
            font-size: 0.8rem;
        }}
        th.sort-asc::after {{
            content: ' ↑';
            opacity: 1;
        }}
        th.sort-desc::after {{
            content: ' ↓';
            opacity: 1;
        }}
        td {{
            padding: 0.65rem;
            border-bottom: 1px solid #e0e5e9;
            vertical-align: top;
        }}
        tr:hover {{
            background: #f9fbfc;
        }}
        tr.hidden {{
            display: none;
        }}
        .protocol-link {{
            color: #286b9f;
            text-decoration: none;
            font-weight: 600;
        }}
        .protocol-link:hover {{
            text-decoration: underline;
        }}
        .comments-cell {{
            font-size: 0.9rem;
            color: #555;
        }}
        .comments-inner {{
            overflow: hidden;
            display: -webkit-box;
            -webkit-line-clamp: 3;
            -webkit-box-orient: vertical;
            cursor: pointer;
            title: "Click to expand";
        }}
        .comments-cell.expanded .comments-inner {{
            display: block;
            overflow: visible;
            -webkit-line-clamp: unset;
        }}
        .tag-chips {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.25rem;
        }}
        .tag-chip {{
            display: inline-block;
            border-radius: 999px;
            background: #e5edf4;
            color: #2b5878;
            font-size: 0.75rem;
            font-weight: 600;
            padding: 0.1rem 0.5rem;
        }}
        .thumb-link {{
            display: inline-block;
        }}
        .thumb-img {{
            max-width: 100%;
            max-height: 56px;
            border-radius: 4px;
            border: 1px solid #d7dde2;
            object-fit: cover;
            display: block;
        }}
        .date-missing {{
            color: #9aa8b3;
        }}
        .no-results {{
            text-align: center;
            padding: 3rem;
            color: #6a7884;
            font-size: 1.1rem;
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
        <h1>Electronic Lab Notebook - Data Catalog</h1>
        <p>Microscopy experiments and documentation</p>
    </div>

    <div class="nav">
        <a href="/">Data Graph</a>
        <a href="experiments.html">Experiments</a>
        <a href="protocols.html">Protocols</a>
        <a href="reports.html">Reports</a>
        <a href="presentations.html">Presentations</a>
    </div>

    <div class="container">
        <div class="stats">
            <div class="stat-card">
                <div class="number">{total_experiments}</div>
                <div class="label">Total Experiments</div>
            </div>
            <div class="stat-card">
                <div class="number">{date_range}</div>
                <div class="label">Date Range</div>
            </div>
        </div>

        <div class="filters">
            <div class="filter-group">
                <label for="search">Search Experiments</label>
                <input type="text" id="search" placeholder="Search by name, cell types, comments...">
            </div>
        </div>

        <div class="table-container">
            <table id="experiments-table">
                <thead>
                    <tr>
                        <th data-column="thumbnail">Preview</th>
                        <th data-column="experiment_id">ID</th>
                        <th data-column="experiment_type">Title</th>
                        <th data-column="date">Date</th>
                        <th data-column="sample">Sample</th>
                        <th data-column="cell_types">Cell Types</th>
                        <th data-column="microscope">Microscope</th>
                        <th data-column="channels">Channels</th>
                        <th data-column="protocol">Protocol</th>
                        <th data-column="tags">Tags</th>
                        <th data-column="comments">Comments</th>
                    </tr>
                </thead>
                <tbody>
                    {experiments_html}
                </tbody>
            </table>
        </div>

        <div class="no-results" id="no-results" style="display: none;">
            No experiments match your search.
        </div>
    </div>

    <div class="footer">
        Electronic Lab Notebook
    </div>

    <script>
        let sortColumn = 'date';
        let sortDirection = 'desc';

        // Table sorting
        document.querySelectorAll('th').forEach(header => {{
            header.addEventListener('click', () => {{
                const column = header.dataset.column;

                if (sortColumn === column) {{
                    sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
                }} else {{
                    sortColumn = column;
                    sortDirection = 'asc';
                }}

                // Update header styling
                document.querySelectorAll('th').forEach(h => {{
                    h.classList.remove('sort-asc', 'sort-desc');
                }});
                header.classList.add(sortDirection === 'asc' ? 'sort-asc' : 'sort-desc');

                sortTable();
            }});
        }});

        function sortTable() {{
            const tbody = document.querySelector('#experiments-table tbody');
            const rows = Array.from(tbody.querySelectorAll('tr'));

            rows.sort((a, b) => {{
                const aValue = a.dataset[sortColumn] || '';
                const bValue = b.dataset[sortColumn] || '';

                if (sortDirection === 'asc') {{
                    return aValue.localeCompare(bValue);
                }} else {{
                    return bValue.localeCompare(aValue);
                }}
            }});

            rows.forEach(row => tbody.appendChild(row));
        }}

        // Search filtering
        document.getElementById('search').addEventListener('input', (e) => {{
            const searchTerm = e.target.value.toLowerCase();
            const rows = document.querySelectorAll('#experiments-table tbody tr');
            let visibleCount = 0;

            rows.forEach(row => {{
                const text = row.textContent.toLowerCase();
                if (text.includes(searchTerm)) {{
                    row.classList.remove('hidden');
                    visibleCount++;
                }} else {{
                    row.classList.add('hidden');
                }}
            }});

            document.getElementById('no-results').style.display = visibleCount === 0 ? 'block' : 'none';
        }});

        // Expand/collapse comments on click
        document.querySelector('#experiments-table tbody').addEventListener('click', (e) => {{
            const cell = e.target.closest('.comments-cell');
            if (cell) cell.classList.toggle('expanded');
        }});

        // Set initial sort
        document.querySelector('th[data-column="date"]').classList.add('sort-desc');
    </script>
</body>
</html>
"""


def generate_catalog(root, catalog_out=None):
    """Generate ``experiments.html`` from the notebook DB under *root*.

    *root* is the data-repo directory holding ``experiments.db`` and the optional
    ``sdgl.db``. Output is written to *catalog_out* (default ``root/catalog``).
    """
    root = Path(root)
    database_path = root / DEFAULT_DB_NAME
    sdgl_db_path = root / DEFAULT_SDGL_DB_NAME
    catalog_dir = Path(catalog_out) if catalog_out else root / "catalog"

    # Make sure every session has a code + repetition so the ID column resolves.
    allocate_experiment_codes(database_path)

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all experiments
    # Date is no longer stored; order by id (insertion order ≈ chronological).
    # Final display order is by derived date, applied after derivation below.
    cursor.execute("""
        SELECT * FROM experiments
        ORDER BY id DESC
    """)
    experiments = [dict(row) for row in cursor.fetchall()]

    # Title -> 5-letter code, used to build the CODE-NN identifier per session.
    cursor.execute("SELECT title, code FROM experiment_codes")
    code_by_title = {row[0]: row[1] for row in cursor.fetchall()}

    # Open the SDGL database once for file-mtime date derivation (reused per
    # experiment below rather than reopened in a loop).
    sdgl_conn = None
    if sdgl_db_path.exists():
        sdgl_conn = sqlite3.connect(sdgl_db_path)
        sdgl_conn.row_factory = sqlite3.Row

    # Get all tags
    cursor.execute("SELECT DISTINCT name FROM tags ORDER BY name")
    all_tags = [row[0] for row in cursor.fetchall()]

    # Get protocol information for linking
    cursor.execute("SELECT id, name, version FROM protocols")
    protocol_map = {}
    for row in cursor.fetchall():
        protocol_map[row[0]] = f"{row[1]} v{row[2]}"

    # Enrich experiments with tags, metadata, and protocols
    for exp in experiments:
        # Get tags
        cursor.execute("""
            SELECT t.name FROM tags t
            INNER JOIN experiment_tags et ON t.id = et.tag_id
            WHERE et.experiment_id = ?
        """, (exp['id'],))
        exp['tags'] = [row[0] for row in cursor.fetchall()]

        # Get metadata
        cursor.execute("""
            SELECT key, value FROM experiment_metadata
            WHERE experiment_id = ?
        """, (exp['id'],))
        exp['metadata'] = {row[0]: row[1] for row in cursor.fetchall()}

        # Get protocol IDs
        cursor.execute("""
            SELECT protocol_id FROM experiment_protocols
            WHERE experiment_id = ?
        """, (exp['id'],))
        exp['protocol_ids'] = [row[0] for row in cursor.fetchall()]

        # Get microscopy channels
        cursor.execute("""
            SELECT channel_order, channel_label, target, modality
            FROM experiment_channels
            WHERE experiment_id = ?
            ORDER BY channel_order
        """, (exp['id'],))
        exp['channels'] = [
            {
                'channel_order': row[0],
                'channel_label': row[1],
                'target': row[2],
                'modality': row[3],
            }
            for row in cursor.fetchall()
        ]
        
        # Derive date from raw data file mtimes (via SDGL). Build the SDGL node id
        # from the canonical experiment_codes mapping (the same identifier shown in
        # the ID column), not a title heuristic, so the lookup actually resolves.
        code = code_by_title.get(exp.get('experiment_type'))
        repetition = exp.get('repetition')
        node_id = None
        if code and repetition is not None:
            node_id = "experiment:" + format_experiment_id(
                code, repetition, bool(exp.get('excluded'))
            )
        exp['derived_date'] = get_experiment_date_from_files(sdgl_conn, node_id)

    conn.close()
    if sdgl_conn is not None:
        sdgl_conn.close()

    # Display newest-first by derived start date; experiments with no raw files
    # (no derivable date) sort last.
    experiments.sort(key=lambda e: e.get('derived_date') or '', reverse=True)

    # Generate statistics from the file-derived dates.
    total_experiments = len(experiments)
    total_tags = len(all_tags)
    derived_dates = [exp['derived_date'] for exp in experiments if exp.get('derived_date')]
    if derived_dates:
        date_range = f"{min(derived_dates)} to {max(derived_dates)}"
    else:
        date_range = "N/A"

    # Generate table rows
    experiments_html = []
    for exp in experiments:
        # Protocol cell - handle multiple protocols
        protocol_ids = exp.get('protocol_ids', [])
        if protocol_ids:
            protocol_links = []
            for pid in protocol_ids:
                if pid in protocol_map:
                    protocol_name = protocol_map[pid].split(' v')[0]  # Get name without version
                    protocol_links.append(f'<a href="protocols.html#{pid}" class="protocol-link">{protocol_name}</a>')
            protocol_cell = ', '.join(protocol_links) if protocol_links else '-'
            # For data attribute, join protocol names without HTML
            protocol_names = ', '.join([protocol_map[pid].split(' v')[0] for pid in protocol_ids if pid in protocol_map])
        else:
            protocol_cell = '-'
            protocol_names = ''

        tags = exp.get('tags', [])
        tags_text = ', '.join(tags)
        tags_cell = (
            '<div class="tag-chips">'
            + ''.join(f'<span class="tag-chip">{tag}</span>' for tag in tags)
            + '</div>'
        ) if tags else '-'

        # Cell types are stored comma-separated; render each as a chip.
        cell_types_text = exp.get('cell_types', '') or ''
        cell_type_parts = [ct.strip() for ct in cell_types_text.split(',') if ct.strip()]
        cell_types_cell = (
            '<div class="tag-chips">'
            + ''.join(f'<span class="tag-chip">{ct}</span>' for ct in cell_type_parts)
            + '</div>'
        ) if cell_type_parts else '-'

        # Microscopy channels: "Blue: F-actin", "Brightfield: DIC", etc.
        channel_parts = []
        for ch in exp.get('channels', []):
            label = ch.get('channel_label', '')
            value = ch.get('target') or ch.get('modality')
            if value:
                channel_parts.append(f"{label}: {value}")
        channels_text = ', '.join(channel_parts)
        channels_cell = (
            '<div class="tag-chips">'
            + ''.join(f'<span class="tag-chip">{p}</span>' for p in channel_parts)
            + '</div>'
        ) if channel_parts else '-'

        # Thumbnail: stored as a path; thumbnails live in the thumbnails/ dir,
        # so reference by filename (relative URL works locally and on Pages).
        thumbnail_path = exp.get('thumbnail_path') or ''
        thumbnail_file = Path(thumbnail_path).name if thumbnail_path else ''
        thumbnail_cell = (
            f'<a class="thumb-link" href="thumbnails/{thumbnail_file}" target="_blank">'
            f'<img class="thumb-img" src="thumbnails/{thumbnail_file}" alt="thumbnail" loading="lazy"></a>'
        ) if thumbnail_file else ''

        # CODE-NN identifier. data-id stays the integer PK (the edit deep-link
        # key); the human-facing ID rides in its own column and data-experiment_id
        # (which also lets the ID column header sort).
        code = code_by_title.get(exp.get('experiment_type'))
        repetition = exp.get('repetition')
        excluded = bool(exp.get('excluded'))
        experiment_code = (
            format_experiment_id(code, repetition, excluded)
            if code and repetition is not None else '-'
        )

        experiments_html.append(f"""
            <tr data-id="{exp['id']}"
                data-experiment_id="{experiment_code}"
                data-experiment_type="{exp.get('experiment_type', '')}"
                data-date="{exp.get('derived_date') or ''}"
                data-sample="{exp.get('live_or_fixed', '')}"
                data-cell_types="{exp.get('cell_types', '')}"
                data-microscope="{exp.get('microscope', '')}"
                data-channels="{channels_text}"
                data-protocol="{protocol_names}"
                data-tags="{tags_text}"
                data-comments="{exp.get('comments', '')}">
                <td>{thumbnail_cell}</td>
                <td><span class="exp-id">{experiment_code}</span></td>
                <td>{exp.get('experiment_type', '-')}</td>
                <td>{_format_date_cell(exp.get('derived_date'))}</td>
                <td>{exp.get('live_or_fixed', '-')}</td>
                <td>{cell_types_cell}</td>
                <td>{exp.get('microscope', '-')}</td>
                <td>{channels_cell}</td>
                <td>{protocol_cell}</td>
                <td>{tags_cell}</td>
                <td class="comments-cell"><div class="comments-inner">{exp.get('comments', '-')}</div></td>
            </tr>
        """)

    # Generate final HTML
    html = HTML_TEMPLATE.format(
        total_experiments=total_experiments,
        date_range=date_range,
        experiments_html='\n'.join(experiments_html),
    )

    # Write to file
    catalog_dir.mkdir(parents=True, exist_ok=True)
    output_file = catalog_dir / "experiments.html"
    output_file.write_text(html)

    print(f"Catalog generated at: {output_file}")
    print(f"Total experiments: {total_experiments}")
    return output_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="data-repo root (holds experiments.db)")
    parser.add_argument("--catalog-out", type=Path, default=None,
                        help="output directory (default: ROOT/catalog)")
    args = parser.parse_args(argv)
    generate_catalog(args.root, args.catalog_out)


if __name__ == "__main__":
    main()
