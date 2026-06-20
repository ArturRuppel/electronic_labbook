"""RFC 3161 trusted timestamps (Roadmap step 11, layer 3).

Manifest digest, index I/O, TSA request/verify wrappers (rfc3161ng mocked),
create/retry orchestration (our request seam mocked), and the verify summary.
No live network or real crypto is exercised here.
"""

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from eln import timestamp

_FIXTURES = Path(__file__).parent / "fixtures"
_SAMPLE_TSR = _FIXTURES / "digicert_sample.tsr"
_SAMPLE_DIGEST = _FIXTURES / "digicert_sample.digest"
_ROOT_PEM = Path(timestamp.DEFAULT_TSA_CERT)
_needs_fixture = pytest.mark.skipif(
    not _SAMPLE_TSR.exists(), reason="recorded DigiCert token fixture absent")


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
        def __init__(self, url, **kwargs):
            calls["url"] = url
            calls.update(kwargs)

        def __call__(self, digest=None, return_tsr=False):
            calls["digest"] = digest
            return b"TOKEN-BYTES"

    monkeypatch.setattr(timestamp.rfc3161ng, "RemoteTimestamper", FakeStamper)
    token = timestamp.request_timestamp(
        "9f86d0", tsa_url="https://tsa.example/tsr", cert_bytes=b"CERT")
    assert token == b"TOKEN-BYTES"
    assert calls["url"] == "https://tsa.example/tsr"
    assert calls["hashname"] == "sha256"
    assert calls["include_tsa_certificate"] is True
    assert calls["digest"] == bytes.fromhex("9f86d0")


@_needs_fixture
def test_verify_token_valid_against_fixture():
    token = _SAMPLE_TSR.read_bytes()
    digest = _SAMPLE_DIGEST.read_text().strip()
    out = timestamp.verify_token(token, digest, _ROOT_PEM.read_bytes())
    assert out["valid"] is True
    assert out["gen_time"] is not None
    assert out["reason"] is None


@_needs_fixture
def test_verify_token_invalid_on_tampered_digest():
    token = _SAMPLE_TSR.read_bytes()
    out = timestamp.verify_token(token, "b" * 64, _ROOT_PEM.read_bytes())
    assert out["valid"] is False
    assert out["reason"]


@_needs_fixture
def test_verify_token_invalid_without_trusted_root():
    token = _SAMPLE_TSR.read_bytes()
    digest = _SAMPLE_DIGEST.read_text().strip()
    out = timestamp.verify_token(token, digest, b"")  # no trusted roots
    assert out["valid"] is False
    assert "trusted root" in out["reason"]


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
