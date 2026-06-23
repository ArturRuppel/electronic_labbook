# `eln.sdgl` — Scientific Data Graph Layer

The scan engine and the project's differentiator.

Contents:

- Scan of configured roots from the unified `labbook.toml`.
- The naming grammar: folders named exactly `CODE-NN` where the 5-character
  `CODE` is the experiment series and `NN` the repetition, with an `X` flag for
  excluded sessions (`SORVI-01`, `COV2D-X03`), and bare `CODE` folders for
  series-spanning aggregate analyses. Downstream structure comes from nesting
  (`SORVI-01/raw`), not from the folder name.
- `nodes`, `edges`, `file_locations` graph tables.
- The experiment date is always derived live from the earliest raw-file mtime;
  it is never stored. The scan scrubs any legacy `experiment_metadata.start_date`.

Behaviors worth noting: hidden-folder exclusion, raw-only date derivation, and
per-repetition qualifier display.
