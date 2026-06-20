"""The Commit endpoint: curated artifacts are copied into the data repo and
stamped; derived artifacts are recorded by reference only."""

import sqlite3

import pytest

from eln.db import init_db
from eln.sdgl import SDGL
from eln.server import create_app


@pytest.fixture
def stamp_app(tmp_path):
    """A data repo (tmp_path/repo) whose graph points at an external artifact
    living outside the repo, under a TFMSP-01 experiment folder."""
    root = tmp_path / "repo"
    root.mkdir()
    init_db.init_db(root / "experiments.db")

    sdgl = SDGL(root)
    node_id = "experiment:TFMSP-01"
    sdgl.upsert_node(node_id, "experiment", "TFM", None, None, {"code": "TFMSP"})
    ext = tmp_path / "drive" / "TFMSP-01" / "curated" / "seg.tif"
    ext.parent.mkdir(parents=True)
    ext.write_bytes(b"hand drawn mask")
    st = ext.stat()
    sdgl.upsert_location(node_id, "drive", str(ext), role="file",
                         rel_path="curated/seg.tif", size=st.st_size,
                         mtime=st.st_mtime, is_dir=0, metadata={"name": "seg.tif"})

    app = create_app(root, scan_roots=[{"name": "drive", "path": tmp_path / "drive"}])
    app.config.update(TESTING=True)
    return root, app, node_id


def _post(app, **body):
    return app.test_client().post("/api/sdgl/provenance/stamp", json=body)


def test_commit_curated_copies_into_repo_and_stamps(stamp_app):
    root, app, node_id = stamp_app
    resp = _post(app, selections=[{"node_id": node_id, "rel_path": "curated/seg.tif"}],
                 kind="curated", tool="napari", method="manual segmentation")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 1
    assert data["stamped"] == ["curated/TFMSP-01/curated/seg.tif"]

    # The file is copied into the data repo, preserving <EXPERIMENT-ID>/<rel>.
    copied = root / "curated" / "TFMSP-01" / "curated" / "seg.tif"
    assert copied.read_bytes() == b"hand drawn mask"

    # The committed copy carries a dataset node + generates edge with the recipe.
    conn = sqlite3.connect(str(root / "sdgl.db"))
    node = conn.execute("SELECT 1 FROM nodes WHERE id = ?",
                        ("dataset:curated/TFMSP-01/curated/seg.tif",)).fetchone()
    edge = conn.execute(
        "SELECT metadata FROM edges WHERE source_id = ? AND relation_type = 'generates'",
        (node_id,)).fetchone()
    conn.close()
    assert node is not None and edge is not None
    assert '"tool": "napari"' in edge[0]


def test_commit_curated_requires_tool_and_method(stamp_app):
    root, app, node_id = stamp_app
    resp = _post(app, selections=[{"node_id": node_id, "rel_path": "curated/seg.tif"}],
                 kind="curated")  # no tool/method
    assert resp.status_code == 400
    assert "tool and method" in resp.get_json()["error"]
    assert not (root / "curated").exists()  # rejected up front; nothing copied


def test_commit_derived_records_by_reference_no_copy(stamp_app):
    root, app, node_id = stamp_app
    resp = _post(app, selections=[{"node_id": node_id, "rel_path": "curated/seg.tif"}],
                 kind="derived", function="mylib.run")
    assert resp.status_code == 200
    assert resp.get_json()["count"] == 1
    # Derived artifacts are NOT copied into the repo (reference only).
    assert not (root / "curated").exists()


def test_commit_no_selections_is_400(stamp_app):
    root, app, node_id = stamp_app
    resp = _post(app, selections=[], kind="curated")
    assert resp.status_code == 400
