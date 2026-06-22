"""Stamped artifacts surface as a distinct per-repetition list in tree()."""

import subprocess

from eln.analysis import stamp
from eln.sdgl import SDGL


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def _experiment_node(sdgl, code="SORVI", rep=1):
    conn = sdgl.connect()
    sdgl.upsert_node(
        f"experiment:{code}-0{rep}", "experiment",
        metadata={"code": code, "experiment_id": f"{code}-0{rep}",
                  "repetition": rep, "excluded": False},
        conn=conn,
    )
    conn.commit()
    conn.close()


def test_tree_surfaces_stamped_artifacts(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    sdgl = SDGL(root)
    sdgl.initialize()
    _experiment_node(sdgl)

    art = root / "SORVI-01" / "derived" / "tractions.npy"
    art.parent.mkdir(parents=True)
    art.write_bytes(b"field")
    stamp(art, function="eln.analysis.tfm.compute", params={"pixel_size": 0.65},
          root=root, data_commit="x", library_commit="y")

    data = sdgl.tree()
    group = next(g for g in data["experiments"] if g["code"] == "SORVI")
    rep = group["repetitions"][0]

    assert len(rep["artifacts"]) == 1
    artifact = rep["artifacts"][0]
    assert artifact["kind"] == "derived"
    assert artifact["rel_path"] == "SORVI-01/derived/tractions.npy"
    assert artifact["record"]["library"]["function"] == "eln.analysis.tfm.compute"
    assert artifact["record"]["params"] == {"pixel_size": 0.65}

    # The artifact is NOT duplicated as a generic linked entity.
    assert all(link["node_id"] != artifact["node_id"] for link in rep["links"])


def test_curated_dirty_is_recomputed_live_against_head(tmp_path):
    # A curated artifact is stamped while its just-copied file makes the repo
    # dirty (so the recorded flag is True), then committed. tree() must report it
    # clean — the dirty flag is a live, path-scoped property, not the frozen one.
    root = tmp_path / "data"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "T")
    (root / "README.md").write_text("data repo")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")

    sdgl = SDGL(root)
    sdgl.initialize()
    _experiment_node(sdgl)

    art = root / "curated" / "SORVI-01" / "figure.png"
    art.parent.mkdir(parents=True)
    art.write_bytes(b"image")
    record = stamp(art, kind="curated", produced_by="experiment:SORVI-01",
                   root=root, tool="ImageJ", method="threshold")
    # Curated stamps persist no whole-repo dirty flag (it would always be True, as
    # the just-copied file dirties the tree); dirtiness is recomputed live below.
    assert record["notebook"]["dirty"] is False

    # Commit the curated artifact (and the provenance store) like the real flow.
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "commit curated")

    data = sdgl.tree()
    group = next(g for g in data["experiments"] if g["code"] == "SORVI")
    artifact = group["repetitions"][0]["artifacts"][0]
    assert artifact["kind"] == "curated"
    assert artifact["record"]["notebook"]["dirty"] is False

    # Re-dirty just the artifact and it flips back to dirty.
    art.write_bytes(b"edited")
    artifact = sdgl.tree()["experiments"][0]["repetitions"][0]["artifacts"][0]
    assert artifact["record"]["notebook"]["dirty"] is True


def test_tree_no_artifacts_when_nothing_stamped(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    sdgl = SDGL(root)
    sdgl.initialize()
    _experiment_node(sdgl)

    data = sdgl.tree()
    rep = data["experiments"][0]["repetitions"][0]
    assert rep["artifacts"] == []
