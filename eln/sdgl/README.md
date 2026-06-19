# `eln.sdgl` — Scientific Data Graph Layer

**Roadmap step 4.** The scan engine and the project's differentiator.

Lands here (ported from the original `sdgl.py`):

- Scan of configured roots from `sdgl.toml`.
- The naming grammar: folders named exactly `CODE-NN` where the 5-character
  `CODE` is the experiment series and `NN` the repetition, with an `X` flag for
  excluded sessions (`SORVI-01`, `COV2D-X03`), and bare `CODE` folders for
  series-spanning aggregate analyses. Downstream structure comes from nesting
  (`SORVI-01/raw`), not from the folder name.
- `nodes`, `edges`, `file_locations`, `scan_findings` graph tables.
- Materialized `experiment_metadata.start_date` (earliest raw-file mtime) so dates
  ride inside `experiments.sql` and the generators never need `sdgl.db`.

**Port as acceptance criteria** (already debugged upstream): hidden-folder
exclusion, raw-only date derivation, per-repetition qualifier display. See the
port inventory in `docs/ROADMAP.md`.
