"""Provenance survives an sdgl.db rebuild via the committed provenance.json."""

import json

from eln.sdgl import SDGL
from eln.sdgl.provenance_store import (
    PROVENANCE_FILE,
    dump_provenance,
    load_provenance,
)


def _seed(sdgl):
    conn = sdgl.connect()
    sdgl.upsert_node("experiment:SORVI-01", "experiment",
                     metadata={"code": "SORVI"}, conn=conn)
    sdgl.upsert_node(
        "dataset:curated/SORVI-01/seg.tif", "dataset", title="seg.tif",
        metadata={"rel_path": "curated/SORVI-01/seg.tif",
                  "content_hash": "sha256:abc", "kind": "curated"}, conn=conn)
    sdgl.upsert_edge("experiment:SORVI-01", "dataset:curated/SORVI-01/seg.tif",
                     "generates", {"kind": "curated", "tool": "napari"}, conn=conn)
    conn.commit()
    conn.close()


def test_dump_writes_only_provenance_subgraph(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    sdgl = SDGL(root)
    _seed(sdgl)

    path = dump_provenance(sdgl)
    assert path.name == PROVENANCE_FILE
    payload = json.loads(path.read_text())
    # Dataset node + generates edge are captured; the experiment node is NOT
    # (it is rebuilt by scanning, so it doesn't belong in the committed file).
    assert [n["id"] for n in payload["nodes"]] == ["dataset:curated/SORVI-01/seg.tif"]
    assert payload["edges"][0]["relation_type"] == "generates"
    assert payload["edges"][0]["metadata"]["tool"] == "napari"


def test_load_restores_after_rebuild(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    sdgl = SDGL(root)
    _seed(sdgl)
    dump_provenance(sdgl)

    # Simulate a from-scratch rebuild: drop sdgl.db entirely.
    for suffix in ("", "-wal", "-shm"):
        p = root / ("sdgl.db" + suffix)
        if p.exists():
            p.unlink()

    rebuilt = SDGL(root)
    assert rebuilt.get_node("dataset:curated/SORVI-01/seg.tif") is None  # gone
    loaded = load_provenance(rebuilt)
    assert loaded == 1
    node = rebuilt.get_node("dataset:curated/SORVI-01/seg.tif")
    assert node is not None
    assert node["metadata"]["kind"] == "curated"


def test_scan_replays_committed_provenance(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / PROVENANCE_FILE).write_text(json.dumps({
        "nodes": [{"id": "dataset:curated/SORVI-01/seg.tif", "type": "dataset",
                   "title": "seg.tif", "description": None, "experiment_id": None,
                   "metadata": {"rel_path": "curated/SORVI-01/seg.tif",
                                "content_hash": "sha256:abc", "kind": "curated"}}],
        "edges": [{"source_id": "experiment:SORVI-01",
                   "target_id": "dataset:curated/SORVI-01/seg.tif",
                   "relation_type": "generates", "metadata": {"kind": "curated"}}],
    }))
    sdgl = SDGL(root)  # fresh sdgl.db, no dataset nodes
    assert sdgl.get_node("dataset:curated/SORVI-01/seg.tif") is None
    sdgl.scan_roots([])  # a scan ends by replaying committed provenance
    assert sdgl.get_node("dataset:curated/SORVI-01/seg.tif") is not None


def test_stamp_auto_dumps_provenance(tmp_path):
    from eln.analysis import stamp
    root = tmp_path / "repo"
    root.mkdir()
    art = root / "SORVI-01" / "derived" / "x.npy"
    art.parent.mkdir(parents=True)
    art.write_bytes(b"data")
    stamp(art, function="f", root=root, data_commit="x", library_commit="y")

    payload = json.loads((root / PROVENANCE_FILE).read_text())
    assert [n["id"] for n in payload["nodes"]] == ["dataset:SORVI-01/derived/x.npy"]


def test_dump_removes_stale_file_when_empty(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    stale = root / PROVENANCE_FILE
    stale.write_text('{"nodes": [], "edges": []}')
    sdgl = SDGL(root)  # no provenance in the graph
    dump_provenance(sdgl)
    assert not stale.exists()
