"""SDGL content hashing on scan (Roadmap step 11, layer 1): SHA-256 per file,
incremental re-hashing, hash preservation, and tamper-evidence verification."""

import hashlib
import os
import sqlite3
from datetime import datetime

import pytest

from eln.db import init_db
from eln.sdgl import SDGL, hashing_options


def _write(path, data, ts):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (ts, ts))


@pytest.fixture
def data_root(tmp_path):
    """A data root with one experiment (TFMSP-01) holding two files."""
    root = tmp_path
    db = root / "experiments.db"
    init_db.init_db(db)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO experiment_codes (title, code) VALUES ('Traction', 'TFMSP')")
    conn.execute("INSERT INTO experiments (experiment_type, repetition, file_path) "
                 "VALUES ('Traction', 1, 'x')")
    conn.commit()
    conn.close()

    ts = datetime(2025, 3, 10, 12, 0).timestamp()
    _write(root / "data" / "TFMSP-01" / "raw" / "img.tif", b"bead data", ts)
    _write(root / "data" / "TFMSP-01" / "analysis" / "out.csv", b"a,b\n1,2\n", ts)
    return root, db


def _roots():
    return [{"name": "data", "path": "data"}]


def _hash_of(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _locations(sdgl):
    conn = sdgl.connect()
    rows = {r["rel_path"]: r for r in conn.execute(
        "SELECT rel_path, is_dir, content_hash, hashed_at FROM file_locations "
        "WHERE node_id = 'experiment:TFMSP-01'")}
    conn.close()
    return rows


def test_scan_stores_file_hashes(data_root):
    root, _db = data_root
    sdgl = SDGL(root)
    sdgl.scan_roots(_roots(), content_hash=True)

    rows = _locations(sdgl)
    assert rows["raw/img.tif"]["content_hash"] == _hash_of(b"bead data")
    assert rows["analysis/out.csv"]["content_hash"] == _hash_of(b"a,b\n1,2\n")
    # Directories are never hashed.
    assert rows["raw"]["is_dir"] == 1
    assert rows["raw"]["content_hash"] is None


def test_hashing_off_stores_no_hash(data_root):
    root, _db = data_root
    sdgl = SDGL(root)
    sdgl.scan_roots(_roots())  # default: content_hash=False
    rows = _locations(sdgl)
    assert all(r["content_hash"] is None for r in rows.values())


def test_rescan_reuses_hash_when_unchanged(data_root):
    """An unchanged file keeps its original hash record (no re-read)."""
    root, _db = data_root
    sdgl = SDGL(root)
    sdgl.scan_roots(_roots(), content_hash=True)
    first = _locations(sdgl)["raw/img.tif"]["hashed_at"]

    # Same size + mtime: the stored hash must be reused verbatim. Prove it by
    # corrupting the bytes in place (same length, same mtime) — a reuse keeps
    # the OLD hash, a recompute would pick up the new content.
    img = root / "data" / "TFMSP-01" / "raw" / "img.tif"
    ts = img.stat().st_mtime
    img.write_bytes(b"XXXX data")  # same 9-byte length
    os.utime(img, (ts, ts))
    sdgl.scan_roots(_roots(), content_hash=True)

    row = _locations(sdgl)["raw/img.tif"]
    assert row["content_hash"] == _hash_of(b"bead data")  # reused, not recomputed
    assert row["hashed_at"] == first


def test_rescan_recomputes_when_mtime_changes(data_root):
    root, _db = data_root
    sdgl = SDGL(root)
    sdgl.scan_roots(_roots(), content_hash=True)

    img = root / "data" / "TFMSP-01" / "raw" / "img.tif"
    img.write_bytes(b"new content here")
    os.utime(img, (datetime(2025, 5, 1).timestamp(),) * 2)
    sdgl.scan_roots(_roots(), content_hash=True)

    assert _locations(sdgl)["raw/img.tif"]["content_hash"] == _hash_of(b"new content here")


def test_disabled_rescan_preserves_existing_hash(data_root):
    """A later scan with hashing off must not erase hashes from an earlier pass."""
    root, _db = data_root
    sdgl = SDGL(root)
    sdgl.scan_roots(_roots(), content_hash=True)
    sdgl.scan_roots(_roots())  # hashing off

    assert _locations(sdgl)["raw/img.tif"]["content_hash"] == _hash_of(b"bead data")


def test_hash_max_bytes_skips_large_files(data_root):
    root, _db = data_root
    sdgl = SDGL(root)
    # out.csv is 8 bytes, img.tif is 9 bytes; cap below img.tif only.
    sdgl.scan_roots(_roots(), content_hash=True, hash_max_bytes=8)

    rows = _locations(sdgl)
    assert rows["analysis/out.csv"]["content_hash"] == _hash_of(b"a,b\n1,2\n")
    assert rows["raw/img.tif"]["content_hash"] is None


def test_verify_hashes_flags_drift_and_loss(data_root):
    root, _db = data_root
    sdgl = SDGL(root)
    sdgl.scan_roots(_roots(), content_hash=True)

    clean = sdgl.verify_hashes()
    assert clean["checked"] == 2
    assert clean["ok"] == 2
    assert clean["mismatch"] == [] and clean["missing"] == []

    # Tamper with one file's contents and remove the other; verify must catch both
    # without a re-scan (the stored hash is the witness).
    img = root / "data" / "TFMSP-01" / "raw" / "img.tif"
    img.write_bytes(b"tampered")
    (root / "data" / "TFMSP-01" / "analysis" / "out.csv").unlink()

    result = sdgl.verify_hashes()
    assert result["ok"] == 0
    assert [m["rel_path"] for m in result["mismatch"]] == ["raw/img.tif"]
    assert result["mismatch"][0]["actual"] == _hash_of(b"tampered")
    assert [m["rel_path"] for m in result["missing"]] == ["analysis/out.csv"]


def test_hashing_options_parsing():
    assert hashing_options(None) == (False, None)
    assert hashing_options({}) == (False, None)
    assert hashing_options({"content_hashing": True}) == (True, None)
    assert hashing_options({"content_hashing": True, "hash_max_bytes": 1024}) == (True, 1024)
