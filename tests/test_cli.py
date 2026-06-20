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
    for name in ["admin", "scan", "regenerate", "rebuild", "publish", "backup",
                 "timestamp"]:
        assert name in sub.choices


def test_cli_timestamp_retry(monkeypatch, tmp_path, capsys):
    import eln.cli as cli
    from eln import timestamp
    cfg = Config(data_root=tmp_path, timestamp={})
    monkeypatch.setattr(cli, "_load", lambda args: cfg)
    monkeypatch.setattr(timestamp, "resolve_timestamp_config",
                        lambda raw: {"enabled": True, "tsa_url": "u", "cert_bytes": b"C",
                                     "paths": ["experiments.sql"]})
    monkeypatch.setattr(timestamp, "retry_pending",
                        lambda root, c: [{"id": "X", "status": "ok"}])

    rc = cli.main(["timestamp", "--retry"])
    assert rc == 0
    assert "X" in capsys.readouterr().out


def test_cli_verify_includes_timestamps(monkeypatch, tmp_path, capsys):
    import eln.cli as cli
    from eln import timestamp
    from eln.sdgl import SDGL
    cfg = Config(data_root=tmp_path, timestamp={})
    monkeypatch.setattr(cli, "_load", lambda args: cfg)
    monkeypatch.setattr(SDGL, "verify_hashes",
                        lambda self, node_id=None: {"checked": 0, "ok": 0,
                                                    "mismatch": [], "missing": []})
    monkeypatch.setattr(timestamp, "resolve_timestamp_config",
                        lambda raw: {"enabled": True, "tsa_url": "u", "cert_bytes": b"C",
                                     "paths": []})
    monkeypatch.setattr(timestamp, "verify_all",
                        lambda root, c: {"timestamps": 2, "ok": 2, "invalid": [],
                                         "pending": [], "live_anchored": True})

    rc = cli.main(["verify"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "2 ok" in out and "anchored" in out.lower()


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


def test_backup_subcommand_parses(monkeypatch):
    import eln.cli as cli
    called = {}

    def fake_cmd_backup(args):
        called["port"] = args.port
        return 0

    monkeypatch.setattr(cli, "cmd_backup", fake_cmd_backup)
    rc = cli.main(["backup", "--port", "5099", "--no-browser"])
    assert rc == 0
    assert called["port"] == 5099
