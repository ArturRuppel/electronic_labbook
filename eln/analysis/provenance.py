"""Record, in SDGL, how a derived file or curated artifact was produced.

Provenance is a **graph relationship, not file metadata** — the artifact on disk
is never touched. ``stamp()`` represents the artifact as a ``dataset`` node and
attaches the recipe (library + data-repo commits, function, parameters, input
content hashes) as metadata on a ``generates`` edge from the producing experiment
node. Both the node type and relation already exist in SDGL, so no schema change
is needed.

The graph stores only *references* — commit hashes, dotted function names,
parameter values, input fingerprints. Never source code, never anything
executable: the recipe itself lives in git, where it can be diffed and recovered.

``verify_provenance()`` re-hashes stamped artifacts on disk and flags any that
diverge from the hash recorded at stamp time (i.e. their last committed state).
"""

from __future__ import annotations

import os
import sqlite3
import warnings
from pathlib import Path

from eln.hashing import sha256_file
from eln.sdgl import SDGL
from eln.sdgl.engine import ID_FOLDER_RE, utcnow
from eln.analysis.gitref import head_commit, remote_url, repo_root

# The code repo's top level (this file is eln/analysis/provenance.py).
_LIBRARY_REPO_DIR = Path(__file__).resolve().parents[2]


def _resolve_root(root):
    if root is not None:
        return Path(root).resolve()
    from eln.config import load_config
    return load_config().data_root


def _rel_to(root, path):
    """Path of ``path`` relative to ``root`` (POSIX), or its abspath if outside."""
    abs = Path(path).resolve()
    try:
        return abs.relative_to(root).as_posix()
    except ValueError:
        return abs.as_posix()


def _function_name(function):
    """Accept a dotted string or a callable and return a dotted name string."""
    if function is None or isinstance(function, str):
        return function
    module = getattr(function, "__module__", None)
    qualname = getattr(function, "__qualname__", None) or getattr(function, "__name__", None)
    return f"{module}.{qualname}" if module and qualname else str(function)


def _infer_producer(rel_path):
    """Infer ``experiment:CODE-NN`` from a path component, or None."""
    for part in Path(rel_path).parts:
        if ID_FOLDER_RE.match(part):
            return "experiment:" + part
    return None


def _portable_rel(root, abs_path):
    """A machine-independent storage key for a filesystem artifact: its path
    relative to the enclosing ``CODE-NN`` experiment folder (``<CODE-NN>/<rest>``).

    This is what makes a *derived* artifact's key portable — the same string on
    every machine regardless of which drive the file sits on. Falls back to the
    data-root-relative path (or absolute) when no experiment folder is in the path.
    The real file is resolved back from this key through the scan index at verify
    time (:func:`verify_provenance`)."""
    parts = Path(abs_path).resolve().parts
    for i, part in enumerate(parts):
        if ID_FOLDER_RE.match(part):
            return "/".join(parts[i:])
    return _rel_to(root, abs_path)


def stamp(
    path,
    *,
    function=None,
    params=None,
    inputs=None,
    notebook=None,
    kind="derived",
    tool=None,
    method=None,
    produced_by=None,
    root=None,
    library_commit=None,
    data_commit=None,
):
    """Record provenance for the artifact at ``path`` and return the record.

    ``kind="derived"`` (default) records the library recipe (``function``,
    ``params``, input hashes) and the producing notebook. ``kind="curated"``
    records an irreproducible human-made artifact via ``tool``/``method`` and the
    data-repo commit of the file itself.

    The producing experiment node is inferred from a ``CODE-NN`` component of the
    path unless ``produced_by`` is given. Git commits are resolved automatically
    unless ``library_commit``/``data_commit`` override them.
    """
    if kind not in ("derived", "curated"):
        raise ValueError("kind must be 'derived' or 'curated'")

    root = _resolve_root(root)
    abs_path = Path(path).resolve()
    data_rel = _rel_to(root, abs_path)
    if not abs_path.exists():
        raise FileNotFoundError(f"artifact not found: {abs_path}")

    producer = produced_by or _infer_producer(data_rel)
    if not producer:
        raise ValueError(
            "could not infer the producing experiment from the path "
            f"({data_rel}); pass produced_by='experiment:CODE-NN'."
        )

    # Storage key. Curated artifacts are copied into the data repo, so their
    # data-root-relative path is already portable and resolvable in place. Derived
    # artifacts stay on the filesystem, so key them by the experiment-relative path
    # ('<CODE-NN>/<rest>') — machine-independent, resolved back to a real file via
    # the scan index at verify time.
    rel_path = data_rel if kind == "curated" else _portable_rel(root, abs_path)

    content_hash = sha256_file(abs_path)
    now = utcnow()

    # Data-repo commit (the data root is the data repo).
    if data_commit is None:
        data_commit, data_dirty = head_commit(root)
    else:
        data_dirty = False
    if data_dirty:
        warnings.warn(f"data repo has uncommitted changes when stamping {rel_path}")

    record = {
        "kind": kind,
        "path": rel_path,
        "content_hash": content_hash,
        "stamped_at": now,
    }

    if kind == "derived":
        if library_commit is None:
            library_commit, lib_dirty = head_commit(_LIBRARY_REPO_DIR)
        else:
            lib_dirty = False
        if lib_dirty:
            warnings.warn("library repo has uncommitted changes when stamping")

        input_hashes = {}
        for item in inputs or []:
            ip = Path(item).resolve()
            input_hashes[_portable_rel(root, ip)] = sha256_file(ip)

        record["library"] = {
            "repo": remote_url(_LIBRARY_REPO_DIR),
            "commit": library_commit,
            "function": _function_name(function),
            "dirty": lib_dirty,
        }
        record["notebook"] = {
            "repo": remote_url(root),
            "commit": data_commit,
            "path": notebook,
            "dirty": data_dirty,
        }
        record["params"] = params or {}
        record["inputs"] = input_hashes
    else:  # curated
        if not tool or not method:
            raise ValueError("curated artifacts require both tool and method")
        record["tool"] = tool
        record["method"] = method
        record["notebook"] = {
            "repo": remote_url(root),
            "commit": data_commit,
            "path": rel_path,
            "dirty": data_dirty,
        }

    # Write the node + generates edge in one transaction; best-effort derived_from
    # edges to any inputs that are themselves stamped dataset nodes.
    sdgl = SDGL(root)
    sdgl.initialize()
    conn = sdgl.connect()
    node_id = "dataset:" + rel_path
    try:
        sdgl.upsert_node(
            node_id, "dataset", title=abs_path.name,
            metadata={"rel_path": rel_path, "content_hash": content_hash, "kind": kind},
            conn=conn,
        )
        sdgl.upsert_edge(producer, node_id, "generates", record, conn=conn)
        for input_rel in record.get("inputs", {}):
            input_node = "dataset:" + input_rel
            exists = conn.execute(
                "SELECT 1 FROM nodes WHERE id = ?", (input_node,)
            ).fetchone()
            if exists:
                sdgl.upsert_edge(node_id, input_node, "derived_from", {}, conn=conn)
        conn.commit()
    finally:
        conn.close()

    # Persist the provenance subgraph to the committed, git-tracked form so the
    # stamp survives an sdgl.db rebuild (and reaches other machines via publish).
    from eln.sdgl.provenance_store import dump_provenance
    dump_provenance(sdgl)

    return record


def _external_hash(conn, rel_path):
    """Current hash of an external (on-filesystem) artifact, resolved through the
    scan index. The portable dataset key ``<EXP-ID>/<file-rel>`` maps to
    ``file_locations`` rows under ``experiment:<EXP-ID>``. Rides on the hash the
    scanner already recorded (so verification reflects the last scan); re-hashes
    on disk only when the scanner left it unhashed. ``None`` when no copy exists."""
    exp_id, _, file_rel = rel_path.partition("/")
    if not file_rel:
        return None
    rows = conn.execute(
        "SELECT path, content_hash, exists_now FROM file_locations "
        "WHERE node_id = ? AND rel_path = ? AND is_dir = 0",
        ("experiment:" + exp_id, file_rel),
    ).fetchall()
    for row in rows:
        if row["content_hash"]:
            return row["content_hash"]
    for row in rows:
        if row["exists_now"] and Path(row["path"]).exists():
            return sha256_file(row["path"])
    return None


def verify_provenance(root=None):
    """Check every stamped ``dataset`` artifact against its stamped fingerprint.

    Each entry is ``{"node_id", "path", "status"}`` where ``status`` is
    ``"modified"`` (current content differs from the stamped hash) or ``"missing"``
    (no copy found). Untouched artifacts are omitted. Curated artifacts live in the
    data repo and are re-hashed in place; derived artifacts live on the filesystem
    and are resolved — and their current hash taken — through the scan index.
    """
    root = _resolve_root(root)
    sdgl = SDGL(root)
    conn = sdgl.connect()
    try:
        try:
            rows = conn.execute(
                "SELECT id, metadata FROM nodes WHERE type = 'dataset'"
            ).fetchall()
        except sqlite3.OperationalError:
            return []  # sdgl.db has no nodes table yet → nothing stamped
        from eln.sdgl.engine import json_loads
        divergences = []
        for row in rows:
            meta = json_loads(row["metadata"])
            stored = meta.get("content_hash")
            rel_path = meta.get("rel_path")
            if not stored or not rel_path:
                continue  # not a stamped artifact (e.g. scanner-created node)
            in_repo = root / rel_path
            if in_repo.exists():
                current = sha256_file(in_repo)        # curated / in-repo
            else:
                current = _external_hash(conn, rel_path)  # derived / external
            if current is None:
                divergences.append({"node_id": row["id"], "path": rel_path, "status": "missing"})
            elif current != stored:
                divergences.append({"node_id": row["id"], "path": rel_path, "status": "modified"})
        return divergences
    finally:
        conn.close()
