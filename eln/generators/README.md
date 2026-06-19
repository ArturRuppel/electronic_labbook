# `eln.generators` — static page generators

**Roadmap step 5** (includes Plan F).

Lands here (ported from the original `scripts/generate_*.py`):

- `generate_catalog.py` — experiments page (reads `experiment_metadata.start_date`).
- `generate_reports.py` — reports page **with the DB-generated report overview
  built in from the start** (Plan F: `**Series:** CODE` + `{{experiments}}` →
  injected series header, active-rep experiment table with derived dates,
  deduplicated linked protocols).
- `generate_home.py`, protocol catalog generator.

**Regression guards:** no timestamp churn (static footers, date-only "Last
updated"; regenerating twice is byte-identical). See `docs/ROADMAP.md` and
`plans/plan-F-report-db-overview.md` (ported in step 5).
