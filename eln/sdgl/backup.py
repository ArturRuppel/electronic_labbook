"""Selectable data backup (Roadmap step 8).

Copies the identified raw+derived files tracked in SDGL's ``file_locations`` to a
user-chosen destination, organized by experiment CODE. Duplicate sightings of one
logical file are deduped by content hash: identical copies collapse to one,
differing copies are surfaced as a conflict for the user to resolve.
"""

import hashlib
import os
import shutil
import threading
from pathlib import Path

CHUNK = 1024 * 1024


def hash_file(path, chunk=CHUNK):
    """Stream a file's SHA-256 so large media never load fully into memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def dest_subpath(node_id):
    """Destination folder for a node, organized by CODE (over mirroring source paths).

    ``experiment:TFMSP-01`` -> ``TFMSP/TFMSP-01``; an excluded session keeps its
    own ``COV2D-X03`` folder; ``aggregate_analysis:TFMSP`` -> ``TFMSP/TFMSP_aggregate``.
    """
    kind, _, suffix = node_id.partition(":")
    if kind == "aggregate_analysis":
        return Path(suffix) / f"{suffix}_aggregate"
    code = suffix.split("-", 1)[0]
    return Path(code) / suffix


def resolve_logical_files(conn, selections):
    """Map each ``{node_id, rel_path}`` selection to its file rows.

    Returns ``{(node_id, rel_path): [row, ...]}`` over file rows only (is_dir=0),
    deduped by ``location.id`` so overlapping selections never double-count a
    physical copy. ``rel_path == ''`` selects the whole node; a folder rel_path
    selects its subtree; a file rel_path selects exactly that file.
    """
    logical = {}
    for sel in selections:
        node_id = sel["node_id"]
        prefix = sel.get("rel_path") or ""
        rows = conn.execute(
            "SELECT * FROM file_locations WHERE node_id = ? AND is_dir = 0",
            (node_id,),
        ).fetchall()
        for row in rows:
            rel = row["rel_path"] or ""
            if prefix and not (rel == prefix or rel.startswith(prefix + os.sep)):
                continue
            by_id = logical.setdefault((node_id, rel), {})
            by_id[row["id"]] = row
    return {key: list(by_id.values()) for key, by_id in logical.items()}


def classify(copies):
    """Decide how to back up one logical file given its physical copies.

    Returns one of:
      {"status": "ok", "chosen": row}           — copy this row
      {"status": "missing"}                       — no copy exists on disk
      {"status": "conflict", "copies": [rows]}    — copies differ; user must pick
    Identical-content duplicates collapse silently (newest mtime wins, matching
    the tree's dedup); only same-rel-path copies with differing content conflict.
    """
    existing = [c for c in copies if c["exists_now"] and Path(c["path"]).exists()]
    if not existing:
        return {"status": "missing"}
    if len(existing) == 1:
        return {"status": "ok", "chosen": existing[0]}
    by_hash = {}
    for copy in existing:
        by_hash.setdefault(hash_file(copy["path"]), []).append(copy)
    if len(by_hash) == 1:
        chosen = max(existing, key=lambda c: c["mtime"] or 0)
        return {"status": "ok", "chosen": chosen}
    return {"status": "conflict", "copies": existing}


def plan_backup(conn, selections):
    """Resolve selections into a copy preview: file count, total bytes, and the
    missing / conflicting files the user must know about before copying."""
    logical = resolve_logical_files(conn, selections)
    ok, missing, conflicts = [], [], []
    total_size = 0
    for (node_id, rel), copies in logical.items():
        result = classify(copies)
        if result["status"] == "ok":
            chosen = result["chosen"]
            total_size += chosen["size"] or 0
            ok.append({"node_id": node_id, "rel_path": rel,
                       "location_id": chosen["id"], "size": chosen["size"]})
        elif result["status"] == "missing":
            missing.append({"node_id": node_id, "rel_path": rel})
        else:
            conflicts.append({
                "node_id": node_id,
                "rel_path": rel,
                "copies": [
                    {"location_id": c["id"], "path": c["path"],
                     "root_name": c["root_name"], "size": c["size"], "mtime": c["mtime"]}
                    for c in result["copies"]
                ],
            })
    return {
        "file_count": len(ok),
        "total_size": total_size,
        "ok": ok,
        "missing": missing,
        "conflicts": conflicts,
    }
