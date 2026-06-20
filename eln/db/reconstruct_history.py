#!/usr/bin/env python3
"""One-time migration: replay binary experiments.db history into diffable
experiments.sql commits in the data repo.

For every commit in the SOURCE repo that changed the tracked binary database, we
extract that blob, run the deterministic dump_db over it, write experiments.sql
into the TARGET repo, and commit — preserving the original author, author date,
and message. The result is a clean, line-level history equivalent to the opaque
binary history, without carrying any binary blobs forward. (sdgl.db history is
intentionally discarded — it is a build artifact.)

Commits whose binary produced an SQL dump identical to the previous one (e.g. a
vacuum or a timestamp-only change) are skipped, so the reconstructed history
records only semantic changes.

Run once during the migration to the diffable history. Example:

    python -m eln.db.reconstruct_history \
        --source-repo /home/aruppel/Data/electronic_labbook \
        --db-path data/experiments.db \
        --target-repo /home/aruppel/Projects/electronic_labbook_database

Use --dry-run first to preview what would be committed.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import DEFAULT_SQL_NAME, dump_db


def _git(repo: Path, *args: str, capture: bool = True, env: dict | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        capture_output=capture,
        env=env,
    )
    return result.stdout.strip() if capture else ""


def _commits_touching(source: Path, db_path: str) -> list[str]:
    """Hashes (oldest first) of commits that changed db_path."""
    out = _git(source, "log", "--reverse", "--format=%H", "--", db_path)
    return [h for h in out.splitlines() if h]


def _meta(source: Path, commit: str) -> dict:
    """Author identity/date and full message for a commit."""
    sep = "\x1f"
    fmt = sep.join(["%an", "%ae", "%aI", "%cn", "%ce", "%B"])
    raw = _git(source, "show", "-s", f"--format={fmt}", commit)
    an, ae, ai, cn, ce, body = raw.split(sep, 5)
    return {"an": an, "ae": ae, "ai": ai, "cn": cn, "ce": ce, "body": body}


def reconstruct(
    source: Path,
    db_path: str,
    target: Path,
    sql_name: str = DEFAULT_SQL_NAME,
    dry_run: bool = False,
) -> dict:
    source, target = Path(source), Path(target)
    sql_out = target / sql_name

    commits = _commits_touching(source, db_path)
    stats = {"total": len(commits), "committed": 0, "skipped_identical": 0, "errors": 0}

    with tempfile.TemporaryDirectory() as td:
        tmp_db = Path(td) / "snapshot.db"
        for commit in commits:
            short = commit[:9]
            # Extract the binary blob at this commit.
            try:
                blob = subprocess.run(
                    ["git", "-C", str(source), "show", f"{commit}:{db_path}"],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError:
                print(f"  ! {short}: could not read {db_path}; skipping")
                stats["errors"] += 1
                continue
            tmp_db.write_bytes(blob.stdout)

            # Dump it deterministically over the target's experiments.sql.
            try:
                dump_db.dump(tmp_db, sql_out)
            except Exception as exc:  # not a valid sqlite snapshot, etc.
                print(f"  ! {short}: dump failed ({exc}); skipping")
                stats["errors"] += 1
                continue

            meta = _meta(source, commit)

            if dry_run:
                first_line = meta["body"].splitlines()[0] if meta["body"] else ""
                print(f"  · {short} {meta['ai'][:10]} {meta['an']} | {first_line}")
                continue

            # Stage and detect whether the SQL actually changed.
            _git(target, "add", sql_name)
            changed = subprocess.run(
                ["git", "-C", str(target), "diff", "--cached", "--quiet"]
            ).returncode  # 0 == no change, 1 == change
            if changed == 0:
                print(f"  = {short}: SQL identical to previous; skipping")
                stats["skipped_identical"] += 1
                continue

            message = meta["body"].rstrip() + (
                f"\n\nReconstructed from {db_path} @ {commit} "
                f"(original binary history)."
            )
            env = {
                **os.environ,
                "GIT_AUTHOR_NAME": meta["an"],
                "GIT_AUTHOR_EMAIL": meta["ae"],
                "GIT_AUTHOR_DATE": meta["ai"],
                # Keep committer date coherent with author date.
                "GIT_COMMITTER_NAME": meta["cn"],
                "GIT_COMMITTER_EMAIL": meta["ce"],
                "GIT_COMMITTER_DATE": meta["ai"],
            }
            _git(target, "commit", "-q", "-m", message, capture=False, env=env)
            stats["committed"] += 1
            print(f"  + {short} {meta['ai'][:10]} | {meta['body'].splitlines()[0]}")

    return stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source-repo", required=True, help="old in-place repo with the binary DB history")
    p.add_argument("--db-path", default="data/experiments.db", help="binary DB path within the source repo")
    p.add_argument("--target-repo", required=True, help="data repo to receive experiments.sql commits")
    p.add_argument("--sql-name", default=DEFAULT_SQL_NAME, help="output SQL filename in the target repo")
    p.add_argument("--dry-run", action="store_true", help="preview commits without writing")
    args = p.parse_args(argv)

    source = Path(args.source_repo).resolve()
    target = Path(args.target_repo).resolve()
    if not (source / ".git").exists():
        p.error(f"not a git repo: {source}")
    if not (target / ".git").exists():
        p.error(f"not a git repo: {target}")

    print(f"Reconstructing {args.db_path} history: {source} -> {target}")
    stats = reconstruct(source, args.db_path, target, args.sql_name, args.dry_run)
    print(
        f"\nDone. {stats['total']} DB commits | "
        f"{stats['committed']} committed | "
        f"{stats['skipped_identical']} identical-skipped | "
        f"{stats['errors']} errors"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
