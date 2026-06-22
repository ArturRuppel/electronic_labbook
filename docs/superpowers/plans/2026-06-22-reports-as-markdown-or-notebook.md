# Reports as markdown **or** notebook — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a report under `reports/` be either a `.md` file or a `.ipynb` notebook, rendered as prose + figures with **all code hidden**, plus a provenance footer that flags when a report's figures are **stale** relative to their inputs — and retire the separate Notebooks page.

**Architecture:** Extend the existing `eln/generators/reports.py` generator. A notebook report contributes only the concatenated source of its **markdown cells** (code cells and outputs are dropped); that markdown then flows through the *exact same* existing pipeline as a `.md` report (`**Series:**`/`{{experiments}}`/`**Date:**`/relative-image rewriting). Provenance comes from SDGL `generates` stamps; a new `stale_outputs()` (sibling to `verify_provenance()`) detects input drift. The Notebooks generator/page/nav are removed; its two still-needed helpers move into `reports.py`.

**Tech Stack:** Python 3.13, stdlib `sqlite3`/`json`, pytest. No new dependencies. SDGL graph (`eln/sdgl`), provenance (`eln/analysis/provenance.py`).

**Spec:** `docs/superpowers/specs/2026-06-22-reports-as-markdown-or-notebook-design.md`

**Repos:** Tasks 1–6 are in `electronic_labbook` (code). Task 7 is an operational migration in `electronic_labbook_database` (private data repo).

---

## File Structure

- `eln/generators/reports.py` — **modified**: SDGL-based series parsing; new `notebook_markdown()`, `_report_source()`, `report_provenance()`; `.ipynb` discovery; footer rendering.
- `eln/analysis/provenance.py` — **modified**: new `stale_outputs()`.
- `eln/generators/notebooks.py` — **deleted** (helpers moved to `reports.py`).
- `eln/generators/nav.py` — **modified**: drop the Notebooks link.
- `eln/generators/__init__.py` — **modified**: drop `generate_notebooks`.
- `eln/share.py`, `eln/server/app.py` — **modified**: drop `notebooks.html`.
- `tests/generators/test_reports.py` — **created**: parsing, notebook rendering, footer.
- `tests/analysis/test_stale_outputs.py` — **created**: staleness detection.
- `tests/generators/test_notebooks.py` — **deleted**; `test_nav.py`, `test_generate.py` — **modified**.

Run the whole suite with: `pytest -q` (from the repo root, inside `.venv`).

---

## Task 1: Series parsing accepts alphanumeric codes (fix the `COV2D` bug)

**Files:**
- Modify: `eln/generators/reports.py` (the `SERIES_RE`/`parse_series` region near line 404, and the import near line 17)
- Test: `tests/generators/test_reports.py`

- [ ] **Step 1: Write the failing test**

Create `tests/generators/test_reports.py`:

```python
"""Reports generator: series parsing, notebook rendering, provenance footer."""

from eln.generators.reports import parse_series


def test_parse_series_alpha_code():
    assert parse_series("intro\n**Series:** SORVI\nmore") == "SORVI"


def test_parse_series_alphanumeric_code():
    # Regression: the old [A-Z]{5} regex did not match a code with a digit.
    assert parse_series("# COV2D\n**Series:** COV2D\n{{experiments}}") == "COV2D"


def test_parse_series_absent():
    assert parse_series("no series declared here") is None


def test_parse_series_rejects_non_code():
    # A five-char token that is not a valid code grammar is not a series.
    assert parse_series("**Series:** ab cd") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/generators/test_reports.py -q`
Expected: FAIL — `test_parse_series_alphanumeric_code` returns `None` (digit breaks `[A-Z]{5}`).

- [ ] **Step 3: Implement — parse via the canonical SDGL code parser**

In `eln/generators/reports.py`, extend the import (currently `from eln.sdgl import format_experiment_id`):

```python
from eln.sdgl import format_experiment_id, parse_code_folder
```

Replace the `SERIES_RE` definition and `parse_series` body:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/generators/test_reports.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add eln/generators/reports.py tests/generators/test_reports.py
git commit -m "fix(reports): parse alphanumeric series codes via the SDGL parser"
```

---

## Task 2: Extract a notebook's markdown (code cells hidden)

**Files:**
- Modify: `eln/generators/reports.py` (add `notebook_markdown` near the other helpers)
- Test: `tests/generators/test_reports.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/generators/test_reports.py`:

```python
from eln.generators.reports import notebook_markdown


def _nb(cells):
    return {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}


def test_notebook_markdown_keeps_markdown_drops_code():
    nb = _nb([
        {"cell_type": "markdown", "source": ["# Title\n", "\n", "**prose**\n"]},
        {"cell_type": "code", "source": ["import numpy as np\n"], "outputs": []},
        {"cell_type": "markdown", "source": ["After the code.\n"]},
    ])
    md = notebook_markdown(nb)
    assert "# Title" in md
    assert "**prose**" in md
    assert "After the code." in md
    assert "import numpy" not in md  # code cell fully hidden


def test_notebook_markdown_ignores_outputs():
    nb = _nb([
        {"cell_type": "code", "source": ["print('hi')\n"],
         "outputs": [{"output_type": "stream", "name": "stdout", "text": ["hi\n"]}]},
    ])
    assert notebook_markdown(nb).strip() == ""


def test_notebook_markdown_source_as_string():
    nb = _nb([{"cell_type": "markdown", "source": "plain string\n"}])
    assert "plain string" in notebook_markdown(nb)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/generators/test_reports.py -q`
Expected: FAIL — `ImportError: cannot import name 'notebook_markdown'`.

- [ ] **Step 3: Implement**

In `eln/generators/reports.py`, add (place it just above `generate_reports`):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/generators/test_reports.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add eln/generators/reports.py tests/generators/test_reports.py
git commit -m "feat(reports): extract markdown-only source from notebooks (code hidden)"
```

---

## Task 3: Render `.ipynb` reports through the existing pipeline

**Files:**
- Modify: `eln/generators/reports.py` (`generate_reports`: discovery glob ~line 714, and content load ~line 739)
- Test: `tests/generators/test_reports.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/generators/test_reports.py`:

```python
import json as _json
import sqlite3


def _make_db_with_codes(path, codes):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE experiment_codes "
                 "(title TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE)")
    for i, code in enumerate(codes):
        conn.execute("INSERT INTO experiment_codes (title, code) VALUES (?, ?)",
                     (f"t{i}", code))
    conn.commit()
    conn.close()


def _write_nb(path, cells):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(
        {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}))


def test_generate_renders_notebook_report(tmp_path):
    from eln.generators.reports import generate_reports
    _make_db_with_codes(tmp_path / "experiments.db", ["COV2D"])
    _write_nb(tmp_path / "reports" / "cov2d" / "report.ipynb", [
        {"cell_type": "markdown",
         "source": ["# COV2D\n", "**Series:** COV2D\n", "\n",
                    "Interpretation prose.\n", "\n",
                    "![fig](figures/plot.png)\n"]},
        {"cell_type": "code", "source": ["secret = compute()\n"], "outputs": []},
    ])
    text = generate_reports(tmp_path).read_text()
    assert "Interpretation prose." in text          # markdown rendered
    assert "secret = compute()" not in text          # code hidden
    assert "reports/cov2d/figures/plot.png" in text  # image path rewritten to report dir
    assert "COV2D" in text                            # series-linked title
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/generators/test_reports.py::test_generate_renders_notebook_report -q`
Expected: FAIL — `.ipynb` files are not discovered (glob is `**/*.md`), so the prose is absent.

- [ ] **Step 3: Implement — discover `.ipynb` and load its markdown**

In `generate_reports`, change the discovery glob (currently globs only `**/*.md`):

```python
    # Reports are markdown or notebook files under reports/ (recursively).
    # README.md is the folder's own documentation, not a report — skip it.
    report_files = sorted(
        (p for p in reports_dir.glob("**/*")
         if p.suffix in (".md", ".ipynb") and p.name.lower() != "readme.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
```

Then change the per-report content load (currently `content = report_file.read_text()`):

```python
        for report_file in report_files:
            if report_file.suffix == ".ipynb":
                content = notebook_markdown(json.loads(report_file.read_text()))
            else:
                content = report_file.read_text()
```

Add `import json` to the imports at the top of `eln/generators/reports.py` (it currently imports `argparse`, `re`, `sqlite3`):

```python
import argparse
import json
import re
import sqlite3
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/generators/test_reports.py::test_generate_renders_notebook_report -q`
Expected: PASS.

- [ ] **Step 5: Run the whole reports test file**

Run: `pytest tests/generators/test_reports.py -q`
Expected: PASS (8 passed).

- [ ] **Step 6: Commit**

```bash
git add eln/generators/reports.py tests/generators/test_reports.py
git commit -m "feat(reports): render .ipynb reports (markdown + figures, code hidden)"
```

---

## Task 4: `stale_outputs()` — detect inputs that changed since a figure was produced

**Files:**
- Modify: `eln/analysis/provenance.py` (add `stale_outputs` after `verify_provenance`)
- Test: `tests/analysis/test_stale_outputs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/analysis/test_stale_outputs.py`:

```python
"""stale_outputs(): an output is stale when an input changed since it was stamped."""

from eln.hashing import sha256_file
from eln.sdgl import SDGL


def _stamp_output(root, *, out_rel, inputs):
    """Create a stamped dataset node + a generates edge recording input hashes."""
    sdgl = SDGL(root)
    sdgl.initialize()
    conn = sdgl.connect()
    out_abs = root / out_rel
    out_abs.parent.mkdir(parents=True, exist_ok=True)
    out_abs.write_bytes(b"FIGURE")
    record = {"kind": "derived", "rel_path": out_rel,
              "content_hash": sha256_file(out_abs), "inputs": inputs}
    sdgl.upsert_node("experiment:COV2D", "experiment", conn=conn)
    sdgl.upsert_node("dataset:" + out_rel, "dataset",
                     metadata={"rel_path": out_rel,
                               "content_hash": record["content_hash"],
                               "kind": "derived"}, conn=conn)
    sdgl.upsert_edge("experiment:COV2D", "dataset:" + out_rel, "generates",
                     record, conn=conn)
    conn.commit()
    conn.close()


def test_not_stale_when_inputs_match(tmp_path):
    from eln.analysis.provenance import stale_outputs
    inp = tmp_path / "reports" / "cov2d" / "in.csv"
    inp.parent.mkdir(parents=True, exist_ok=True)
    inp.write_bytes(b"DATA-V1")
    _stamp_output(tmp_path, out_rel="reports/cov2d/fig.png",
                  inputs={"reports/cov2d/in.csv": sha256_file(inp)})
    assert stale_outputs(tmp_path) == []


def test_stale_when_input_changed(tmp_path):
    from eln.analysis.provenance import stale_outputs
    inp = tmp_path / "reports" / "cov2d" / "in.csv"
    inp.parent.mkdir(parents=True, exist_ok=True)
    inp.write_bytes(b"DATA-V1")
    _stamp_output(tmp_path, out_rel="reports/cov2d/fig.png",
                  inputs={"reports/cov2d/in.csv": sha256_file(inp)})
    inp.write_bytes(b"DATA-V2")  # input changed after stamping
    result = stale_outputs(tmp_path)
    assert len(result) == 1
    assert result[0]["path"] == "reports/cov2d/fig.png"
    assert result[0]["status"] == "stale"
    assert result[0]["changed_inputs"] == ["reports/cov2d/in.csv"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/analysis/test_stale_outputs.py -q`
Expected: FAIL — `ImportError: cannot import name 'stale_outputs'`.

- [ ] **Step 3: Implement**

In `eln/analysis/provenance.py`, add after `verify_provenance`:

```python
def stale_outputs(root=None):
    """Stamped outputs whose inputs changed since the output was produced.

    Sibling to :func:`verify_provenance` (which checks the *output's* own hash).
    For each ``generates`` edge, re-hash every input recorded at stamp time — in
    the repo via ``sha256_file``, external (filesystem) via the scan index
    (:func:`_external_hash`) — and compare to the stored hash. Any mismatch means
    the figure was made from older inputs and the notebook should be re-run.

    Each entry is ``{"node_id", "path", "status": "stale", "changed_inputs": [...]}``.
    Outputs whose inputs all still match are omitted.
    """
    root = _resolve_root(root)
    sdgl = SDGL(root)
    conn = sdgl.connect()
    try:
        from eln.sdgl.engine import json_loads
        try:
            rows = conn.execute(
                "SELECT target_id, metadata FROM edges "
                "WHERE relation_type = 'generates'"
            ).fetchall()
        except sqlite3.OperationalError:
            return []  # sdgl.db has no edges table yet → nothing stamped
        stale = []
        for row in rows:
            meta = json_loads(row["metadata"]) or {}
            inputs = meta.get("inputs") or {}
            changed = []
            for input_rel, stored in inputs.items():
                in_repo = root / input_rel
                if in_repo.exists():
                    current = sha256_file(in_repo)
                else:
                    current = _external_hash(conn, input_rel)
                if current is not None and current != stored:
                    changed.append(input_rel)
            if changed:
                node = row["target_id"]
                path = node[len("dataset:"):] if node.startswith("dataset:") else node
                stale.append({"node_id": node, "path": path, "status": "stale",
                              "changed_inputs": sorted(changed)})
        return stale
    finally:
        conn.close()
```

Note: `verify_provenance` uses `conn` with a row factory; confirm `SDGL.connect()` returns rows supporting string-key access (it does — `notebooks.py` reads `row["metadata"]` off the same connection). If `row_factory` is unset on this path, add `conn.row_factory = sqlite3.Row` after `conn = sdgl.connect()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/analysis/test_stale_outputs.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add eln/analysis/provenance.py tests/analysis/test_stale_outputs.py
git commit -m "feat(provenance): stale_outputs() flags figures whose inputs changed"
```

---

## Task 5: Provenance footer + staleness badge on each report card

**Files:**
- Modify: `eln/generators/reports.py` (add `report_provenance`; render footer in `generate_reports`)
- Test: `tests/generators/test_reports.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/generators/test_reports.py`:

```python
def test_report_card_shows_stale_badge(tmp_path):
    from eln.generators.reports import generate_reports
    from eln.hashing import sha256_file
    from eln.sdgl import SDGL

    _make_db_with_codes(tmp_path / "experiments.db", ["COV2D"])
    nb_rel = "reports/cov2d/report.ipynb"
    _write_nb(tmp_path / nb_rel, [
        {"cell_type": "markdown",
         "source": ["# COV2D\n", "**Series:** COV2D\n", "![f](figures/fig.png)\n"]},
    ])
    # An input that will change, and a stamped output produced by this notebook.
    inp = tmp_path / "reports" / "cov2d" / "in.csv"
    inp.write_bytes(b"V1")
    out_rel = "reports/cov2d/figures/fig.png"
    out_abs = tmp_path / out_rel
    out_abs.parent.mkdir(parents=True, exist_ok=True)
    out_abs.write_bytes(b"FIG")

    sdgl = SDGL(tmp_path)
    sdgl.initialize()
    conn = sdgl.connect()
    sdgl.upsert_node("experiment:COV2D", "experiment", conn=conn)
    sdgl.upsert_node("dataset:" + out_rel, "dataset",
                     metadata={"rel_path": out_rel,
                               "content_hash": sha256_file(out_abs),
                               "kind": "derived"}, conn=conn)
    sdgl.upsert_edge("experiment:COV2D", "dataset:" + out_rel, "generates",
                     {"rel_path": out_rel, "content_hash": sha256_file(out_abs),
                      "inputs": {"reports/cov2d/in.csv": sha256_file(inp)},
                      "notebook": {"path": nb_rel}}, conn=conn)
    conn.commit()
    conn.close()

    inp.write_bytes(b"V2")  # input drifts after stamping
    text = generate_reports(tmp_path).read_text()
    assert "stale" in text.lower()
    assert out_rel in text  # the produced artifact is listed in the footer
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/generators/test_reports.py::test_report_card_shows_stale_badge -q`
Expected: FAIL — no footer/badge rendered.

- [ ] **Step 3: Implement — `report_provenance` helper + footer injection**

In `eln/generators/reports.py`, add this helper (above `generate_reports`):

```python
def report_provenance(root):
    """Map each report's path to its produced artifacts and their status, from the
    SDGL ``generates`` stamps. Keyed by the stamp's recorded ``notebook.path``
    (e.g. ``reports/cov2d/report.ipynb``); each value is a sorted list of
    ``{"path", "status"}`` with ``status`` in ``ok`` / ``stale`` / ``modified`` /
    ``missing``. Empty when ``sdgl.db`` is absent, so the page renders without it.

    One pass over the graph: a single ``generates`` query plus one
    ``verify_provenance`` and one ``stale_outputs`` for the whole repo."""
    root = Path(root)
    sdgl_db = root / DEFAULT_SDGL_DB_NAME
    if not sdgl_db.exists():
        return {}

    from eln.analysis.provenance import stale_outputs, verify_provenance
    from eln.sdgl.engine import json_loads

    conn = sqlite3.connect(str(sdgl_db))
    conn.row_factory = sqlite3.Row
    try:
        try:
            rows = conn.execute(
                "SELECT target_id, metadata FROM edges "
                "WHERE relation_type = 'generates'"
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
    finally:
        conn.close()

    drift = {d["node_id"]: d["status"] for d in verify_provenance(root)}
    stale = {d["node_id"]: d["status"] for d in stale_outputs(root)}
    by_report = {}
    for row in rows:
        meta = json_loads(row["metadata"]) or {}
        nb_path = (meta.get("notebook") or {}).get("path")
        if not nb_path:
            continue
        node = row["target_id"]
        path = node[len("dataset:"):] if node.startswith("dataset:") else node
        status = drift.get(node) or stale.get(node) or "ok"
        by_report.setdefault(nb_path, []).append({"path": path, "status": status})
    for items in by_report.values():
        items.sort(key=lambda a: a["path"])
    return by_report


def _provenance_footer(artifacts):
    """Footer HTML for a report card: a staleness banner (when any artifact is
    stale/modified/missing) and the list of produced artifacts. '' when none."""
    if not artifacts:
        return ""
    bad = [a for a in artifacts if a["status"] != "ok"]
    banner = ""
    if bad:
        kinds = sorted({a["status"] for a in bad})
        banner = (f'<div class="report-stale">&#9888; figures {", ".join(kinds)} '
                  "&mdash; re-run the notebook</div>")
    items = "".join(
        f'<li><span class="prov-status prov-{a["status"]}">[{a["status"]}]</span> '
        f'{a["path"]}</li>' for a in artifacts)
    return (f'<div class="report-provenance">{banner}'
            f'<h4>How this was made &middot; artifacts produced</h4>'
            f'<ul>{items}</ul></div>')
```

Then, in `generate_reports`, build the provenance map once (just before the `for report_file in report_files:` loop, alongside the DB connections):

```python
        provenance = report_provenance(root)
```

And inject the footer into each card. Find where `html_content` is assembled into the card (the `reports_html_list.append(...)` f-string) and add the footer after the report body. Compute it from the report's rel path just before the append:

```python
            rel_src = report_file.relative_to(root).as_posix()
            footer = _provenance_footer(provenance.get(rel_src, []))
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
                        {footer}
                    </div>
                </div>
            """)
```

Add minimal styles to `REPORTS_HTML_TEMPLATE`'s `<style>` block (anywhere among the existing rules):

```css
        .report-provenance {{ margin-top: 1rem; padding-top: 0.75rem;
                              border-top: 1px solid #e0e5e9; font-size: 0.85rem;
                              color: #53616d; }}
        .report-provenance h4 {{ font-size: 0.8rem; text-transform: uppercase;
                                 color: #6a7884; margin-bottom: 0.4rem; }}
        .report-provenance li {{ list-style: none; }}
        .report-stale {{ background: #fbeede; color: #8a5a1f;
                         border: 1px solid #eccf9c; border-radius: 6px;
                         padding: 0.4rem 0.7rem; margin-bottom: 0.6rem; }}
        .prov-status {{ font-family: monospace; }}
        .prov-ok {{ color: #27735f; }}
        .prov-stale {{ color: #8a5a1f; }}
        .prov-modified {{ color: #8a6d1f; }}
        .prov-missing {{ color: #8a3b3b; }}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/generators/test_reports.py::test_report_card_shows_stale_badge -q`
Expected: PASS.

- [ ] **Step 5: Run the whole reports test file**

Run: `pytest tests/generators/test_reports.py -q`
Expected: PASS (9 passed).

- [ ] **Step 6: Commit**

```bash
git add eln/generators/reports.py tests/generators/test_reports.py
git commit -m "feat(reports): provenance footer with staleness badge on report cards"
```

---

## Task 6: Retire the Notebooks page and its wiring

**Files:**
- Delete: `eln/generators/notebooks.py`, `tests/generators/test_notebooks.py`
- Modify: `eln/generators/nav.py`, `eln/generators/__init__.py`, `eln/share.py`, `eln/server/app.py`, `tests/generators/test_nav.py`, `tests/generators/test_generate.py`

- [ ] **Step 1: Update the nav test (drop Notebooks) — write the failing expectation**

In `tests/generators/test_nav.py`, remove the Notebooks line from `EXPECTED`:

```python
EXPECTED = (
    '<div class="nav">\n'
    '        <a href="/">Data Graph</a>\n'
    '        <a href="experiments.html">Experiments</a>\n'
    '        <a href="protocols.html">Protocols</a>\n'
    '        <a href="reports.html">Reports</a>\n'
    '        <a href="presentations.html">Presentations</a>\n'
    '    </div>'
)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/generators/test_nav.py -q`
Expected: FAIL — current nav still includes the Notebooks link.

- [ ] **Step 3: Remove the Notebooks link from `nav.py`**

In `eln/generators/nav.py`, delete the line `NavLink("Notebooks", "notebooks.html"),` from `CORE_NAV`.

- [ ] **Step 4: Run to verify nav passes**

Run: `pytest tests/generators/test_nav.py -q`
Expected: PASS.

- [ ] **Step 5: Drop the generator from `__init__.py`**

In `eln/generators/__init__.py`: remove `from eln.generators.notebooks import generate_notebooks`, remove `"generate_notebooks",` from `__all__`, and remove the `"notebooks": generate_notebooks(...)` line from the `written` dict in `generate_all`.

- [ ] **Step 6: Drop `notebooks.html` from share + server page sets**

In `eln/share.py`, remove `"notebooks.html",` from `_CATALOG_PAGES`.
In `eln/server/app.py`, remove `"notebooks.html",` from `CORE_GENERATED_PAGES`.

- [ ] **Step 7: Delete the notebooks generator and its tests**

```bash
git rm eln/generators/notebooks.py tests/generators/test_notebooks.py
```

- [ ] **Step 8: Fix the remaining page-set assertion**

In `tests/generators/test_generate.py` (~line 117), remove `"notebooks.html",` from the tuple of expected pages.

- [ ] **Step 9: Run the full suite**

Run: `pytest -q`
Expected: PASS — no references to `generate_notebooks`/`notebooks.html` remain. (If any import error surfaces, grep `git grep -n "notebooks"` and remove the stragglers.)

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "refactor(reports): retire the separate Notebooks page (reports own notebooks now)"
```

---

## Task 7: Migrate the COV2D report (data repo — operational)

**Repo:** `electronic_labbook_database` (private). Requires a kernel with the analysis deps (numpy/pandas/scipy/matplotlib/pyarrow/IPython) **and** `eln`, plus access to the COV2D data. This task moves the notebook into the report folder and makes it the single COV2D report.

- [ ] **Step 1: Move the notebook into the report folder**

```bash
cd /home/aruppel/Projects/electronic_labbook_database
git mv notebooks/COV2D.ipynb reports/2026-06-21_COV2D-NLS-subpopulation/report.ipynb
rmdir notebooks 2>/dev/null || true
```

- [ ] **Step 2: Fold the prose + figure embeds into markdown cells**

Edit `reports/2026-06-21_COV2D-NLS-subpopulation/report.ipynb` (use NotebookEdit). Ensure the first markdown cell still contains `**Series:** COV2D` and `**Date:** 2026-06-21`. After each analysis code cell, add a markdown cell that embeds the saved figure and interprets it, e.g.:

```markdown
![Homotypic clustering vs chance](figures/analysis/label_clustering.png)

Homotypic contacts are enriched 1.06×, p ≈ 0.008 ...
```

Move the narrative paragraphs from the old `.md` report into markdown cells so the notebook carries the full interpretation (the `.md` is removed in Step 4).

- [ ] **Step 3: Point the stamp cell at the new path**

In the final (stamp) code cell, change `notebook="notebooks/COV2D.ipynb"` to
`notebook="reports/2026-06-21_COV2D-NLS-subpopulation/report.ipynb"`.

- [ ] **Step 4: Remove the now-redundant markdown report**

```bash
git rm reports/2026-06-21_COV2D-NLS-subpopulation/2026-06-21_COV2D-NLS-subpopulation.md
```

- [ ] **Step 5: Commit, then run + stamp (commit-then-stamp)**

```bash
git add -A
git commit -m "reports: COV2D report becomes a notebook (prose + figures, code hidden)"
```

Then run the notebook end-to-end (refreshes figures and creates the `generates`
stamps at the new path). Confirm the stamps landed:

```bash
python -W ignore -c "from eln.analysis.provenance import stale_outputs, verify_provenance; \
print('stale:', stale_outputs('.')); print('drift:', verify_provenance('.'))"
```

Expected: immediately after a clean run, `stale: []` and `drift: []`.

- [ ] **Step 6: Regenerate and eyeball the page**

```bash
python -W ignore -m eln.generators.reports .   # (run from the data repo, eln on PATH)
```

Open `catalog/reports.html`: the COV2D card shows prose + figures, **no code**, and a
"How this was made" footer with all artifacts `[ok]`. Commit the provenance dump if the
run updated it (`git add provenance.json && git commit -m "chore: stamp COV2D report artifacts"`).

---

## Self-Review

**Spec coverage:**
- §A (report = .md or .ipynb under reports/) → Tasks 3, 7.
- §A (retire notebooks/ + page) → Task 6, Task 7 Step 1.
- §B (render hides all code; markdown pipeline reused) → Tasks 2, 3.
- §B (series via SDGL parser; `{{experiments}}`) → Task 1 (parser); `{{experiments}}` is unchanged existing code exercised by Task 3's markdown path.
- §C (execution explicit; outputs persisted + stamped) → Task 7 (authoring/operational); the generator never executes (Tasks 2–3 only read).
- §D (footer + staleness) → Tasks 4, 5.
- §E (fix `[A-Z]{5}`; remove nav/page; migrate COV2D) → Tasks 1, 6, 7.

**Placeholder scan:** No TBD/TODO; every code step shows the code; every test step shows the test and the run command with expected result.

**Type/name consistency:** `notebook_markdown(nb)` defined in Task 2, used in Task 3. `report_provenance(root)` and `_provenance_footer(artifacts)` defined and used in Task 5. `stale_outputs(root)` defined in Task 4, used in Task 5. Stamp metadata keys (`inputs`, `notebook.path`, `rel_path`, `content_hash`) match `eln/analysis/provenance.py`'s `stamp()` record shape and the existing `verify_provenance`/`_external_hash` usage. `parse_code_folder` returns `{"code": ...}` (verified) — used in Task 1.

**Note on `generate_reports` line numbers:** the file is ~840 lines; the anchors quoted (discovery glob, content load, card f-string, `SERIES_RE`) are unique strings — match on the string, not the line number.
