import subprocess

import pytest

from eln.analysis import stamp, verify_provenance
from eln.sdgl import SDGL


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


@pytest.fixture
def data_repo(tmp_path):
    """A git-initialized data root with one derived artifact under SORVI-01."""
    root = tmp_path / "data"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "T")
    artifact = root / "SORVI-01" / "derived" / "tractions.npy"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"traction field")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "data")
    return root, artifact


def _incoming_generates(root, node_id):
    node = SDGL(root).get_node(node_id)
    return [e for e in node["incoming"] if e["relation_type"] == "generates"]


def test_stamp_derived_writes_node_and_edge(data_repo):
    root, artifact = data_repo
    inp = root / "SORVI-01" / "raw" / "beads.tif"
    inp.parent.mkdir(parents=True)
    inp.write_bytes(b"beadstack")

    record = stamp(
        artifact,
        function="eln.analysis.tfm.compute",
        params={"pixel_size": 0.65},
        inputs=[inp],
        notebook="notebooks/SORVI/01_compute.ipynb",
        root=root,
        library_commit="abc123",
        data_commit="def456",
    )

    assert record["kind"] == "derived"
    assert record["content_hash"].startswith("sha256:")
    assert record["library"]["function"] == "eln.analysis.tfm.compute"
    assert record["library"]["commit"] == "abc123"
    assert record["notebook"]["commit"] == "def456"
    assert record["params"] == {"pixel_size": 0.65}
    assert record["inputs"]["SORVI-01/raw/beads.tif"].startswith("sha256:")

    node = SDGL(root).get_node("dataset:SORVI-01/derived/tractions.npy")
    assert node is not None
    assert node["metadata"]["content_hash"] == record["content_hash"]

    edges = _incoming_generates(root, "dataset:SORVI-01/derived/tractions.npy")
    assert len(edges) == 1
    assert edges[0]["source_id"] == "experiment:SORVI-01"
    assert edges[0]["metadata"]["library"]["function"] == "eln.analysis.tfm.compute"


def test_stamp_infers_producer_from_path(data_repo):
    root, artifact = data_repo
    stamp(artifact, function="f", root=root, data_commit="x", library_commit="y")
    edges = _incoming_generates(root, "dataset:SORVI-01/derived/tractions.npy")
    assert edges[0]["source_id"] == "experiment:SORVI-01"


def test_stamp_requires_producer_when_uninferable(tmp_path):
    root = tmp_path / "d"
    root.mkdir()
    loose = root / "loose.npy"
    loose.write_bytes(b"x")
    with pytest.raises(ValueError, match="produced_by"):
        stamp(loose, function="f", root=root, data_commit="x", library_commit="y")


def test_stamp_curated_records_tool_method(data_repo):
    root, _ = data_repo
    seg = root / "SORVI-01" / "curated" / "seg.tif"
    seg.parent.mkdir(parents=True)
    seg.write_bytes(b"hand drawn")
    record = stamp(
        seg, kind="curated", tool="napari", method="manual segmentation",
        root=root, data_commit="def456",
    )
    assert record["kind"] == "curated"
    assert record["tool"] == "napari"
    assert record["method"] == "manual segmentation"
    assert "library" not in record and "inputs" not in record
    assert record["notebook"]["commit"] == "def456"


def test_stamp_curated_requires_tool_and_method(data_repo):
    root, _ = data_repo
    seg = root / "SORVI-01" / "curated" / "seg.tif"
    seg.parent.mkdir(parents=True)
    seg.write_bytes(b"x")
    with pytest.raises(ValueError, match="tool and method"):
        stamp(seg, kind="curated", root=root, data_commit="x")


def test_stamp_links_derived_from_when_input_stamped(data_repo):
    root, artifact = data_repo
    inp = root / "SORVI-01" / "derived" / "intermediate.npy"
    inp.write_bytes(b"intermediate")
    # Stamp the input first so it exists as a dataset node.
    stamp(inp, function="f", root=root, data_commit="x", library_commit="y")
    stamp(artifact, function="g", inputs=[inp], root=root,
          data_commit="x", library_commit="y")

    node = SDGL(root).get_node("dataset:SORVI-01/derived/tractions.npy")
    derived = [e for e in node["outgoing"] if e["relation_type"] == "derived_from"]
    assert any(e["target_id"] == "dataset:SORVI-01/derived/intermediate.npy" for e in derived)


def test_stamp_auto_resolves_data_commit(data_repo):
    root, artifact = data_repo
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    record = stamp(artifact, function="f", root=root, library_commit="y")
    assert record["notebook"]["commit"] == head


# --- verification -----------------------------------------------------------

def test_verify_clean_after_stamp(data_repo):
    root, artifact = data_repo
    stamp(artifact, function="f", root=root, data_commit="x", library_commit="y")
    assert verify_provenance(root) == []


def test_verify_flags_modified(data_repo):
    root, artifact = data_repo
    stamp(artifact, function="f", root=root, data_commit="x", library_commit="y")
    artifact.write_bytes(b"tampered")
    result = verify_provenance(root)
    assert result == [{
        "node_id": "dataset:SORVI-01/derived/tractions.npy",
        "path": "SORVI-01/derived/tractions.npy",
        "status": "modified",
    }]


def test_verify_flags_missing(data_repo):
    root, artifact = data_repo
    stamp(artifact, function="f", root=root, data_commit="x", library_commit="y")
    artifact.unlink()
    result = verify_provenance(root)
    assert result[0]["status"] == "missing"
