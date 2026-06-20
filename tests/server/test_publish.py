"""Publish flow: dump experiments.sql into a real git data repo and commit."""

import sqlite3
import subprocess

import pytest

from eln.db import init_db
from eln.server.publish import publish


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)


@pytest.fixture
def data_repo(tmp_path):
    """A git-initialized data repo with experiments.db and a gitignore for binaries."""
    root = tmp_path
    _git(["init", "-q"], root)
    _git(["config", "user.email", "test@example.com"], root)
    _git(["config", "user.name", "Test"], root)
    (root / ".gitignore").write_text("*.db\n*.db-wal\n*.db-shm\n")

    db = root / "experiments.db"
    init_db.init_db(db)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO experiment_codes (title, code) VALUES ('Traction Force', 'TFMSP')")
    conn.execute(
        "INSERT INTO experiments (experiment_type, repetition, excluded, file_path) "
        "VALUES ('Traction Force', 1, 0, 'x')"
    )
    conn.commit()
    conn.close()

    (root / "reports").mkdir()
    (root / "reports" / "r.md").write_text("# report\n")

    _git(["add", ".gitignore"], root)
    _git(["commit", "-q", "-m", "init"], root)
    return root


def test_publish_dumps_sql_and_commits(data_repo):
    result = publish(data_repo, push=False)
    assert result["success"] is True
    assert "Committed" in result["message"]

    # experiments.sql is created and committed; the binary .db is not committed.
    sql = data_repo / "experiments.sql"
    assert sql.exists()
    assert "TFMSP" in sql.read_text()

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=str(data_repo), capture_output=True, text=True
    ).stdout
    assert "experiments.sql" in tracked
    assert "experiments.db" not in tracked  # binary stays out of git


def test_publish_nothing_to_publish_when_unchanged(data_repo):
    publish(data_repo, push=False)
    second = publish(data_repo, push=False)
    assert second["success"] is True
    assert "Nothing to publish" in second["message"]


def test_publish_missing_db_returns_error(tmp_path):
    result = publish(tmp_path, push=False)
    assert "error" in result
    assert "not found" in result["error"].lower()


def test_publish_creates_timestamp_when_cfg_enabled(data_repo, monkeypatch):
    from eln import timestamp
    monkeypatch.setattr(timestamp, "request_timestamp", lambda d, **k: b"TOKEN")
    monkeypatch.setattr(timestamp, "verify_token",
                        lambda *a, **k: {"valid": True, "gen_time": "T", "reason": None})
    cfg = {"enabled": True, "tsa_url": "https://t.example/tsr",
           "cert_bytes": b"CERT",
           "paths": ["experiments.sql", "reports", "timestamps"]}

    result = publish(data_repo, push=False, timestamp_cfg=cfg)
    assert result["success"] is True

    idx = timestamp.read_index(data_repo)
    assert len(idx) == 1 and idx[0]["status"] == "ok"
    tracked = subprocess.run(["git", "ls-files"], cwd=str(data_repo),
                             capture_output=True, text=True).stdout
    assert "timestamps/index.jsonl" in tracked  # token artifacts committed


def test_publish_timestamp_pending_does_not_block(data_repo, monkeypatch):
    from eln import timestamp

    def boom(d, **k):
        raise OSError("offline")

    monkeypatch.setattr(timestamp, "request_timestamp", boom)
    cfg = {"enabled": True, "tsa_url": "https://t.example/tsr",
           "cert_bytes": b"CERT", "paths": ["experiments.sql", "timestamps"]}

    result = publish(data_repo, push=False, timestamp_cfg=cfg)
    assert result["success"] is True  # publish still succeeds
    assert timestamp.read_index(data_repo)[0]["status"] == "pending"


def test_publish_without_timestamp_cfg_is_unchanged(data_repo):
    result = publish(data_repo, push=False)  # no timestamp_cfg -> no timestamping
    assert result["success"] is True
    assert (data_repo / "timestamps").exists() is False


def test_publish_rejects_oversized_staged_file(data_repo):
    """A staged file >90 MB hard-fails the publish and is never committed."""
    big = data_repo / "reports" / "huge.bin"
    with open(big, "wb") as fh:
        fh.truncate(91 * 1024 * 1024)  # sparse: 91 MB apparent size, ~no disk use

    result = publish(data_repo, push=False)
    assert "error" in result
    assert "huge.bin" in result["error"]

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=str(data_repo), capture_output=True, text=True
    ).stdout
    assert "huge.bin" not in tracked  # nothing oversized committed
