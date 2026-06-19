import subprocess

import pytest

from eln.analysis.gitref import head_commit, remote_url, repo_root


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
