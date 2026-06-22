# Reports as markdown **or** notebook — design

**Date:** 2026-06-22
**Status:** approved (design), pending implementation plan
**Repo:** `electronic_labbook` (the public code repo; generators live in `eln/generators/`)

## Motivation

A report should do three things for the person it is shared with:

1. **Be reproducible, with input and output tightly linked** — the report carries the
   actual analysis recipe, and every figure/number in it is traceable to the exact
   inputs and code that produced it.
2. **Interpret the results in prose** — narrative written by the author around the
   figures.
3. **Show no code** — a colleague opening the shared report sees prose + figures, never
   a code cell. Code clutter must not overwhelm the reader.

Today these pull in two directions handled by two parallel subsystems:

- `reports.py` renders `reports/**/*.md` → `reports.html`. Good at prose; links to a
  series via `**Series:** CODE` and can embed a DB overview at a `{{experiments}}`
  token. But a `.md` report is disconnected from the code that made its figures.
- `notebooks.py` renders `notebooks/*.ipynb` → `notebooks.html`. Carries the recipe
  and an "artifacts produced" list from SDGL `generates` stamps, but renders **code as
  `<pre>`** — the opposite of requirement 3 — and lives in a separate place/tab.

The COV2D NLS-subpopulation work produced **both** a `.md` report (prose + figures) and
a `.ipynb` (the recipe that made those figures) — the redundancy this design removes.

## Decisions (locked during brainstorming)

- **Unify into one "Reports" concept.** A report is a single document whose source is
  either `.md` (pure prose) or `.ipynb` (recipe + prose). The separate Notebooks page
  and nav tab are retired.
- **Linking is uniform.** Both formats declare their series with a `**Series:** CODE`
  line (in the markdown, or in a markdown cell). Parsing standardizes on the canonical
  SDGL code parser so alphanumeric codes like `COV2D` work (the current `[A-Z]{5}`
  regex does not match `COV2D` — a live bug).
- **Execution is decoupled from rendering.** Notebooks may involve **heavy computation
  against raw data**, so the render step **never executes anything**. The author runs a
  notebook deliberately, on demand, when code or inputs change.
- **Outputs are persisted, not recomputed.** A run writes small figures into the report
  folder (committed to git) and any heavy *intermediate* derived data to the filesystem
  (`stamp(kind="derived")`, keyed by experiment-relative path, resolved via the scan
  index). "Disposable derived data" means *the recipe can regenerate it*, not *the site
  regenerates it on every view*.
- **Rendering hides all code.** The notebook renderer emits **markdown cells only**;
  every code cell and every cell output is dropped. The code still lives in the
  committed `.ipynb` (that is the recipe); it is simply never shown.
- **Reproducibility is surfaced, and staleness is flagged.** Each report card gets a
  "how this was made" footer from its `generates` stamps (notebook @ commit, inputs),
  and a **staleness badge** when an input has changed since the figures were last
  produced.

## Approach

**Extend the existing reports generator** (chosen over a new document abstraction or an
external nbconvert/Quarto renderer — both heavier and, in Quarto's case, tempting
build-time execution we have ruled out). One render path, following current patterns.

### A. Report = a document under `reports/`

- Discovery globs `reports/**/*.md` **and** `reports/**/*.ipynb` (skip `README.md`).
  One report per folder, e.g.
  `reports/2026-06-21_COV2D-NLS-subpopulation/report.ipynb`.
- The `notebooks/` folder and `notebooks.html` page are retired; the `code/` vendored
  library (importable analysis code) stays as-is.

### B. Rendering hides all code

- New `render_report_cells(nb)` (replacing `notebooks.py`'s `render_cells`):
  - **markdown cell** → `markdown_to_html(source)` (same converter as `.md` reports).
  - **code cell** → dropped entirely (no `<pre>`).
  - **outputs** → ignored (and never expected; notebooks are committed without them).
- For a `.md` report the body is the file text; for an `.ipynb` it is the concatenation
  of its markdown cells. From that point the two paths are identical:
  `**Series:**` / `{{experiments}}` parsing, `**Date:**` extraction, and relative-image
  rewriting (relative to the report's folder) all run on the combined markdown.
- Figures appear because markdown cells embed the saved figure files
  (`![caption](figures/analysis/label_clustering.png)`) — the same mechanism `.md`
  reports already use, and the embedded files are the stamped output artifacts.

### C. Execution is explicit; outputs are persisted + stamped

- Out of scope for the generator: it never runs a kernel. Authoring workflow (documented,
  not enforced by the generator):
  1. Author the `.ipynb`: markdown cells (prose + figure embeds) interleaved with code
     cells (the recipe). Declare `**Series:** CODE` in the first markdown cell.
  2. Run it deliberately (may be heavy / against raw data). It writes figures into the
     report folder and any heavy intermediate derived data to the filesystem.
  3. `stamp()` each figure with `function`, `params`, `inputs`, and
     `notebook="reports/<folder>/<file>.ipynb"`, `produced_by="experiment:CODE"`.
  4. Commit, then (per the existing "commit, then stamp" rule) the recorded hash is the
     committed state.

### D. Reproducibility footer + staleness flag

- **Footer.** Generalize `notebooks.py`'s `artifacts_by_notebook` so it keys by the
  stamp's recorded `notebook.path` (now a `reports/...` path). For each report the
  generator looks up its `generates` edges and renders a compact "how this was made"
  block: the producing notebook @ commit and the artifacts produced, each with status.
- **Staleness — new `stale_outputs(root)` in `eln/analysis/provenance.py`**, a sibling
  to `verify_provenance`. For every stamped `dataset` node it reads the `generates`
  edge's recorded `inputs` map (`{input_rel: sha256}`) and recomputes each input's
  current hash — in-repo via `sha256_file`, external via the existing `_external_hash`
  scan-index resolver. If any current input hash differs from the recorded one, the
  output is **stale** (made from older inputs). Returns
  `[{"node_id", "path", "status": "stale", "changed_inputs": [...]}]`.
- **Badge.** The report card shows:
  - `⚠ figures stale — re-run the notebook` when any of its outputs are stale, listing
    which inputs changed;
  - `modified` / `missing` for outputs whose own content drifted or vanished (from
    `verify_provenance`);
  - nothing when everything verifies (clean).
  Both checks run **once per page build** over the whole graph (as `artifacts_by_notebook`
  already does), then are indexed per report.

### E. Cleanup carried with the change

- Replace the `[A-Z]{5}` `SERIES_RE` with the SDGL code parser in `reports.py`
  (`parse_code_folder`), fixing `{{experiments}}` for alphanumeric series.
- Remove the `Notebooks` nav entry (`eln/generators/nav.py`); delete the
  `notebooks.html` generation path; keep/move reusable helpers
  (`classify_notebook`, `artifacts_by_notebook`) to where reports consume them.
- Migrate the COV2D work: fold the existing `.md` report's prose into markdown cells of
  `reports/2026-06-21_COV2D-NLS-subpopulation/report.ipynb`, embed the figures, remove
  the now-redundant `.md`, move the notebook out of `notebooks/`, and re-`stamp()` at the
  new path. (The vendored `code/cellflow_analysis/` is unchanged.)

## Data flow

```
author runs report.ipynb  ──►  figures/*.png|svg  (git, in report folder)
   (explicit, may be heavy)     heavy intermediate derived data (filesystem)
            │                            │
            └────── stamp() ─────────────┴──►  SDGL generates edges
                                                (notebook@commit, inputs={hash})
                                                committed to provenance.json

site build (no kernel, no data, no compute):
  reports/**/*.{md,ipynb}
     ├─ .md   → text
     └─ .ipynb→ markdown cells only (code & outputs dropped)
                    │
            markdown_to_html + image rewrite + {{experiments}} + date
                    │
            + footer (artifacts_by_notebook)  + staleness (stale_outputs)
                    │
                 reports.html
```

## Testing

- `render_report_cells`: code cells produce no output in the HTML; markdown cells render;
  committed outputs (if any) are ignored.
- Series parsing: `**Series:** COV2D` resolves via the SDGL parser (regression for the
  `[A-Z]{5}` bug); unknown code renders the inline error; `{{experiments}}` injects.
- `stale_outputs`: synthetic stamp whose recorded input hash differs from the current
  file → reported stale with the changed input; matching hashes → not stale; missing
  input handled.
- Reports page: an `.ipynb` under `reports/` appears as a card with code hidden, figures
  embedded, and the footer/badge; `notebooks.html` is no longer generated and the nav has
  no Notebooks entry.
- Image-path rewriting works for figures embedded from a notebook's markdown cell.

## Edge cases

- `.ipynb` with no markdown cells → empty body (card still lists artifacts/footer).
- `.ipynb` committed with outputs → outputs ignored (forward-compatible; no break).
- `sdgl.db` absent → no footer/staleness (page renders fully), matching current guards.
- A report with both a `.md` and an `.ipynb` in one folder → both render as separate
  cards; the COV2D migration removes the `.md` so there is exactly one.
- Stale + missing simultaneously → show the stronger signal (`missing`) plus stale list.

## Out of scope

- Build-time execution of notebooks (ruled out by the heavy-compute / raw-data and
  CI-has-no-data constraints).
- External renderers (nbconvert/Quarto).
- A collapsible "show code" toggle — code is *completely* hidden, not folded.
- Auto-embedding a code cell's figure from its output (figures are saved files embedded
  from markdown cells).
- Re-architecting provenance; we only add `stale_outputs` alongside `verify_provenance`.
