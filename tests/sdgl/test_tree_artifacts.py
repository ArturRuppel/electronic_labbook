"""Stamped artifacts surface as a distinct per-repetition list in tree()."""

from eln.analysis import stamp
from eln.sdgl import SDGL


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


def test_tree_no_artifacts_when_nothing_stamped(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    sdgl = SDGL(root)
    sdgl.initialize()
    _experiment_node(sdgl)

    data = sdgl.tree()
    rep = data["experiments"][0]["repetitions"][0]
    assert rep["artifacts"] == []
