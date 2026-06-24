import subprocess

import pytest

from eln.analysis.gitref import (
    file_at_commit,
    file_history,
    head_commit,
    path_dirty,
    remote_url,
    repo_root,
)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "T")
    (r / "a.txt").write_text("one")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "first")
    return r


def test_head_commit_resolves_clean(repo):
    commit, dirty = head_commit(repo)
    assert len(commit) == 40
    assert dirty is False


def test_head_commit_flags_dirty(repo):
    (repo / "a.txt").write_text("changed")
    commit, dirty = head_commit(repo)
    assert dirty is True


def test_head_commit_outside_repo_is_none(tmp_path):
    assert head_commit(tmp_path) == (None, False)


def test_repo_root_finds_toplevel(repo):
    sub = repo / "deep" / "nested"
    sub.mkdir(parents=True)
    assert repo_root(sub) == repo.resolve()


def test_repo_root_outside_repo_is_none(tmp_path):
    assert repo_root(tmp_path) is None


def test_remote_url_absent_is_none(repo):
    assert remote_url(repo) is None


def test_path_dirty_clean_committed_file(repo):
    assert path_dirty(repo, repo / "a.txt") is False


def test_path_dirty_flags_modified_path(repo):
    (repo / "a.txt").write_text("changed")
    assert path_dirty(repo, repo / "a.txt") is True


def test_path_dirty_flags_untracked_path(repo):
    (repo / "b.txt").write_text("new")
    assert path_dirty(repo, repo / "b.txt") is True


def test_path_dirty_is_scoped_to_path(repo):
    # An unrelated dirty file elsewhere must not taint a clean artifact.
    (repo / "a.txt").write_text("changed")
    (repo / "clean.txt").write_text("x")
    _git(repo, "add", "clean.txt")
    _git(repo, "commit", "-q", "-m", "add clean")
    assert path_dirty(repo, repo / "clean.txt") is False


def test_path_dirty_outside_repo_is_false(tmp_path):
    assert path_dirty(tmp_path, tmp_path / "nope.txt") is False


@pytest.fixture
def repo_two_versions(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "T")
    f = r / "reports" / "r.md"
    f.parent.mkdir()
    f.write_text("v1\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "first")
    f.write_text("v2\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "second")
    return r


def test_file_history_newest_first(repo_two_versions):
    history = file_history(repo_two_versions, "reports/r.md")
    assert [h["subject"] for h in history] == ["second", "first"]
    assert all(len(h["sha"]) >= 7 and h["date"] for h in history)


def test_file_at_commit_returns_old_content(repo_two_versions):
    history = file_history(repo_two_versions, "reports/r.md")
    oldest = history[-1]["sha"]
    assert file_at_commit(repo_two_versions, oldest, "reports/r.md") == "v1\n"


def test_file_history_untracked_is_empty(repo_two_versions):
    assert file_history(repo_two_versions, "reports/nope.md") == []
