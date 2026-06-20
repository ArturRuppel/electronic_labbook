# Notebooks — design

_2026-06-20_

## Purpose

Add **notebooks** as a first-class element of the lab notebook: the thin,
git-tracked code wrappers that turn immutable raw data into derived data. A
notebook is the *recipe* that links raw → derived, and it gets the same identity
as the experiment it analyzes. This spec covers the scaffolding to surface
notebooks in the catalog, on par with protocols and reports.

## Requirements (from the user)

1. A notebook **gets the same ID as an experiment** — `CODE-NN` for a session,
   bare `CODE` for the series aggregate. At most one notebook per ID.
2. Notebooks are **listed in the same place as protocols** — a core nav entry and
   a generated catalog page in the same visual family.
3. Notebooks are **thin wrappers only**: all real computation comes from public
   libraries or the private analysis library in the data repo.
4. Notebooks are **`.ipynb`** containing **text (markdown) and code only — no plot
   outputs**. Plots are produced as *derived* artifacts (stored locally,
   untracked); the exception is plots made for a progress report, which live in
   `reports/` and are tracked there.
5. Notebooks **live in the data repo**.

## Model

### Storage and identity

- Notebooks live at `ROOT/notebooks/<ID>.ipynb`.
- `<ID>` is the filename stem, parsed with the existing SDGL grammar:
  - `parse_id_folder` recognizes `CODE-NN` / `CODE-XNN` (session, incl. excluded).
  - `parse_code_folder` recognizes a bare five-character `CODE` (series aggregate).
- **The filename is the link.** No junction table and **no schema change** — the
  feature is purely file-driven, like reports' markdown. The ID maps a notebook to
  its experiment row (via `experiment_codes` / `experiments`).

### Rendering

- Notebooks are parsed as **`.ipynb` JSON with the stdlib `json` module — no
  `nbconvert` dependency.** Iterate `nb["cells"]`:
  - `markdown` cells → rendered with the existing `markdown_to_html` helper.
  - `code` cells → rendered as `<pre>` source (syntax highlighting is a possible
    later upgrade via Pygments).
  - **Cell outputs are ignored entirely**, consistent with the no-plots rule.
- **No-output enforcement (lightweight):** if any code cell carries outputs
  (`cell["outputs"]`), the notebook is rendered but shows a small warning
  ("outputs present — notebooks should be committed without outputs"), with a
  count. This nudges the user to strip outputs; it does not modify the file.
- Notebook files are **read-only** to this feature — never written to, in keeping
  with the provenance principle that recipes/relationships live in git and SDGL,
  never as file metadata.

### Grouping and unmatched files

- The page groups session notebooks under their series `CODE`, with the series
  aggregate notebook (bare `CODE`) shown at the series level. Visual treatment
  reuses the protocols page's collapsible-card pattern.
- A filename that does not parse to a known experiment ID is still listed but
  **flagged as unmatched** (catches typos). An empty `notebooks/` directory yields
  a "No notebooks yet." placeholder.

## Components

### 1. Generator — `eln/generators/notebooks.py`

`generate_notebooks(root, catalog_out=None, plugins=None)`:

1. Resolve `notebooks_dir = root / "notebooks"`, `database_path = root /
   "experiments.db"`, output `catalog_dir / "notebooks.html"`.
2. Scan `notebooks_dir` for `*.ipynb`. For each: parse the stem to an ID, classify
   as session / series / unmatched, parse the JSON, render cells.
3. Build the provenance panel per notebook (see component 3).
4. Render the page with `render_nav(plugins)` and write `notebooks.html`.
5. Follow the conventions of the other generators: byte-identical output for
   unchanged inputs (no timestamp churn), `print` the output path, return it.

The module mirrors `protocols.py` in structure (module-level HTML template,
`markdown_to_html`, a `main()` CLI entry) so it reads like its neighbors. The
`markdown_to_html` helper is shared rather than duplicated (extract the existing
implementation to a small shared location or import it from one generator —
implementation detail for the plan).

### 2. Navigation — `eln/generators/nav.py`

Add `NavLink("Notebooks", "notebooks.html")` to `CORE_NAV`, positioned **after
Protocols** (method → analysis code → writeup):

```
Data Graph · Experiments · Protocols · Notebooks · Reports
```

### 3. Provenance panel (folded in)

For each notebook at `notebooks/<ID>.ipynb`, list the artifacts it produced:

- Open `sdgl.db` (optional build artifact). Query:
  `SELECT source_id, target_id, metadata FROM edges WHERE relation_type =
  'generates'` and keep edges whose `json_extract(metadata, '$.notebook.path')`
  equals `notebooks/<ID>.ipynb`. Each `target_id` is a `dataset:<rel_path>` node —
  an artifact the notebook stamped.
- Cross-reference `verify_provenance(root)` (returns `[{node_id, path, status}]`
  with `status` in `modified`/`missing`) to tag each artifact `ok` (default),
  `modified`, or `missing`.
- Render a small "Artifacts produced" list per notebook: artifact path + status
  badge.
- **Graceful degrade:** if `sdgl.db` is absent, has no `edges` table, or yields no
  matching edges, the panel is omitted. The page renders fully without SDGL.

This reads the graph that `stamp(notebook="notebooks/<ID>.ipynb", …)` already
writes; it never writes anything itself.

### 4. Server — `eln/server/app.py`

Add `"notebooks.html"` to `CORE_GENERATED_PAGES` so it is served from the data
root's `catalog/` with the edit-overlay injected, exactly like the other core
pages. The existing `/<page>.html` route then covers it; no new route needed.

### 5. Wiring — `eln/generators/__init__.py`

Add `generate_notebooks` to the imports, `__all__`, and `generate_all`:

```python
"notebooks": generate_notebooks(root, catalog_out, plugins=plugins),
```

### 6. Sample data

Add `sample_data/.../notebooks/SORVI-01.ipynb` (and optionally a series
`SORVI.ipynb`) — a minimal notebook with one markdown cell and one code cell, **no
outputs** — so the page renders out of the box and demonstrates the convention.
(Aligns with `sample_data` using the canonical `CODE-NN` grammar.)

## Testing — `tests/generators/test_notebooks.py`

- ID parsing from filename: `SORVI-01.ipynb` → session, `SORVI.ipynb` → series,
  `SORVI-X02.ipynb` → excluded session, garbage stem → unmatched/flagged.
- Cell rendering: markdown cell becomes HTML; code cell becomes `<pre>` source.
- Outputs ignored: a cell with `outputs` does not render the output, and the
  warning/count appears.
- Empty `notebooks/` → "No notebooks yet." placeholder.
- Provenance panel: with a seeded `sdgl.db` containing a `generates` edge whose
  `metadata.notebook.path` matches, the artifact is listed with the right status;
  with no `sdgl.db`, the page still renders and the panel is omitted.

## Out of scope (this pass)

- Cross-links from experiment rows/cards to their notebook and back (separate
  follow-up).
- Syntax highlighting of code cells (Pygments) — easy later upgrade.
- A `labbook` CLI subcommand for notebooks; the catalog page and `generate_all`
  are enough for now.
- Authoring/creating notebooks from the UI — notebooks are authored in the data
  repo with normal tools.
- Enforcing output-stripping by modifying files (we only warn).

## Non-goals / invariants

- No `experiments.db` schema change.
- Notebook files are never modified by this feature.
- Provenance stays a graph relationship in SDGL; nothing executable or
  metadata-bearing is written into notebook or artifact files.
