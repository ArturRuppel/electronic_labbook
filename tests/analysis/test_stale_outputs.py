"""stale_outputs(): an output is stale when an input changed since it was stamped."""

from eln.hashing import sha256_file
from eln.sdgl import SDGL


def _stamp_output(root, *, out_rel, inputs):
    """Create a stamped dataset node + a generates edge recording input hashes."""
    sdgl = SDGL(root)
    sdgl.initialize()
    conn = sdgl.connect()
    out_abs = root / out_rel
    out_abs.parent.mkdir(parents=True, exist_ok=True)
    out_abs.write_bytes(b"FIGURE")
    record = {"kind": "derived", "rel_path": out_rel,
              "content_hash": sha256_file(out_abs), "inputs": inputs}
    sdgl.upsert_node("experiment:COV2D", "experiment", conn=conn)
    sdgl.upsert_node("dataset:" + out_rel, "dataset",
                     metadata={"rel_path": out_rel,
                               "content_hash": record["content_hash"],
                               "kind": "derived"}, conn=conn)
    sdgl.upsert_edge("experiment:COV2D", "dataset:" + out_rel, "generates",
                     record, conn=conn)
    conn.commit()
    conn.close()


def test_not_stale_when_inputs_match(tmp_path):
    from eln.analysis.provenance import stale_outputs
    inp = tmp_path / "reports" / "cov2d" / "in.csv"
    inp.parent.mkdir(parents=True, exist_ok=True)
    inp.write_bytes(b"DATA-V1")
    _stamp_output(tmp_path, out_rel="reports/cov2d/fig.png",
                  inputs={"reports/cov2d/in.csv": sha256_file(inp)})
    assert stale_outputs(tmp_path) == []


def test_stale_when_input_changed(tmp_path):
    from eln.analysis.provenance import stale_outputs
    inp = tmp_path / "reports" / "cov2d" / "in.csv"
    inp.parent.mkdir(parents=True, exist_ok=True)
    inp.write_bytes(b"DATA-V1")
    _stamp_output(tmp_path, out_rel="reports/cov2d/fig.png",
                  inputs={"reports/cov2d/in.csv": sha256_file(inp)})
    inp.write_bytes(b"DATA-V2")  # input changed after stamping
    result = stale_outputs(tmp_path)
    assert len(result) == 1
    assert result[0]["path"] == "reports/cov2d/fig.png"
    assert result[0]["status"] == "stale"
    assert result[0]["changed_inputs"] == ["reports/cov2d/in.csv"]
