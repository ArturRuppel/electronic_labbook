"""Resolve git facts for provenance stamps, tolerant of non-repo paths.

``stamp()`` records which commit of the library repo and the data repo produced
an artifact. These helpers shell out to git the same way the rest of the codebase
does (see ``eln/server/publish.py``), and degrade gracefully — outside a checkout
they return ``None`` so a notebook run from a loose directory still stamps (just
without a commit), rather than crashing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(repo_dir, *args):
    """Run a git command in ``repo_dir``; return stripped stdout or None on error."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), *args],
            capture_output=True, text=True,
        )
    except (OSError, ValueError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def head_commit(repo_dir):
    """Return ``(commit_sha, dirty)`` for ``repo_dir``'s HEAD.

    ``dirty`` is True when the working tree has uncommitted changes (so a stamp
    can warn that the recorded commit doesn't fully describe the on-disk state).
    Returns ``(None, False)`` when ``repo_dir`` isn't inside a git repository.
    """
    commit = _git(repo_dir, "rev-parse", "HEAD")
    if commit is None:
        return None, False
    status = _git(repo_dir, "status", "--porcelain")
    return commit, bool(status)


def path_dirty(repo_dir, path):
    """Return True if ``path`` has uncommitted changes in ``repo_dir`` right now.

    Scopes ``git status`` to the single path, so an unrelated dirty file elsewhere
    in the repo doesn't taint this artifact — unlike :func:`head_commit`, which
    measures the whole working tree. False when the path is clean, ignored, or
    ``repo_dir`` isn't a git repository (``_git`` returns None on error).
    """
    status = _git(repo_dir, "status", "--porcelain", "--", str(path))
    return bool(status)


def repo_root(path):
    """Return the absolute top-level of the repo containing ``path``, or None.

    A file path is resolved against its parent directory so callers can pass the
    artifact path directly.
    """
    p = Path(path)
    start = p if p.is_dir() else p.parent
    top = _git(start, "rev-parse", "--show-toplevel")
    return Path(top).resolve() if top else None


def remote_url(repo_dir):
    """Return the ``origin`` fetch URL of ``repo_dir``, or None if unset."""
    return _git(repo_dir, "config", "--get", "remote.origin.url") or None
