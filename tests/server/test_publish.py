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
