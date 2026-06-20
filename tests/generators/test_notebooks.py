"""Notebooks generator: id classification, cell rendering, provenance, assembly."""

import json as _json
import sqlite3

from eln.generators.notebooks import (
    classify_notebook,
    generate_notebooks,
    known_codes,
    notebook_artifacts,
    render_cells,
)


# ---- classify_notebook -----------------------------------------------------

def test_classify_session():
    info = classify_notebook("SORVI-01")
    assert info == {"kind": "session", "code": "SORVI", "rep": 1,
                    "excluded": False, "id": "SORVI-01"}


def test_classify_excluded_session():
    info = classify_notebook("COV2D-X03")
    assert info["kind"] == "session"
    assert info["excluded"] is True
    assert info["id"] == "COV2D-X03"


def test_classify_series():
    assert classify_notebook("SORVI") == {"kind": "series", "code": "SORVI", "id": "SORVI"}


def test_classify_unmatched():
    assert classify_notebook("scratch") == {"kind": "unmatched", "code": None, "id": "scratch"}


# ---- render_cells ----------------------------------------------------------

def _nb(cells):
    return {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}


def test_render_markdown_and_code():
    nb = _nb([
        {"cell_type": "markdown", "source": ["# Title\n", "\n", "Some **prose**.\n"]},
        {"cell_type": "code", "source": ["import numpy as np\n", "x = np.arange(3)\n"],
         "outputs": [], "execution_count": 1},
    ])
    html_out, output_cells = render_cells(nb)
    assert output_cells == 0
    assert "<h1>Title</h1>" in html_out
    assert "<strong>prose</strong>" in html_out
    assert "import numpy as np" in html_out
    assert 'class="nb-code"' in html_out


def test_render_ignores_outputs_and_counts_them():
    nb = _nb([
        {"cell_type": "code", "source": ["print('hi')\n"],
         "outputs": [{"output_type": "stream", "name": "stdout", "text": ["hi\n"]}],
         "execution_count": 1},
    ])
    html_out, output_cells = render_cells(nb)
    assert output_cells == 1
    # The output content is NOT rendered into the page.
    assert "stdout" not in html_out
    assert "print(&#x27;hi&#x27;)" in html_out  # source is html-escaped


def test_render_source_as_plain_string():
    nb = _nb([{"cell_type": "code", "source": "a = 1\n", "outputs": []}])
    html_out, _ = render_cells(nb)
    assert "a = 1" in html_out


# ---- known_codes -----------------------------------------------------------

def _make_db_with_codes(path, codes):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE experiment_codes (title TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE)")
    for i, code in enumerate(codes):
        conn.execute("INSERT INTO experiment_codes (title, code) VALUES (?, ?)", (f"t{i}", code))
    conn.commit()
    conn.close()


def test_known_codes_reads_table(tmp_path):
    db = tmp_path / "experiments.db"
    _make_db_with_codes(db, ["SORVI", "COV2D"])
    assert known_codes(db) == {"SORVI", "COV2D"}


def test_known_codes_missing_db_is_empty(tmp_path):
    assert known_codes(tmp_path / "nope.db") == set()


def test_known_codes_missing_table_is_empty(tmp_path):
    db = tmp_path / "experiments.db"
    sqlite3.connect(str(db)).close()  # empty db, no experiment_codes table
    assert known_codes(db) == set()


# ---- notebook_artifacts ----------------------------------------------------

def test_notebook_artifacts_none_without_sdgl(tmp_path):
    assert notebook_artifacts(tmp_path, "notebooks/SORVI-01.ipynb") == []


def test_notebook_artifacts_lists_generates_edges(tmp_path):
    from eln.hashing import sha256_file
    from eln.sdgl import SDGL

    # An artifact on disk whose stored hash matches -> status "ok".
    art_dir = tmp_path / "data" / "SORVI-01" / "analysis"
    art_dir.mkdir(parents=True)
    art = art_dir / "plot.png"
    art.write_bytes(b"PNGDATA")
    rel = "data/SORVI-01/analysis/plot.png"
    content_hash = sha256_file(art)

    sdgl = SDGL(tmp_path)
    sdgl.initialize()
    conn = sdgl.connect()
    sdgl.upsert_node("experiment:SORVI-01", "experiment", conn=conn)
    sdgl.upsert_node(
        "dataset:" + rel, "dataset",
        metadata={"rel_path": rel, "content_hash": content_hash, "kind": "derived"},
        conn=conn,
    )
    sdgl.upsert_edge(
        "experiment:SORVI-01", "dataset:" + rel, "generates",
        {"notebook": {"path": "notebooks/SORVI-01.ipynb"}}, conn=conn,
    )
    conn.commit()
    conn.close()

    arts = notebook_artifacts(tmp_path, "notebooks/SORVI-01.ipynb")
    assert arts == [{"path": rel, "status": "ok"}]
    # A different notebook path matches nothing.
    assert notebook_artifacts(tmp_path, "notebooks/OTHER-01.ipynb") == []


# ---- generate_notebooks ----------------------------------------------------

def _write_nb(path, cells):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(
        {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}))


def test_generate_empty_dir_placeholder(tmp_path):
    (tmp_path / "experiments.db").touch()
    out = generate_notebooks(tmp_path)
    assert out == tmp_path / "catalog" / "notebooks.html"
    text = out.read_text()
    assert "No notebooks yet" in text
    assert 'href="protocols.html"' in text  # nav present


def test_generate_renders_matched_and_flags_unmatched(tmp_path):
    _make_db_with_codes(tmp_path / "experiments.db", ["SORVI"])
    _write_nb(tmp_path / "notebooks" / "SORVI-01.ipynb",
              [{"cell_type": "code", "source": ["x = 1\n"], "outputs": []}])
    _write_nb(tmp_path / "notebooks" / "scratch.ipynb",
              [{"cell_type": "markdown", "source": ["notes"]}])
    text = generate_notebooks(tmp_path).read_text()
    assert "SORVI-01" in text
    assert "x = 1" in text
    assert "scratch" in text
    assert "unmatched" in text.lower()


def test_generate_warns_on_outputs(tmp_path):
    _make_db_with_codes(tmp_path / "experiments.db", ["SORVI"])
    _write_nb(tmp_path / "notebooks" / "SORVI-01.ipynb",
              [{"cell_type": "code", "source": ["print(1)\n"],
                "outputs": [{"output_type": "stream", "name": "stdout", "text": ["1\n"]}]}])
    text = generate_notebooks(tmp_path).read_text()
    assert "outputs" in text.lower()


# ---- wiring ----------------------------------------------------------------

def test_nav_includes_notebooks_after_protocols():
    from eln.generators.nav import CORE_NAV
    labels = [link.label for link in CORE_NAV]
    assert "Notebooks" in labels
    assert labels.index("Notebooks") == labels.index("Protocols") + 1


def test_generate_all_writes_notebooks(tmp_path):
    from eln.db import init_db
    init_db.init_db(tmp_path / "experiments.db")  # real schema (generate_all needs it)
    from eln.generators import generate_all
    written = generate_all(tmp_path)
    assert "notebooks" in written
    assert written["notebooks"].name == "notebooks.html"
    assert written["notebooks"].exists()


def test_server_serves_notebooks_page():
    from eln.server.app import CORE_GENERATED_PAGES
    assert "notebooks.html" in CORE_GENERATED_PAGES


def test_export_catalog_pages_include_notebooks():
    from eln.share import _CATALOG_PAGES
    assert "notebooks.html" in _CATALOG_PAGES
