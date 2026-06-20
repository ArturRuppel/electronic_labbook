"""Publish flow for the data repo.

Unlike the original monorepo (which committed the binary ``data/experiments.db``),
the clean-rebuild publish materializes the database into its diffable form —
``experiments.sql`` via :func:`eln.db.dump` — and commits *that* to the **data**
repo, then pushes. The static ``catalog/`` is intentionally not committed: GitLab
CI rebuilds it from ``experiments.sql`` on every Pages build.
"""

import subprocess
from datetime import datetime
from pathlib import Path

from eln.db.dump_db import dump
from eln.sdgl import allocate_experiment_codes

# Tracked, diffable data committed on publish. The binary experiments.db / sdgl.db
# are build artifacts and stay gitignored in the data repo. ``curated/`` holds
# hand-made artifacts copied in via the Commit flow — versioned like code.
PUBLISH_PATHS = ["experiments.sql", "provenance.json", "reports", "presentations",
                 "thumbnails", "timestamps", "curated"]

# Reject any single staged file above this size so committing bulk media to git
# stays sustainable (large data belongs in the backup flow, not git history).
MAX_STAGED_BYTES = 90 * 1024 * 1024


def _git(args, cwd):
    """Run a git command in ``cwd``; returns the CompletedProcess (no check)."""
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )


def _oversized_staged(root):
    """Return ``[(path, size_bytes)]`` for staged files above MAX_STAGED_BYTES."""
    out = _git(["diff", "--cached", "--name-only"], cwd=root)
    offenders = []
    for name in out.stdout.split("\n"):
        name = name.strip()
        if not name:
            continue
        f = Path(root) / name
        if f.exists() and f.stat().st_size > MAX_STAGED_BYTES:
            offenders.append((name, f.stat().st_size))
    return offenders


def _repo_size_bytes(root):
    """Approximate the git repo's packed object size in bytes."""
    out = _git(["count-objects", "-v"], cwd=root)
    for line in out.stdout.splitlines():
        if line.startswith("size-pack:"):
            return int(line.split()[1]) * 1024  # KiB -> bytes
    return 0


def publish(root, eln_db_path=None, *, push=True, remote="origin", branch="main",
            timestamp_cfg=None):
    """Materialize → dump → commit → push the data repo at ``root``.

    Returns a result dict with ``success``/``message`` (and, on git failure,
    ``error``) mirroring the original endpoint's contract. Raises only on a
    missing database (a programmer/config error, not a publish-time condition).
    """
    root = Path(root)
    db_path = Path(eln_db_path) if eln_db_path else root / "experiments.db"
    if not db_path.exists():
        return {"error": f"Database not found: {db_path}"}

    # 1. Materialize derived identifiers (CODE-NN) before dumping; dates stay
    #    derived from raw-file mtimes at generation time and need no materializing.
    allocate_experiment_codes(db_path)

    # 2. Dump the database to its diffable form inside the data repo.
    dump(db_path, root / "experiments.sql")

    # 2b. Best-effort trusted timestamp over the snapshot (RFC 3161 layer).
    #     A TSA failure records a "pending" entry but never blocks the
    #     publish; the token/manifest/index land under timestamps/ (in
    #     PUBLISH_PATHS) and are committed with the rest below.
    if timestamp_cfg and timestamp_cfg.get("enabled", True):
        from eln import timestamp as _ts
        _ts.create_timestamp(root, timestamp_cfg["paths"], timestamp_cfg)

    # 3. Stage the diffable data that actually exists.
    paths = [p for p in PUBLISH_PATHS if (root / p).exists()]
    add = _git(["add", *paths], cwd=root)
    if add.returncode != 0:
        return {"error": f"Publish failed: {add.stderr.strip() or 'git add failed'}"}

    # 3b. Guardrail: refuse to commit oversized blobs into git history.
    offenders = _oversized_staged(root)
    if offenders:
        listed = ", ".join(f"{n} ({s // (1024 * 1024)} MB)" for n, s in offenders)
        repo_mb = _repo_size_bytes(root) // (1024 * 1024)
        _git(["reset"], cwd=root)  # un-stage so the working tree is left clean
        return {
            "error": (
                f"Publish blocked: staged file(s) exceed 90 MB: {listed}. "
                f"Move large media out of git (repo pack size ~{repo_mb} MB)."
            )
        }

    # 4. Nothing staged → nothing to publish.
    if _git(["diff", "--cached", "--quiet"], cwd=root).returncode == 0:
        return {"success": True, "message": "Nothing to publish (no changes detected)"}

    # 5. Commit.
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    commit = _git(["commit", "-m", f"Update lab notebook ({timestamp})"], cwd=root)
    if commit.returncode != 0:
        return {"error": f"Publish failed: {commit.stderr.strip() or 'git commit failed'}"}

    # 6. Push (best-effort: a committed-but-unpushed state is recoverable).
    if not push:
        return {"success": True, "message": "Committed locally (push skipped)."}

    pushed = _git(["push", remote, branch], cwd=root)
    if pushed.returncode != 0:
        return {
            "success": True,
            "message": (
                f"Committed but push failed: {pushed.stderr.strip()}. "
                f"Push manually with: git push {remote} {branch}"
            ),
        }
    return {"success": True, "message": "Published successfully! Changes committed and pushed."}
