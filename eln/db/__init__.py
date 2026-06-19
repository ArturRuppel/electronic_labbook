"""Database plumbing: schema-as-source-of-truth + diffable dump/rebuild.

- ``schema.sql``      canonical DDL (the source of truth).
- ``init_db``         create a fresh empty database from ``schema.sql``.
- ``dump_db``         experiments.db -> deterministic, line-diffable experiments.sql.
- ``rebuild_db``      experiments.sql -> experiments.db (idempotent).

The binary database is a build artifact and is never committed; ``experiments.sql``
is the versioned form. See ``docs/ROADMAP.md`` step 2 and
``plans/plan-G-db-versioning.md``.
"""

from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

DEFAULT_DB_NAME = "experiments.db"
DEFAULT_SQL_NAME = "experiments.sql"

__all__ = ["SCHEMA_PATH", "DEFAULT_DB_NAME", "DEFAULT_SQL_NAME", "connect"]


def connect(path):
    """Open a SQLite connection with foreign-key enforcement on."""
    import sqlite3

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
