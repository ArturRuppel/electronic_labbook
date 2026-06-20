"""Durable, git-committed form of the provenance subgraph.

The SDGL graph (``sdgl.db``) is a rebuildable build artifact: scanning recreates
the scanned nodes, but the *provenance* a human or notebook records via
``stamp()`` — ``dataset`` nodes and ``generates`` / ``derived_from`` edges — is
not derivable from the filesystem and would be lost on rebuild.

This module mirrors the ``experiments.db`` ↔ ``experiments.sql`` pattern for that
subgraph: :func:`dump_provenance` writes it to a tracked, line-diffable
``provenance.json`` in the data repo (committed on publish), and
:func:`load_provenance` replays it back into ``sdgl.db`` after a rebuild.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

PROVENANCE_FILE = "provenance.json"

# The graph this store owns. ``dataset`` nodes and these two relations are the
# only graph content created by stamping (never by scanning), so they round-trip
# cleanly without colliding with the scanner.
_NODE_TYPES = ("dataset",)
_EDGE_RELATIONS = ("generates", "derived_from")


def _meta(value):
    return json.loads(value) if value else None


def dump_provenance(sdgl):
    """Write the provenance subgraph of ``sdgl`` to ``<root>/provenance.json``.

    Deterministic (sorted, indented) so commits diff cleanly. Returns the path.
    When the subgraph is empty, any stale file is removed rather than left behind.
    """
    path = Path(sdgl.root_path) / PROVENANCE_FILE
    conn = sdgl.connect()
    try:
        node_q = "SELECT id, type, title, description, experiment_id, metadata FROM nodes WHERE type IN ({})".format(
            ",".join("?" * len(_NODE_TYPES)))
        edge_q = "SELECT source_id, target_id, relation_type, metadata FROM edges WHERE relation_type IN ({})".format(
            ",".join("?" * len(_EDGE_RELATIONS)))
        try:
            node_rows = conn.execute(node_q, _NODE_TYPES).fetchall()
            edge_rows = conn.execute(edge_q, _EDGE_RELATIONS).fetchall()
        except sqlite3.OperationalError:
            node_rows, edge_rows = [], []  # graph schema not created yet
    finally:
        conn.close()

    nodes = sorted((
        {"id": r["id"], "type": r["type"], "title": r["title"],
         "description": r["description"], "experiment_id": r["experiment_id"],
         "metadata": _meta(r["metadata"])}
        for r in node_rows), key=lambda n: n["id"])
    edges = sorted((
        {"source_id": r["source_id"], "target_id": r["target_id"],
         "relation_type": r["relation_type"], "metadata": _meta(r["metadata"])}
        for r in edge_rows),
        key=lambda e: (e["source_id"], e["relation_type"], e["target_id"]))

    if not nodes and not edges:
        if path.exists():
            path.unlink()
        return path
    path.write_text(json.dumps({"nodes": nodes, "edges": edges},
                               indent=2, sort_keys=True) + "\n")
    return path


def load_provenance(sdgl):
    """Replay ``<root>/provenance.json`` into ``sdgl``'s graph. Idempotent (upsert).

    Returns the number of nodes loaded; 0 when the file is absent. Safe to call on
    a freshly rebuilt ``sdgl.db`` — the schema is ensured first.
    """
    path = Path(sdgl.root_path) / PROVENANCE_FILE
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return 0

    sdgl.initialize()
    conn = sdgl.connect()
    try:
        for node in payload.get("nodes", []):
            sdgl.upsert_node(
                node["id"], node["type"], title=node.get("title"),
                description=node.get("description"),
                experiment_id=node.get("experiment_id"),
                metadata=node.get("metadata"), conn=conn,
            )
        for edge in payload.get("edges", []):
            sdgl.upsert_edge(
                edge["source_id"], edge["target_id"], edge["relation_type"],
                edge.get("metadata"), conn=conn,
            )
        conn.commit()
    finally:
        conn.close()
    return len(payload.get("nodes", []))
