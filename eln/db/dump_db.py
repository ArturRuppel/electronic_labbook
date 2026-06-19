#!/usr/bin/env python3
"""Deterministic SQL dump of experiments.db -> experiments.sql.

Determinism is the whole point: the dump is line-diffable and regenerating it
twice from the same database is byte-identical. To guarantee that we do NOT use
sqlite3's ``iterdump`` (which walks sqlite_master in creation order). Instead:

- schema objects are emitted in a fixed order: every ``table`` first (so INSERTs
  are valid), then ``index`` / ``trigger`` / ``view``;
- within each kind, objects are ordered by name;
- each table's rows are emitted in rowid order;
- values are serialized via SQLite's own ``quote()`` so NULLs, numbers, strings
  and blobs round-trip exactly.

Usage:
    python -m eln.db.dump_db [DB] [SQL]
        DB   path to experiments.db   (default: ./experiments.db)
        SQL  path to write the dump   (default: ./experiments.sql)
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from . import DEFAULT_DB_NAME, DEFAULT_SQL_NAME

_HEADER = "PRAGMA foreign_keys=OFF;\nBEGIN TRANSACTION;\n"
_FOOTER = "COMMIT;\n"


def _table_has_rowid(conn: sqlite3.Connection, table: str) -> bool:
    """A WITHOUT ROWID table cannot be ordered by rowid."""
    for row in conn.execute(f'PRAGMA index_list("{table}")'):
        # origin 'pk' on a WITHOUT ROWID table appears as a real index; the
        # reliable check is trying to read rowid.
        pass
    try:
        conn.execute(f'SELECT rowid FROM "{table}" LIMIT 0')
        return True
    except sqlite3.OperationalError:
        return False


def _iter_inserts(conn: sqlite3.Connection, table: str):
    """Yield deterministic INSERT statements for one table."""
    cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
    if not cols:
        return
    quoted = ", ".join(f'quote("{c}")' for c in cols)
    order = "rowid" if _table_has_rowid(conn, table) else ", ".join(
        f'"{c}"' for c in cols
    )
    query = f'SELECT {quoted} FROM "{table}" ORDER BY {order}'
    for row in conn.execute(query):
        values = ",".join(row)
        yield f'INSERT INTO "{table}" VALUES({values});\n'


def dump(db_path: str | Path, sql_path: str | Path) -> Path:
    """Dump ``db_path`` to ``sql_path`` deterministically. Returns the SQL path."""
    db_path = Path(db_path)
    sql_path = Path(sql_path)
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        master = conn.execute(
            """
            SELECT type, name, sql FROM sqlite_master
            WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()

        tables = sorted((n, s) for t, n, s in master if t == "table")
        others = sorted(
            (t, n, s) for t, n, s in master if t != "table"
        )  # index/trigger/view, by (type, name)

        parts: list[str] = [_HEADER]
        for name, sql in tables:
            parts.append(f"{sql};\n")
            parts.extend(_iter_inserts(conn, name))
        for _type, _name, sql in others:
            parts.append(f"{sql};\n")
        parts.append(_FOOTER)
    finally:
        conn.close()

    sql_path.write_text("".join(parts), encoding="utf-8")
    return sql_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministically dump experiments.db to experiments.sql")
    parser.add_argument("db", nargs="?", default=DEFAULT_DB_NAME, help="path to experiments.db")
    parser.add_argument("sql", nargs="?", default=DEFAULT_SQL_NAME, help="path to write experiments.sql")
    args = parser.parse_args(argv)
    out = dump(args.db, args.sql)
    print(f"Dumped {args.db} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
