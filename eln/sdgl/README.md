# `eln.sdgl` — Scientific Data Graph Layer

**Roadmap step 4.** The scan engine and the project's differentiator.

Lands here (ported from the original `sdgl.py`):

- Scan of configured roots from `sdgl.toml`.
- The naming grammar (`AA00_raw`, `AA00_analysis_tfm`,
  `AA00+AB01_aggregate_analysis_…`).
- `nodes`, `edges`, `file_locations`, `scan_findings` graph tables.
- Materialized `experiment_metadata.start_date` (earliest raw-file mtime) so dates
  ride inside `experiments.sql` and the generators never need `sdgl.db`.

**Port as acceptance criteria** (already debugged upstream): hidden-folder
exclusion, raw-only date derivation, per-repetition qualifier display. See the
port inventory in `docs/ROADMAP.md`.
