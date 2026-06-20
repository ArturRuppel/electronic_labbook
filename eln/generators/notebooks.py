#!/usr/bin/env python3
"""Generate the notebooks catalog page (``notebooks.html``).

Notebooks are ``.ipynb`` files under ``ROOT/notebooks`` named by experiment ID
(``SORVI-01`` for a session, ``SORVI`` for the series aggregate). The filename is
the link to the experiment; there is no DB table. Cells are rendered from the
``.ipynb`` JSON with the stdlib — markdown and code only, outputs ignored.
"""

import argparse
import html
import json
import sqlite3
from pathlib import Path

from eln.generators.nav import render_nav
from eln.generators.protocols import markdown_to_html
from eln.sdgl import format_experiment_id, parse_code_folder, parse_id_folder

DEFAULT_DB_NAME = "experiments.db"
DEFAULT_SDGL_DB_NAME = "sdgl.db"


def classify_notebook(stem):
    """Classify a notebook filename stem into an experiment ID.

    Returns a dict with ``kind`` in ``session`` / ``series`` / ``unmatched``.
    """
    sid = parse_id_folder(stem)
    if sid:
        return {
            "kind": "session",
            "code": sid["code"],
            "rep": sid["rep"],
            "excluded": sid["excluded"],
            "id": format_experiment_id(sid["code"], sid["rep"], sid["excluded"]),
        }
    scode = parse_code_folder(stem)
    if scode:
        return {"kind": "series", "code": scode["code"], "id": scode["code"]}
    return {"kind": "unmatched", "code": None, "id": stem}


def render_cells(nb):
    """Render an ``.ipynb`` dict into HTML and count code cells that carry outputs.

    Markdown cells go through ``markdown_to_html``; code cells render as escaped
    ``<pre>`` source. Cell *outputs* are never rendered (notebooks are committed
    without outputs); the returned count lets the caller warn when any are found.
    """
    parts = []
    output_cells = 0
    for cell in nb.get("cells", []):
        source = cell.get("source", [])
        if isinstance(source, list):
            source = "".join(source)
        cell_type = cell.get("cell_type")
        if cell_type == "markdown":
            parts.append(f'<div class="nb-md">{markdown_to_html(source)}</div>')
        elif cell_type == "code":
            if cell.get("outputs"):
                output_cells += 1
            parts.append(f'<pre class="nb-code">{html.escape(source)}</pre>')
        # raw and other cell types are intentionally skipped
    return "\n".join(parts), output_cells


def known_codes(db_path):
    """Return the set of experiment codes in ``experiments.db``.

    Empty set when the DB or the ``experiment_codes`` table is absent, so the
    generator degrades gracefully against an empty/placeholder database.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return set()
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT code FROM experiment_codes").fetchall()
        return {row[0] for row in rows}
    except sqlite3.OperationalError:
        return set()
    finally:
        conn.close()


def notebook_artifacts(root, notebook_rel):
    """List artifacts a notebook produced, from SDGL ``generates`` edges.

    Each item is ``{"path", "status"}`` with ``status`` in ``ok`` / ``modified``
    / ``missing``. Returns ``[]`` when ``sdgl.db`` is absent or has no edges, so
    the page renders fully without SDGL.
    """
    root = Path(root)
    sdgl_db = root / DEFAULT_SDGL_DB_NAME
    if not sdgl_db.exists():
        return []

    from eln.analysis.provenance import verify_provenance
    from eln.sdgl.engine import json_loads

    conn = sqlite3.connect(str(sdgl_db))
    conn.row_factory = sqlite3.Row
    try:
        try:
            rows = conn.execute(
                "SELECT target_id, metadata FROM edges WHERE relation_type = 'generates'"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    finally:
        conn.close()

    status_by_node = {d["node_id"]: d["status"] for d in verify_provenance(root)}
    artifacts = []
    for row in rows:
        meta = json_loads(row["metadata"]) or {}
        notebook = meta.get("notebook") or {}
        if notebook.get("path") == notebook_rel:
            node = row["target_id"]
            path = node[len("dataset:"):] if node.startswith("dataset:") else node
            artifacts.append({"path": path, "status": status_by_node.get(node, "ok")})
    return sorted(artifacts, key=lambda a: a["path"])


NOTEBOOKS_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Notebooks - Electronic Lab Notebook</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                line-height: 1.6; color: #27313a; background: #eef1f4; }}
        .header {{ background: #263646; color: white; padding: 1.25rem 1.5rem; }}
        .header h1 {{ font-size: 1.55rem; margin-bottom: 0.25rem; }}
        .header p {{ color: #d7e0e7; }}
        .nav {{ display: flex; flex-wrap: wrap; gap: 1rem; background: white;
                padding: 0.8rem 1.5rem; border-bottom: 1px solid #d7dde2; }}
        .nav a {{ color: #286b9f; text-decoration: none; font-weight: 650; }}
        .nav a:hover {{ text-decoration: underline; }}
        .container {{ max-width: 1000px; margin: 0 auto; padding: 1.5rem; }}
        .nb-group {{ background: white; border: 1px solid #d7dde2; border-radius: 8px;
                     margin-bottom: 1rem; overflow: hidden; }}
        .nb-head {{ display: flex; justify-content: space-between; align-items: center;
                    cursor: pointer; padding: 1rem 1.5rem; }}
        .nb-head:hover {{ background: #f3f6f8; }}
        .nb-id {{ font-size: 1.15rem; font-weight: 650; color: #24313d;
                  display: flex; align-items: center; gap: 0.75rem; }}
        .expand-icon {{ color: #286b9f; font-size: 1rem; }}
        .badge {{ padding: 0.15rem 0.55rem; border-radius: 999px; font-size: 0.8rem;
                  font-weight: 700; }}
        .badge-series {{ background: #e5efe9; color: #27735f; }}
        .badge-session {{ background: #e7eef5; color: #2a5d86; }}
        .badge-excluded {{ background: #f5e7e7; color: #8a3b3b; }}
        .badge-unmatched {{ background: #f7efd9; color: #8a6d1f; }}
        .nb-body {{ display: none; padding: 1rem 1.5rem 1.5rem; border-top: 1px solid #e0e5e9;
                    margin: 0 1rem; }}
        .nb-warning {{ background: #f7efd9; color: #8a6d1f; padding: 0.5rem 0.75rem;
                       border-radius: 6px; margin-bottom: 1rem; font-size: 0.9rem; }}
        .nb-artifacts {{ margin-bottom: 1rem; }}
        .nb-artifacts h3 {{ font-size: 1rem; color: #53616d; margin-bottom: 0.5rem; }}
        .nb-artifacts li {{ list-style: none; font-size: 0.9rem; }}
        .status-ok {{ color: #27735f; }}
        .status-modified {{ color: #8a6d1f; }}
        .status-missing {{ color: #8a3b3b; }}
        .nb-code {{ background: #f5f7f9; border: 1px solid #e0e5e9; border-radius: 6px;
                    padding: 0.75rem 1rem; margin: 0.75rem 0; overflow-x: auto;
                    font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 0.85rem; }}
        .nb-md {{ margin: 0.75rem 0; }}
        .no-notebooks {{ text-align: center; padding: 3rem; color: #6a7884; }}
        .footer {{ text-align: center; padding: 1.5rem; color: #6a7884;
                   font-size: 0.85rem; margin-top: 2rem; }}
    </style>
</head>
<body>
    <script src="auth.js"></script>
    <div class="header">
        <h1>Notebooks</h1>
        <p>Analysis wrappers linking raw data to derived results</p>
    </div>

    {nav}

    <div class="container">
        {notebooks_html}
    </div>

    <div class="footer">
        Electronic Lab Notebook
    </div>

    <script>
        function toggleNotebook(id) {{
            const body = document.getElementById('body-' + id);
            const icon = document.getElementById('icon-' + id);
            const open = body.style.display === 'block';
            body.style.display = open ? 'none' : 'block';
            icon.textContent = open ? '\\u25b6' : '\\u25bc';
        }}
    </script>
</body>
</html>
"""


def _badges(entry):
    badges = []
    if entry["kind"] == "series":
        badges.append('<span class="badge badge-series">SERIES</span>')
    elif entry["kind"] == "session":
        badges.append('<span class="badge badge-session">SESSION</span>')
        if entry.get("excluded"):
            badges.append('<span class="badge badge-excluded">EXCLUDED</span>')
    if not entry["matched"]:
        badges.append('<span class="badge badge-unmatched">UNMATCHED</span>')
    return "".join(badges)


def _artifacts_html(artifacts):
    if not artifacts:
        return ""
    items = "".join(
        f'<li><span class="status-{a["status"]}">[{a["status"]}]</span> {html.escape(a["path"])}</li>'
        for a in artifacts
    )
    return f'<div class="nb-artifacts"><h3>Artifacts produced</h3><ul>{items}</ul></div>'


def _entry_html(entry):
    eid = entry["id"]
    safe_id = eid.replace(".", "_")
    warning = ""
    if entry["outputs"]:
        warning = (f'<div class="nb-warning">{entry["outputs"]} cell(s) contain outputs — '
                   "notebooks should be committed without outputs.</div>")
    return f"""
        <div class="nb-group">
            <div class="nb-head" onclick="toggleNotebook('{safe_id}')">
                <div class="nb-id">
                    <span class="expand-icon" id="icon-{safe_id}">&#9654;</span>
                    {html.escape(eid)}
                </div>
                <div>{_badges(entry)}</div>
            </div>
            <div class="nb-body" id="body-{safe_id}">
                {warning}
                {_artifacts_html(entry["artifacts"])}
                {entry["cells_html"]}
            </div>
        </div>
    """


def _sort_key(entry):
    code = entry["code"] or ("~" + entry["id"])
    kind_rank = 0 if entry["kind"] == "series" else 1
    return (code, kind_rank, entry.get("rep", 0))


def generate_notebooks(root, catalog_out=None, plugins=None):
    """Generate ``notebooks.html`` from ``ROOT/notebooks/*.ipynb``.

    Output is written to *catalog_out* (default ``root/catalog``). *plugins*
    (default: discovered) supply extra nav links.
    """
    root = Path(root)
    notebooks_dir = root / "notebooks"
    database_path = root / DEFAULT_DB_NAME
    catalog_dir = Path(catalog_out) if catalog_out else root / "catalog"

    codes = known_codes(database_path)
    entries = []
    if notebooks_dir.is_dir():
        for path in sorted(notebooks_dir.glob("*.ipynb")):
            info = classify_notebook(path.stem)
            try:
                nb = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                nb = {"cells": []}
            cells_html, output_cells = render_cells(nb)
            entry = dict(info)
            entry["matched"] = bool(info["code"]) and info["code"] in codes
            entry["cells_html"] = cells_html
            entry["outputs"] = output_cells
            entry["artifacts"] = notebook_artifacts(root, f"notebooks/{path.name}")
            entries.append(entry)

    if entries:
        entries.sort(key=_sort_key)
        notebooks_html = "\n".join(_entry_html(e) for e in entries)
    else:
        notebooks_html = '<div class="no-notebooks">No notebooks yet.</div>'

    html_out = NOTEBOOKS_HTML_TEMPLATE.format(
        nav=render_nav(plugins),
        notebooks_html=notebooks_html,
    )
    catalog_dir.mkdir(parents=True, exist_ok=True)
    output_file = catalog_dir / "notebooks.html"
    output_file.write_text(html_out)
    print(f"Notebook catalog generated at: {output_file}")
    return output_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="data-repo root (holds experiments.db)")
    parser.add_argument("--catalog-out", type=Path, default=None,
                        help="output directory (default: ROOT/catalog)")
    args = parser.parse_args(argv)
    generate_notebooks(args.root, args.catalog_out)


if __name__ == "__main__":
    main()
