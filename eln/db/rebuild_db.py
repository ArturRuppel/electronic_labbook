#!/usr/bin/env python3
"""Rebuild experiments.db from the diffable experiments.sql.

Idempotent: by default a no-op if the binary already exists (CI calls this when
the binary is absent). Use --force to rebuild over an existing binary.

The rebuild is atomic: the database is built in a temp file next to the target
and moved into place only on success, so a failure never leaves a half-written db.

Usage:
    python -m eln.db.rebuild_db [SQL] [DB] [--force]
        SQL  path to experiments.sql  (default: ./experiments.sql)
        DB   path to write the binary (default: ./experiments.db)
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from . import DEFAULT_DB_NAME, DEFAULT_SQL_NAME


def rebuild(sql_path: str | Path, db_path: str | Path, force: bool = False) -> Path:
    """Build ``db_path`` from ``sql_path``. Returns the database path."""
    sql_path = Path(sql_path)
    db_path = Path(db_path)
    if not sql_path.exists():
        raise FileNotFoundError(f"SQL dump not found: {sql_path}")
    if db_path.exists() and not force:
        # Idempotent no-op: the binary is a build artifact; leave it alone.
        return db_path

    script = sql_path.read_text(encoding="utf-8")
    tmp_path = db_path.with_name(db_path.name + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    conn = sqlite3.connect(str(tmp_path))
    try:
        conn.executescript(script)
        conn.commit()
    finally:
        conn.close()

    os.replace(tmp_path, db_path)  # atomic on the same filesystem
    return db_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild experiments.db from experiments.sql")
    parser.add_argument("sql", nargs="?", default=DEFAULT_SQL_NAME, help="path to experiments.sql")
    parser.add_argument("db", nargs="?", default=DEFAULT_DB_NAME, help="path to write experiments.db")
    parser.add_argument("--force", action="store_true", help="rebuild even if the binary exists")
    args = parser.parse_args(argv)
    existed = Path(args.db).exists()
    out = rebuild(args.sql, args.db, force=args.force)
    if existed and not args.force:
        print(f"{args.db} already exists; left unchanged (use --force to rebuild)")
    else:
        print(f"Rebuilt {out} <- {args.sql}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
