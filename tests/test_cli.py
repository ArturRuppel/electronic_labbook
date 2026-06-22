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


def test_regenerate_scaffold_series_flag_runs_scaffolder(monkeypatch, tmp_path, capsys):
    import eln.cli as cli
    import eln.generators.reports as reports
    cfg = Config(data_root=tmp_path)
    monkeypatch.setattr(cli, "_load", lambda args: cfg)

    calls = {}

    def _fake_scaffold(root):
        calls["root"] = root
        return [root / "reports/auto/COV2D.md"]
    monkeypatch.setattr(reports, "generate_series_reports", _fake_scaffold)
    monkeypatch.setattr("eln.generators.generate_all", lambda root, out: {})

    rc = cli.main(["regenerate", "--scaffold-series"])
    assert rc == 0
    assert calls["root"] == tmp_path
    assert "scaffolded 1 series report stub" in capsys.readouterr().out


def test_regenerate_without_flag_skips_scaffolder(monkeypatch, tmp_path):
    import eln.cli as cli
    import eln.generators.reports as reports
    cfg = Config(data_root=tmp_path)
    monkeypatch.setattr(cli, "_load", lambda args: cfg)

    def _fail(root):
        raise AssertionError("scaffolder should not run without --scaffold-series")
    monkeypatch.setattr(reports, "generate_series_reports", _fail)
    monkeypatch.setattr("eln.generators.generate_all", lambda root, out: {})

    assert cli.main(["regenerate"]) == 0


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


def test_stamp_subcommand_in_parser():
    parser = build_parser()
    sub = next(a for a in parser._actions if a.dest == "command")
    assert "stamp" in sub.choices


def test_parse_params_json_then_string():
    from eln.cli import _parse_params
    assert _parse_params(["threshold=0.5", "n=3", "flag=true", "name=foo"]) == {
        "threshold": 0.5, "n": 3, "flag": True, "name": "foo",
    }
    with pytest.raises(ValueError):
        _parse_params(["bogus"])  # no '='


def test_cli_stamp_derived_records_node_and_edge(monkeypatch, tmp_path, capsys):
    import json
    import eln.cli as cli
    monkeypatch.setattr(cli, "_load", lambda args: Config(data_root=tmp_path))
    art = tmp_path / "data" / "SORVI-01" / "analysis" / "plot.png"
    art.parent.mkdir(parents=True)
    art.write_bytes(b"PNGDATA")

    rc = cli.main(["stamp", str(art), "--function", "mylib.run",
                   "--param", "threshold=0.5"])
    assert rc == 0
    assert "Stamped derived artifact" in capsys.readouterr().out

    # Derived artifacts are keyed by the portable experiment-relative path
    # (the data/ prefix is stripped), so the node id is machine-independent.
    node_id = "dataset:SORVI-01/analysis/plot.png"
    conn = sqlite3.connect(str(tmp_path / "sdgl.db"))
    node = conn.execute("SELECT 1 FROM nodes WHERE id = ?", (node_id,)).fetchone()
    edge = conn.execute(
        "SELECT metadata FROM edges WHERE source_id = ? AND target_id = ? "
        "AND relation_type = 'generates'",
        ("experiment:SORVI-01", node_id),
    ).fetchone()
    conn.close()
    assert node is not None                       # artifact became a dataset node
    assert edge is not None                        # generates edge from the experiment
    assert json.loads(edge[0])["params"]["threshold"] == 0.5  # param parsed as float


def test_cli_stamp_curated_requires_tool_and_method(monkeypatch, tmp_path, capsys):
    import eln.cli as cli
    monkeypatch.setattr(cli, "_load", lambda args: Config(data_root=tmp_path))
    art = tmp_path / "data" / "SORVI-01" / "fig.png"
    art.parent.mkdir(parents=True)
    art.write_bytes(b"x")
    rc = cli.main(["stamp", str(art), "--kind", "curated"])  # missing tool/method
    assert rc == 1
    assert "error:" in capsys.readouterr().err


def test_cli_stamp_uninferable_producer_errors(monkeypatch, tmp_path, capsys):
    import eln.cli as cli
    monkeypatch.setattr(cli, "_load", lambda args: Config(data_root=tmp_path))
    art = tmp_path / "figures" / "fig3.png"   # no CODE-NN component in the path
    art.parent.mkdir(parents=True)
    art.write_bytes(b"x")
    rc = cli.main(["stamp", str(art)])
    assert rc == 1
    assert "produced_by" in capsys.readouterr().err


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
