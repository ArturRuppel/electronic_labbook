# `eln.db` — schema + diffable DB plumbing

**Roadmap step 2.** This package owns the database as a *build artifact*.

Lands here:

- **Schema / migrations** as the source of truth for `experiments.db`.
- **`dump_db.py`** — deterministic dump to `experiments.sql`
  (`.iterdump()`, tables in name order, rows in rowid order) so the SQL is
  line-diffable and regenerating twice is byte-identical.
- **`rebuild_db.py`** — idempotent `experiments.sql` → `experiments.db`.

The binary `*.db` is never committed (see `.gitignore`); `experiments.sql` is the
versioned form and lives in the **data** repo.

See `docs/ROADMAP.md` and `plans/plan-G-db-versioning.md` (ported in step 2).
