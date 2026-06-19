"""Publish flow for the data repo.

Unlike the original monorepo (which committed the binary ``data/experiments.db``),
the clean-rebuild publish materializes the database into its diffable form —
``experiments.sql`` via :func:`eln.db.dump` — and commits *that* to the **data**
repo, then pushes. The static ``catalog/`` is intentionally not committed: GitLab
CI rebuilds it from ``experiments.sql`` on every Pages build (see ROADMAP step 7).
"""

import subprocess
from datetime import datetime
from pathlib import Path

from eln.db.dump_db import dump
from eln.sdgl import allocate_experiment_codes

# Tracked, diffable data committed on publish. The binary experiments.db / sdgl.db
# are build artifacts and stay gitignored in the data repo.
PUBLISH_PATHS = ["experiments.sql", "reports", "presentations", "thumbnails"]


def _git(args, cwd):
    """Run a git command in ``cwd``; returns the CompletedProcess (no check)."""
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )


def publish(root, eln_db_path=None, *, push=True, remote="origin", branch="main"):
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

    # 3. Stage the diffable data that actually exists.
    paths = [p for p in PUBLISH_PATHS if (root / p).exists()]
    add = _git(["add", *paths], cwd=root)
    if add.returncode != 0:
        return {"error": f"Publish failed: {add.stderr.strip() or 'git add failed'}"}

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
