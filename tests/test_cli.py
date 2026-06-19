import sqlite3
import pytest

from eln.cli import build_parser, _ensure_db, main
from eln.config import Config


def _make_db(path):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()


def test_bare_invocation_prints_help_and_exits_zero(capsys):
    rc = main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "admin" in out and "publish" in out


def test_parser_has_all_subcommands():
    parser = build_parser()
    sub = next(a for a in parser._actions if a.dest == "command")
    for name in ["admin", "scan", "regenerate", "rebuild", "publish", "backup"]:
        assert name in sub.choices


def test_ensure_db_builds_when_missing(tmp_path):
    sql = tmp_path / "experiments.sql"
    sql.write_text("CREATE TABLE t (id INTEGER);", encoding="utf-8")
    db = tmp_path / "experiments.db"
    cfg = Config(data_root=tmp_path)
    _ensure_db(cfg)
    assert db.exists()


def test_ensure_db_does_not_clobber_live_db(tmp_path):
    sql = tmp_path / "experiments.sql"
    sql.write_text("CREATE TABLE t (id INTEGER);", encoding="utf-8")
    db = tmp_path / "experiments.db"
    _make_db(db)
    conn = sqlite3.connect(str(db)); conn.execute("CREATE TABLE live (x INTEGER)"); conn.commit(); conn.close()
    cfg = Config(data_root=tmp_path)
    _ensure_db(cfg)
    conn = sqlite3.connect(str(db))
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "live" in names  # untouched


def test_backup_is_a_stub(capsys):
    rc = main(["backup"])
    err = capsys.readouterr().err
    assert rc != 0
    assert "step 8" in err.lower()
