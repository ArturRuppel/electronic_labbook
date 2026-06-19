#!/usr/bin/env python3
"""Create a fresh, empty experiments.db from the canonical schema.sql.

Usage:
    python -m eln.db.init_db [DB] [--force]
        DB   path to create (default: ./experiments.db)
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from . import DEFAULT_DB_NAME, SCHEMA_PATH


def init_db(db_path: str | Path, force: bool = False) -> Path:
    """Create an empty database at ``db_path`` from ``schema.sql``."""
    db_path = Path(db_path)
    if db_path.exists() and not force:
        raise FileExistsError(f"refusing to overwrite existing database: {db_path} (use --force)")
    if db_path.exists():
        db_path.unlink()

    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()
    return db_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Initialize an empty experiments.db from schema.sql")
    parser.add_argument("db", nargs="?", default=DEFAULT_DB_NAME, help="path to create")
    parser.add_argument("--force", action="store_true", help="overwrite an existing database")
    args = parser.parse_args(argv)
    out = init_db(args.db, force=args.force)
    print(f"Initialized {out} from {SCHEMA_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
