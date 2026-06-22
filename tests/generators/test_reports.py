"""Reports generator: series parsing, notebook rendering, provenance footer."""

from eln.generators.reports import parse_series


def test_parse_series_alpha_code():
    assert parse_series("intro\n**Series:** SORVI\nmore") == "SORVI"


def test_parse_series_alphanumeric_code():
    # Regression: the old [A-Z]{5} regex did not match a code with a digit.
    assert parse_series("# COV2D\n**Series:** COV2D\n{{experiments}}") == "COV2D"


def test_parse_series_absent():
    assert parse_series("no series declared here") is None


def test_parse_series_rejects_non_code():
    # 5 non-space chars match the regex, but the SDGL grammar rejects them, so the
    # parse_code_folder filter (not the regex) is what returns None here.
    assert parse_series("**Series:** a!b@c") is None


from eln.generators.reports import notebook_markdown


def _nb(cells):
    return {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}


def test_notebook_markdown_keeps_markdown_drops_code():
    nb = _nb([
        {"cell_type": "markdown", "source": ["# Title\n", "\n", "**prose**\n"]},
        {"cell_type": "code", "source": ["import numpy as np\n"], "outputs": []},
        {"cell_type": "markdown", "source": ["After the code.\n"]},
    ])
    md = notebook_markdown(nb)
    assert "# Title" in md
    assert "**prose**" in md
    assert "After the code." in md
    assert "import numpy" not in md  # code cell fully hidden


def test_notebook_markdown_ignores_outputs():
    nb = _nb([
        {"cell_type": "code", "source": ["print('hi')\n"],
         "outputs": [{"output_type": "stream", "name": "stdout", "text": ["hi\n"]}]},
    ])
    assert notebook_markdown(nb).strip() == ""


def test_notebook_markdown_source_as_string():
    nb = _nb([{"cell_type": "markdown", "source": "plain string\n"}])
    assert "plain string" in notebook_markdown(nb)


import json as _json
import sqlite3


def _make_db_with_codes(path, codes):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE experiment_codes "
                 "(title TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE)")
    for i, code in enumerate(codes):
        conn.execute("INSERT INTO experiment_codes (title, code) VALUES (?, ?)",
                     (f"t{i}", code))
    conn.commit()
    conn.close()


def _write_nb(path, cells):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(
        {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}))


def test_generate_renders_notebook_report(tmp_path):
    from eln.generators.reports import generate_reports
    _make_db_with_codes(tmp_path / "experiments.db", ["COV2D"])
    _write_nb(tmp_path / "reports" / "cov2d" / "report.ipynb", [
        {"cell_type": "markdown",
         "source": ["# COV2D\n", "**Series:** COV2D\n", "\n",
                    "Interpretation prose.\n", "\n",
                    "![fig](figures/plot.png)\n"]},
        {"cell_type": "code", "source": ["secret = compute()\n"], "outputs": []},
    ])
    text = generate_reports(tmp_path).read_text()
    assert "Interpretation prose." in text          # markdown rendered
    assert "secret = compute()" not in text          # code hidden
    assert "reports/cov2d/figures/plot.png" in text  # image path rewritten to report dir
    assert "COV2D" in text                            # series-linked title


def test_report_card_shows_stale_badge(tmp_path):
    from eln.generators.reports import generate_reports
    from eln.hashing import sha256_file
    from eln.sdgl import SDGL

    db_path = tmp_path / "experiments.db"
    _make_db_with_codes(db_path, ["COV2D"])
    # SDGL.initialize() calls allocate_experiment_codes which needs an experiments table.
    _conn = sqlite3.connect(str(db_path))
    _conn.execute("CREATE TABLE IF NOT EXISTS experiments "
                  "(id INTEGER PRIMARY KEY, experiment_type TEXT, repetition INTEGER, excluded INTEGER DEFAULT 0)")
    _conn.commit()
    _conn.close()
    nb_rel = "reports/cov2d/report.ipynb"
    _write_nb(tmp_path / nb_rel, [
        {"cell_type": "markdown",
         "source": ["# COV2D\n", "**Series:** COV2D\n", "![f](figures/fig.png)\n"]},
    ])
    # An input that will change, and a stamped output produced by this notebook.
    inp = tmp_path / "reports" / "cov2d" / "in.csv"
    inp.write_bytes(b"V1")
    out_rel = "reports/cov2d/figures/fig.png"
    out_abs = tmp_path / out_rel
    out_abs.parent.mkdir(parents=True, exist_ok=True)
    out_abs.write_bytes(b"FIG")

    sdgl = SDGL(tmp_path)
    sdgl.initialize()
    conn = sdgl.connect()
    sdgl.upsert_node("experiment:COV2D", "experiment", conn=conn)
    sdgl.upsert_node("dataset:" + out_rel, "dataset",
                     metadata={"rel_path": out_rel,
                               "content_hash": sha256_file(out_abs),
                               "kind": "derived"}, conn=conn)
    sdgl.upsert_edge("experiment:COV2D", "dataset:" + out_rel, "generates",
                     {"rel_path": out_rel, "content_hash": sha256_file(out_abs),
                      "inputs": {"reports/cov2d/in.csv": sha256_file(inp)},
                      "notebook": {"path": nb_rel}}, conn=conn)
    conn.commit()
    conn.close()

    inp.write_bytes(b"V2")  # input drifts after stamping
    text = generate_reports(tmp_path).read_text()
    assert "stale" in text.lower()
    assert out_rel in text  # the produced artifact is listed in the footer


def test_generate_skips_malformed_notebook(tmp_path):
    from eln.generators.reports import generate_reports
    (tmp_path / "experiments.db").touch()
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "broken.ipynb").write_text("{ this is not valid json")
    (tmp_path / "reports" / "ok.md").write_text("# Good\n\nReadable report.\n")
    text = generate_reports(tmp_path).read_text()  # must not raise
    assert "Readable report." in text  # the good report still renders
