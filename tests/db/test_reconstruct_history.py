"""Tests for the one-time history reconstruction migration."""

import subprocess

from eln.db import connect, init_db, reconstruct_history


def _git(repo, *args, env=None):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env)


def _commit_db(src, db_rel, msg, date, mutate):
    """Mutate the binary DB in the source repo and commit it with a fixed date."""
    db = src / db_rel
    conn = connect(db)
    mutate(conn)
    conn.commit()
    conn.close()
    env = {
        "GIT_AUTHOR_NAME": "Ada", "GIT_AUTHOR_EMAIL": "ada@example.com", "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_NAME": "Ada", "GIT_COMMITTER_EMAIL": "ada@example.com", "GIT_COMMITTER_DATE": date,
    }
    _git(src, "add", db_rel)
    import os
    _git(src, "commit", "-m", msg, env={**os.environ, **env})


def test_reconstruct_produces_diffable_commits_and_skips_identical(tmp_path):
    src = tmp_path / "source"
    (src / "data").mkdir(parents=True)
    _git(src, "init", "-q", "-b", "main")
    _git(src, "config", "user.email", "ada@example.com")
    _git(src, "config", "user.name", "Ada")

    db_rel = "data/experiments.db"
    init_db.init_db(src / db_rel)
    _git(src, "add", db_rel)
    import os
    base_env = {
        "GIT_AUTHOR_NAME": "Ada", "GIT_AUTHOR_EMAIL": "ada@example.com",
        "GIT_AUTHOR_DATE": "2025-01-01T00:00:00", "GIT_COMMITTER_NAME": "Ada",
        "GIT_COMMITTER_EMAIL": "ada@example.com", "GIT_COMMITTER_DATE": "2025-01-01T00:00:00",
    }
    _git(src, "commit", "-m", "init schema", env={**os.environ, **base_env})

    _commit_db(src, db_rel, "add AA01", "2025-01-02T00:00:00",
               lambda c: c.execute("INSERT INTO experiments (experiment_uid, repetition, file_path) VALUES ('AA01', 1, '/d/AA01')"))
    # A no-op semantic change (touch then rewrite identical) -> identical SQL, must be skipped.
    _commit_db(src, db_rel, "vacuum", "2025-01-03T00:00:00", lambda c: c.execute("VACUUM"))
    _commit_db(src, db_rel, "add AB02", "2025-01-04T00:00:00",
               lambda c: c.execute("INSERT INTO experiments (experiment_uid, repetition, file_path) VALUES ('AB02', 1, '/d/AB02')"))

    # Target repo with one base commit.
    tgt = tmp_path / "target"
    tgt.mkdir()
    _git(tgt, "init", "-q", "-b", "main")
    _git(tgt, "config", "user.email", "t@example.com")
    _git(tgt, "config", "user.name", "T")
    (tgt / "README.md").write_text("data repo\n")
    _git(tgt, "add", "README.md")
    _git(tgt, "commit", "-m", "scaffold")

    stats = reconstruct_history.reconstruct(src, db_rel, tgt)

    assert stats["total"] == 4          # init + add AA01 + vacuum + add AB02
    assert stats["committed"] == 3      # init schema, add AA01, add AB02
    assert stats["skipped_identical"] == 1  # vacuum produced identical SQL
    assert stats["errors"] == 0

    # experiments.sql is tracked; original author/date preserved on reconstructed commits.
    log = subprocess.run(
        ["git", "-C", str(tgt), "log", "--format=%an|%ad|%s", "--date=short", "--", "experiments.sql"],
        check=True, capture_output=True, text=True,
    ).stdout
    assert "Ada|2025-01-04|add AB02" in log
    assert "Ada|2025-01-02|add AA01" in log
    assert "reconstructed" in subprocess.run(
        ["git", "-C", str(tgt), "log", "-1", "--format=%b"], capture_output=True, text=True
    ).stdout.lower()
