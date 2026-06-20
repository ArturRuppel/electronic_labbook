# `eln.generators` — static page generators

Ported from the original `scripts/generate_*.py`.

Every generator reads from a data-repo *root* (holding `experiments.db`, the
optional `sdgl.db` build artifact, `reports/` and `presentations/`) and writes a
static HTML page into `root/catalog` (or an explicit `catalog_out`):

- `catalog.py` → `experiments.html`. Experiment start dates are derived from the
  earliest raw-file mtime via SDGL (`get_experiment_date_from_files`), never read
  from the DB; the SDGL connection is optional (dates render as `-` without it).
- `reports.py` → `reports.html`, rendering each markdown report. **Plan F**: a
  report declaring `**Series:** CODE` and a `{{experiments}}` token gets the token
  replaced with a DB-generated overview — a series header, a table of active
  repetitions (excluded ones omitted) with derived dates, and the deduplicated
  protocols used. An unknown series renders an inline error rather than crashing.
- `protocols.py` → `protocols.html`, grouped by name with version history.
- `presentations.py` → `presentations.html`, scanning `presentations/`.
- `home.py` → `index.html` from the static `catalog/home_template.html` asset
  (a code-repo input), filling in the experiment/protocol/report/presentation counts.

## Usage

```bash
labbook regenerate          # run all five (DB -> catalog HTML)
```

Or from Python: `from eln.generators import generate_all; generate_all(root)`.

## Regression guard: byte-identical regeneration

Regenerating over unchanged inputs produces identical bytes — footers are static
and the home page's "Last updated" is date-only (no `HH:MM:SS` churn). The
vestigial `generation_date` kwarg from the original scripts was dropped so this is
structural, not incidental. Covered by `tests/generators/test_generate.py`.
