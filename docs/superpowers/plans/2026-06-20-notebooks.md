# Notebooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add notebooks as a first-class catalog element — `.ipynb` wrappers in `ROOT/notebooks/` named by experiment ID, rendered (text + code, no outputs) into `notebooks.html` alongside protocols, with a provenance panel listing the artifacts each notebook produced.

**Architecture:** A new file-driven generator (`eln/generators/notebooks.py`) scans `ROOT/notebooks/*.ipynb`, parses each filename stem to an experiment ID via the existing SDGL grammar, renders cells by parsing the `.ipynb` JSON with the stdlib (no `nbconvert`), and reads `sdgl.db` `generates` edges to show produced artifacts. It is wired into `generate_all`, the nav bar, and the server's served-pages set. No `experiments.db` schema change; notebook files are read-only.

**Tech Stack:** Python 3.9+, stdlib `json`/`sqlite3`/`html`, existing `eln.sdgl` parsers, `eln.generators.nav`/`protocols`, `eln.analysis.provenance`. Tests with pytest (`/home/aruppel/miniconda3/bin/pytest`).

---

## File structure

- **Create** `eln/generators/notebooks.py` — the generator + helpers (`classify_notebook`, `render_cells`, `known_codes`, `notebook_artifacts`, `generate_notebooks`, `main`).
- **Modify** `eln/generators/nav.py` — add the Notebooks core nav link.
- **Modify** `eln/generators/__init__.py` — import/export `generate_notebooks`, add it to `generate_all`.
- **Modify** `eln/server/app.py` — add `"notebooks.html"` to `CORE_GENERATED_PAGES`.
- **Create** `tests/generators/test_notebooks.py` — unit tests for helpers + generator.
- **Create** `sample_data/notebooks/SORVI-01.ipynb` — a minimal sample notebook.

**Conventions:** the executor runs tests with the canonical env, e.g. `/home/aruppel/miniconda3/bin/pytest`. If `pytest` resolves to that path on `PATH`, the bare command is fine. Commits go on `main` (matches this repo's workflow).

---

### Task 1: Notebook generator module skeleton + ID classification

**Files:**
- Create: `eln/generators/notebooks.py`
- Test: `tests/generators/test_notebooks.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/generators/test_notebooks.py
from eln.generators.notebooks import classify_notebook


def test_classify_session():
    info = classify_notebook("SORVI-01")
    assert info == {"kind": "session", "code": "SORVI", "rep": 1,
                    "excluded": False, "id": "SORVI-01"}


def test_classify_excluded_session():
    info = classify_notebook("COV2D-X03")
    assert info["kind"] == "session"
    assert info["excluded"] is True
    assert info["id"] == "COV2D-X03"


def test_classify_series():
    assert classify_notebook("SORVI") == {"kind": "series", "code": "SORVI", "id": "SORVI"}


def test_classify_unmatched():
    assert classify_notebook("scratch") == {"kind": "unmatched", "code": None, "id": "scratch"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/generators/test_notebooks.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError: cannot import name 'classify_notebook'`.

- [ ] **Step 3: Write minimal implementation**

```python
# eln/generators/notebooks.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/generators/test_notebooks.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add eln/generators/notebooks.py tests/generators/test_notebooks.py
git commit -m "feat(notebooks): notebook id classification from filename stem"
```

---

### Task 2: Render `.ipynb` cells (markdown + code, ignore outputs)

**Files:**
- Modify: `eln/generators/notebooks.py`
- Test: `tests/generators/test_notebooks.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/generators/test_notebooks.py
from eln.generators.notebooks import render_cells


def _nb(cells):
    return {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}


def test_render_markdown_and_code():
    nb = _nb([
        {"cell_type": "markdown", "source": ["# Title\n", "\n", "Some **prose**.\n"]},
        {"cell_type": "code", "source": ["import numpy as np\n", "x = np.arange(3)\n"],
         "outputs": [], "execution_count": 1},
    ])
    html_out, output_cells = render_cells(nb)
    assert output_cells == 0
    assert "<h1>Title</h1>" in html_out
    assert "<strong>prose</strong>" in html_out
    assert "import numpy as np" in html_out
    assert 'class="nb-code"' in html_out


def test_render_ignores_outputs_and_counts_them():
    nb = _nb([
        {"cell_type": "code", "source": ["print('hi')\n"],
         "outputs": [{"output_type": "stream", "name": "stdout", "text": ["hi\n"]}],
         "execution_count": 1},
    ])
    html_out, output_cells = render_cells(nb)
    assert output_cells == 1
    # The output content is NOT rendered into the page.
    assert "stdout" not in html_out
    assert "print(&#x27;hi&#x27;)" in html_out  # source is html-escaped


def test_render_source_as_plain_string():
    nb = _nb([{"cell_type": "code", "source": "a = 1\n", "outputs": []}])
    html_out, _ = render_cells(nb)
    assert "a = 1" in html_out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/generators/test_notebooks.py -k render -v`
Expected: FAIL with `ImportError: cannot import name 'render_cells'`.

- [ ] **Step 3: Write minimal implementation**

Add to `eln/generators/notebooks.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/generators/test_notebooks.py -k render -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add eln/generators/notebooks.py tests/generators/test_notebooks.py
git commit -m "feat(notebooks): render ipynb markdown+code cells, ignore outputs"
```

---

### Task 3: Known-codes lookup (matched vs. flagged)

**Files:**
- Modify: `eln/generators/notebooks.py`
- Test: `tests/generators/test_notebooks.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/generators/test_notebooks.py
import sqlite3
from eln.generators.notebooks import known_codes


def _make_db_with_codes(path, codes):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE experiment_codes (title TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE)")
    for i, code in enumerate(codes):
        conn.execute("INSERT INTO experiment_codes (title, code) VALUES (?, ?)", (f"t{i}", code))
    conn.commit()
    conn.close()


def test_known_codes_reads_table(tmp_path):
    db = tmp_path / "experiments.db"
    _make_db_with_codes(db, ["SORVI", "COV2D"])
    assert known_codes(db) == {"SORVI", "COV2D"}


def test_known_codes_missing_db_is_empty(tmp_path):
    assert known_codes(tmp_path / "nope.db") == set()


def test_known_codes_missing_table_is_empty(tmp_path):
    db = tmp_path / "experiments.db"
    sqlite3.connect(str(db)).close()  # empty db, no experiment_codes table
    assert known_codes(db) == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/generators/test_notebooks.py -k known_codes -v`
Expected: FAIL with `ImportError: cannot import name 'known_codes'`.

- [ ] **Step 3: Write minimal implementation**

Add to `eln/generators/notebooks.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/generators/test_notebooks.py -k known_codes -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add eln/generators/notebooks.py tests/generators/test_notebooks.py
git commit -m "feat(notebooks): known-codes lookup for matched/flagged status"
```

---

### Task 4: Provenance panel — artifacts produced by a notebook

**Files:**
- Modify: `eln/generators/notebooks.py`
- Test: `tests/generators/test_notebooks.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/generators/test_notebooks.py
from eln.generators.notebooks import notebook_artifacts


def test_notebook_artifacts_none_without_sdgl(tmp_path):
    assert notebook_artifacts(tmp_path, "notebooks/SORVI-01.ipynb") == []


def test_notebook_artifacts_lists_generates_edges(tmp_path):
    from eln.hashing import sha256_file
    from eln.sdgl import SDGL

    # An artifact on disk whose stored hash matches -> status "ok".
    art_dir = tmp_path / "data" / "SORVI-01" / "analysis"
    art_dir.mkdir(parents=True)
    art = art_dir / "plot.png"
    art.write_bytes(b"PNGDATA")
    rel = "data/SORVI-01/analysis/plot.png"
    content_hash = sha256_file(art)

    sdgl = SDGL(tmp_path)
    sdgl.initialize()
    conn = sdgl.connect()
    sdgl.upsert_node("experiment:SORVI-01", "experiment", conn=conn)
    sdgl.upsert_node(
        "dataset:" + rel, "dataset",
        metadata={"rel_path": rel, "content_hash": content_hash, "kind": "derived"},
        conn=conn,
    )
    sdgl.upsert_edge(
        "experiment:SORVI-01", "dataset:" + rel, "generates",
        {"notebook": {"path": "notebooks/SORVI-01.ipynb"}}, conn=conn,
    )
    conn.commit()
    conn.close()

    arts = notebook_artifacts(tmp_path, "notebooks/SORVI-01.ipynb")
    assert arts == [{"path": rel, "status": "ok"}]
    # A different notebook path matches nothing.
    assert notebook_artifacts(tmp_path, "notebooks/OTHER-01.ipynb") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/generators/test_notebooks.py -k artifacts -v`
Expected: FAIL with `ImportError: cannot import name 'notebook_artifacts'`.

- [ ] **Step 3: Write minimal implementation**

Add to `eln/generators/notebooks.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/generators/test_notebooks.py -k artifacts -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add eln/generators/notebooks.py tests/generators/test_notebooks.py
git commit -m "feat(notebooks): provenance panel reads generates-edges from sdgl.db"
```

---

### Task 5: Assemble `generate_notebooks` → `notebooks.html`

**Files:**
- Modify: `eln/generators/notebooks.py`
- Test: `tests/generators/test_notebooks.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/generators/test_notebooks.py
import json as _json
from eln.generators.notebooks import generate_notebooks


def _write_nb(path, cells):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(
        {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}))


def test_generate_empty_dir_placeholder(tmp_path):
    (tmp_path / "experiments.db").touch()
    out = generate_notebooks(tmp_path)
    assert out == tmp_path / "catalog" / "notebooks.html"
    text = out.read_text()
    assert "No notebooks yet" in text
    assert 'href="protocols.html"' in text  # nav present


def test_generate_renders_matched_and_flags_unmatched(tmp_path):
    _make_db_with_codes(tmp_path / "experiments.db", ["SORVI"])
    _write_nb(tmp_path / "notebooks" / "SORVI-01.ipynb",
              [{"cell_type": "code", "source": ["x = 1\n"], "outputs": []}])
    _write_nb(tmp_path / "notebooks" / "scratch.ipynb",
              [{"cell_type": "markdown", "source": ["notes"]}])
    text = generate_notebooks(tmp_path).read_text()
    assert "SORVI-01" in text
    assert "x = 1" in text
    assert "scratch" in text
    assert "unmatched" in text.lower()


def test_generate_warns_on_outputs(tmp_path):
    _make_db_with_codes(tmp_path / "experiments.db", ["SORVI"])
    _write_nb(tmp_path / "notebooks" / "SORVI-01.ipynb",
              [{"cell_type": "code", "source": ["print(1)\n"],
                "outputs": [{"output_type": "stream", "name": "stdout", "text": ["1\n"]}]}])
    text = generate_notebooks(tmp_path).read_text()
    assert "outputs" in text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/generators/test_notebooks.py -k generate -v`
Expected: FAIL with `ImportError: cannot import name 'generate_notebooks'`.

- [ ] **Step 3: Write minimal implementation**

Add to `eln/generators/notebooks.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/generators/test_notebooks.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add eln/generators/notebooks.py tests/generators/test_notebooks.py
git commit -m "feat(notebooks): assemble notebooks.html generator"
```

---

### Task 6: Wire into nav, generate_all, and the server

**Files:**
- Modify: `eln/generators/nav.py:12-17`
- Modify: `eln/generators/__init__.py`
- Modify: `eln/server/app.py:55-60`
- Modify: `eln/share.py:62-63` (`_CATALOG_PAGES` — the single-item-export sibling set)
- Test: `tests/generators/test_notebooks.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/generators/test_notebooks.py
def test_nav_includes_notebooks_after_protocols():
    from eln.generators.nav import CORE_NAV
    labels = [link.label for link in CORE_NAV]
    assert "Notebooks" in labels
    assert labels.index("Notebooks") == labels.index("Protocols") + 1


def test_generate_all_writes_notebooks(tmp_path):
    (tmp_path / "experiments.db").touch()
    from eln.generators import generate_all
    written = generate_all(tmp_path)
    assert "notebooks" in written
    assert written["notebooks"].name == "notebooks.html"
    assert written["notebooks"].exists()


def test_server_serves_notebooks_page():
    from eln.server.app import CORE_GENERATED_PAGES
    assert "notebooks.html" in CORE_GENERATED_PAGES


def test_export_catalog_pages_include_notebooks():
    from eln.share import _CATALOG_PAGES
    assert "notebooks.html" in _CATALOG_PAGES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/generators/test_notebooks.py -k "nav or generate_all or server or export_catalog" -v`
Expected: FAIL — `Notebooks` not in nav / `notebooks` not in `generate_all` result / `notebooks.html` not in `CORE_GENERATED_PAGES` / not in `_CATALOG_PAGES`.

- [ ] **Step 3: Write minimal implementation**

In `eln/generators/nav.py`, update `CORE_NAV`:

```python
CORE_NAV = [
    NavLink("Data Graph", "/"),
    NavLink("Experiments", "experiments.html"),
    NavLink("Protocols", "protocols.html"),
    NavLink("Notebooks", "notebooks.html"),
    NavLink("Reports", "reports.html"),
]
```

In `eln/generators/__init__.py`, add the import (alphabetical with the others), the `__all__` entry, and the `generate_all` line:

```python
from eln.generators.notebooks import generate_notebooks
```

```python
    "generate_notebooks",
```

```python
        "protocols": generate_protocol_catalog(root, catalog_out, plugins=plugins),
        "notebooks": generate_notebooks(root, catalog_out, plugins=plugins),
        "reports": generate_reports(root, catalog_out, plugins=plugins),
```

In `eln/server/app.py`, add to `CORE_GENERATED_PAGES`:

```python
CORE_GENERATED_PAGES = {
    "experiments.html",
    "protocols.html",
    "notebooks.html",
    "reports.html",
    "index.html",
}
```

In `eln/share.py`, add `"notebooks.html"` to `_CATALOG_PAGES`:

```python
_CATALOG_PAGES = {"index.html", "experiments.html", "protocols.html",
                  "notebooks.html", "reports.html", "presentations.html",
                  "admin.html", "sdgl.html"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/generators/test_notebooks.py -v && pytest tests/test_share.py -q`
Expected: PASS for the new tests, and `tests/test_share.py` still green (export flow already generates `notebooks.html` via `generate_all`, so the new nav link resolves and is not reported missing).

- [ ] **Step 5: Commit**

```bash
git add eln/generators/nav.py eln/generators/__init__.py eln/server/app.py eln/share.py tests/generators/test_notebooks.py
git commit -m "feat(notebooks): wire notebooks into nav, generate_all, server, export"
```

---

### Task 7: Sample notebook

**Files:**
- Create: `sample_data/notebooks/SORVI-01.ipynb`

- [ ] **Step 1: Create the sample notebook**

Write `sample_data/notebooks/SORVI-01.ipynb` (text + code, no outputs):

```json
{
 "cells": [
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": ["# SORVI-01 — analysis\n", "\n", "Thin wrapper: all computation comes from the analysis library.\n"]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": ["from eln.analysis import stamp  # illustrative\n", "# result = my_library.run(raw_inputs)\n", "# stamp(result, function=my_library.run, notebook='notebooks/SORVI-01.ipynb')\n"]
  }
 ],
 "metadata": {},
 "nbformat": 4,
 "nbformat_minor": 5
}
```

- [ ] **Step 2: Verify it renders**

Run: `python -m eln.generators.notebooks sample_data --catalog-out /tmp/nb_sample`
Expected: prints `Notebook catalog generated at: /tmp/nb_sample/notebooks.html`. Open/grep it: `grep -c "SORVI-01" /tmp/nb_sample/notebooks.html` returns ≥ 1. (The sample `experiments.db` is an empty placeholder, so the entry will carry an `UNMATCHED` badge — that is expected until the sample DB has codes.)

- [ ] **Step 3: Commit**

```bash
git add sample_data/notebooks/SORVI-01.ipynb
git commit -m "feat(notebooks): add sample notebook for out-of-the-box render"
```

---

### Task 8: Full suite, docs cleanup, push

**Files:**
- Delete (from working tree): `docs/superpowers/specs/2026-06-20-notebooks-design.md`, `docs/superpowers/plans/2026-06-20-notebooks.md`

- [ ] **Step 1: Run the full test suite**

Run: `pytest -q`
Expected: all tests pass (existing suite + the new `tests/generators/test_notebooks.py`).

- [ ] **Step 2: Confirm imports + generation end-to-end**

Run: `python -c "import eln.generators.notebooks, eln.server.app; from eln.generators import generate_all; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Remove the dev docs from the working tree (kept in git history)**

```bash
git rm docs/superpowers/specs/2026-06-20-notebooks-design.md docs/superpowers/plans/2026-06-20-notebooks.md
rmdir docs/superpowers/specs docs/superpowers/plans docs/superpowers docs 2>/dev/null || true
```

- [ ] **Step 4: Commit and push**

```bash
git add -A
git commit -m "chore(notebooks): remove design+plan dev docs from working tree (kept in history)"
git push origin main
```

---

## Self-review

**Spec coverage:**
- Storage/identity `ROOT/notebooks/<ID>.ipynb`, filename = link, no schema change → Tasks 1, 5, 7. ✓
- Render `.ipynb` JSON (md + code), no `nbconvert`, outputs ignored → Task 2. ✓
- No-output warning → Task 2 (count) + Task 5 (`nb-warning`). ✓
- Matched vs. unmatched flagging → Tasks 3, 5. ✓
- Series/session grouping & ordering → Task 5 (`_sort_key`, badges). ✓
- Empty-dir placeholder → Task 5. ✓
- Provenance panel (generates-edges by `notebook.path`, verify status, graceful degrade) → Task 4, surfaced in Task 5 (`_artifacts_html`). ✓
- Nav after Protocols; `generate_all`; `CORE_GENERATED_PAGES`; `_CATALOG_PAGES` (static export) → Task 6. ✓
- Static-export integration: `export_all` already calls `generate_all`, so `notebooks.html` is produced in bundles; `_CATALOG_PAGES` updated so single-item exports treat it as a known sibling → Task 6. ✓
- Sample notebook → Task 7. ✓
- Tests → every task. ✓
- Remove spec+plan from working tree (kept in history) → Task 8. ✓
- Invariants: no schema change (no DB-migration task touches `schema.sql`); notebook files only ever read (`read_text`), never written. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The sample notebook's `from eln.analysis import stamp` line is illustrative content inside a sample data file, not a plan placeholder.

**Type consistency:** Helper names and signatures are stable across tasks — `classify_notebook(stem)→dict(kind,code,id[,rep,excluded])`, `render_cells(nb)→(html,int)`, `known_codes(db_path)→set`, `notebook_artifacts(root,notebook_rel)→[{path,status}]`, `generate_notebooks(root,catalog_out,plugins)→Path`. Entry dict keys (`id,kind,code,rep,excluded,matched,cells_html,outputs,artifacts`) are produced in Task 5 and consumed by `_badges`/`_entry_html`/`_artifacts_html`/`_sort_key` consistently.
