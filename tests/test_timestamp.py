"""RFC 3161 trusted timestamps (Roadmap step 11, layer 3).

Manifest digest, index I/O, TSA request/verify wrappers (rfc3161ng mocked),
create/retry orchestration (our request seam mocked), and the verify summary.
No live network or real crypto is exercised here.
"""

import hashlib
from datetime import datetime, timezone

from eln import timestamp


def _write(root, rel, data):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def _cfg(tmp_path, **over):
    base = {"enabled": True, "tsa_url": "https://tsa.example/tsr",
            "cert_bytes": b"CERT", "paths": ["experiments.sql"]}
    base.update(over)
    return base


# ---- Task 1: manifest + snapshot digest ----------------------------------

def test_build_manifest_is_sorted_and_hashed(tmp_path):
    _write(tmp_path, "experiments.sql", b"CREATE TABLE x;")
    _write(tmp_path, "reports/b.md", b"bbb")
    _write(tmp_path, "reports/a.md", b"aaa")

    manifest = timestamp.build_manifest(tmp_path, ["experiments.sql", "reports"])

    sql_h = hashlib.sha256(b"CREATE TABLE x;").hexdigest()
    a_h = hashlib.sha256(b"aaa").hexdigest()
    b_h = hashlib.sha256(b"bbb").hexdigest()
    assert manifest == (
        f"experiments.sql\t{sql_h}\n"
        f"reports/a.md\t{a_h}\n"
        f"reports/b.md\t{b_h}\n"
    )


def test_snapshot_digest_matches_manifest_hash(tmp_path):
    _write(tmp_path, "experiments.sql", b"data")
    digest_hex, manifest = timestamp.snapshot_digest(tmp_path, ["experiments.sql"])
    assert digest_hex == hashlib.sha256(manifest.encode("utf-8")).hexdigest()


def test_snapshot_digest_ignores_missing_paths(tmp_path):
    _write(tmp_path, "experiments.sql", b"data")
    digest_hex, manifest = timestamp.snapshot_digest(
        tmp_path, ["experiments.sql", "reports"])
    assert "reports" not in manifest
    assert digest_hex


# ---- Task 2: id + index I/O ----------------------------------------------

def test_make_timestamp_id_format():
    when = datetime(2026, 6, 20, 14, 32, 1, tzinfo=timezone.utc)
    ts_id = timestamp.make_timestamp_id("9f86d081abc123", when=when)
    assert ts_id == "20260620T143201Z-9f86d081abc1"


def test_index_append_read_update(tmp_path):
    timestamp.append_index(tmp_path, {"id": "A", "status": "pending"})
    timestamp.append_index(tmp_path, {"id": "B", "status": "ok"})
    assert [e["id"] for e in timestamp.read_index(tmp_path)] == ["A", "B"]

    timestamp.update_index(tmp_path, "A", status="ok", gen_time="t")
    rows = {e["id"]: e for e in timestamp.read_index(tmp_path)}
    assert rows["A"]["status"] == "ok"
    assert rows["A"]["gen_time"] == "t"
    assert rows["B"]["status"] == "ok"


def test_read_index_missing_is_empty(tmp_path):
    assert timestamp.read_index(tmp_path) == []


# ---- Task 3: TSA request + token verify wrappers -------------------------

def test_request_timestamp_passes_digest_and_returns_token(monkeypatch):
    calls = {}

    class FakeStamper:
        def __init__(self, url, certificate=None, hashname=None, timeout=None):
            calls["url"] = url
            calls["hashname"] = hashname

        def __call__(self, digest=None, return_tsr=False):
            calls["digest"] = digest
            return b"TOKEN-BYTES"

    monkeypatch.setattr(timestamp.rfc3161ng, "RemoteTimestamper", FakeStamper)
    token = timestamp.request_timestamp(
        "9f86d0", tsa_url="https://tsa.example/tsr", cert_bytes=b"CERT")
    assert token == b"TOKEN-BYTES"
    assert calls["url"] == "https://tsa.example/tsr"
    assert calls["hashname"] == "sha256"
    assert calls["digest"] == bytes.fromhex("9f86d0")


def test_verify_token_valid(monkeypatch):
    monkeypatch.setattr(timestamp.rfc3161ng, "check_timestamp", lambda *a, **k: True)
    monkeypatch.setattr(
        timestamp.rfc3161ng, "get_timestamp",
        lambda token: datetime(2026, 6, 20, tzinfo=timezone.utc))
    out = timestamp.verify_token(b"TOK", "9f86d0", b"CERT")
    assert out["valid"] is True
    assert out["gen_time"].startswith("2026-06-20")
    assert out["reason"] is None


def test_verify_token_invalid_on_exception(monkeypatch):
    def boom(*a, **k):
        raise ValueError("bad signature")

    monkeypatch.setattr(timestamp.rfc3161ng, "check_timestamp", boom)
    out = timestamp.verify_token(b"TOK", "9f86d0", b"CERT")
    assert out["valid"] is False
    assert "bad signature" in out["reason"]


# ---- Task 4: create_timestamp + retry_pending ----------------------------

def test_create_timestamp_success_writes_token_and_index(tmp_path, monkeypatch):
    _write(tmp_path, "experiments.sql", b"data")
    monkeypatch.setattr(timestamp, "request_timestamp", lambda d, **k: b"TOKEN")
    monkeypatch.setattr(
        timestamp, "verify_token",
        lambda *a, **k: {"valid": True, "gen_time": "2026-06-20T00:00:00+00:00", "reason": None})

    entry = timestamp.create_timestamp(tmp_path, ["experiments.sql"], _cfg(tmp_path))

    assert entry["status"] == "ok"
    tdir = tmp_path / "timestamps"
    assert (tdir / f"{entry['id']}.tsr").read_bytes() == b"TOKEN"
    assert (tdir / f"{entry['id']}.manifest").exists()
    assert timestamp.read_index(tmp_path)[0]["id"] == entry["id"]
    assert entry["gen_time"] == "2026-06-20T00:00:00+00:00"


def test_create_timestamp_pending_on_tsa_failure(tmp_path, monkeypatch):
    _write(tmp_path, "experiments.sql", b"data")

    def boom(d, **k):
        raise OSError("network down")

    monkeypatch.setattr(timestamp, "request_timestamp", boom)

    entry = timestamp.create_timestamp(tmp_path, ["experiments.sql"], _cfg(tmp_path))

    assert entry["status"] == "pending"
    tdir = tmp_path / "timestamps"
    assert not (tdir / f"{entry['id']}.tsr").exists()
    assert (tdir / f"{entry['id']}.manifest").exists()
    assert timestamp.read_index(tmp_path)[0]["status"] == "pending"


def test_retry_pending_completes_entry(tmp_path, monkeypatch):
    _write(tmp_path, "experiments.sql", b"data")

    def boom(d, **k):
        raise OSError()

    monkeypatch.setattr(timestamp, "request_timestamp", boom)
    pending = timestamp.create_timestamp(tmp_path, ["experiments.sql"], _cfg(tmp_path))

    seen = {}

    def _ok(d, **k):
        seen["digest"] = d
        return b"TOKEN"

    monkeypatch.setattr(timestamp, "request_timestamp", _ok)
    monkeypatch.setattr(timestamp, "verify_token",
                        lambda *a, **k: {"valid": True, "gen_time": "T", "reason": None})

    updated = timestamp.retry_pending(tmp_path, _cfg(tmp_path))

    assert len(updated) == 1 and updated[0]["status"] == "ok"
    assert seen["digest"] == pending["snapshot_digest"]
    assert (tmp_path / "timestamps" / f"{pending['id']}.tsr").read_bytes() == b"TOKEN"
    assert timestamp.read_index(tmp_path)[0]["status"] == "ok"


# ---- Task 5: verify_all ---------------------------------------------------

def test_verify_all_reports_ok_invalid_pending_and_live_anchor(tmp_path, monkeypatch):
    _write(tmp_path, "experiments.sql", b"data")
    monkeypatch.setattr(timestamp, "request_timestamp", lambda d, **k: b"TOKEN")
    monkeypatch.setattr(timestamp, "verify_token",
                        lambda *a, **k: {"valid": True, "gen_time": "T", "reason": None})
    timestamp.create_timestamp(tmp_path, ["experiments.sql"], _cfg(tmp_path))

    summary = timestamp.verify_all(tmp_path, _cfg(tmp_path))
    assert summary["timestamps"] == 1
    assert summary["ok"] == 1
    assert summary["invalid"] == []
    assert summary["pending"] == []
    assert summary["live_anchored"] is True


def test_verify_all_flags_invalid_token(tmp_path, monkeypatch):
    _write(tmp_path, "experiments.sql", b"data")
    monkeypatch.setattr(timestamp, "request_timestamp", lambda d, **k: b"TOKEN")
    monkeypatch.setattr(timestamp, "verify_token",
                        lambda *a, **k: {"valid": True, "gen_time": "T", "reason": None})
    timestamp.create_timestamp(tmp_path, ["experiments.sql"], _cfg(tmp_path))

    monkeypatch.setattr(timestamp, "verify_token",
                        lambda *a, **k: {"valid": False, "gen_time": None, "reason": "bad"})
    summary = timestamp.verify_all(tmp_path, _cfg(tmp_path))
    assert summary["ok"] == 0
    assert len(summary["invalid"]) == 1
