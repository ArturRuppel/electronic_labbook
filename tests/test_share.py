"""Static-bundle export (Roadmap step 12): helpers, full/single export, CLI."""

import os
import sqlite3
from datetime import datetime

import pytest

from eln.db import init_db
from eln.sdgl import SDGL
from eln.share import _local_refs, _staticize, _strip_nav, _collect_assets


def _touch(path, ts):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    os.utime(path, (ts, ts))


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """A data-repo root (mirrors tests/generators/test_generate.py): experiments.db,
    an SDGL scan over a CODE-NN tree, two reports, and one presentation. Returns the
    root Path (a subdir of tmp_path, so test bundles can sit beside it)."""
    root = tmp_path / "repo"
    root.mkdir()
    db = root / "experiments.db"
    init_db.init_db(db)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO experiment_codes (title, code) VALUES ('Traction Force', 'TFMSP')")
    conn.execute("INSERT INTO experiments (id, experiment_type, repetition, excluded, file_path, "
                 "cell_types, microscope) VALUES (1,'Traction Force',1,0,'x','HUVEC','Spinning disk')")
    conn.execute("INSERT INTO experiments (id, experiment_type, repetition, excluded, file_path) "
                 "VALUES (2,'Traction Force',2,0,'x')")
    conn.execute("INSERT INTO protocols (id, name, version, description, content, is_latest) "
                 "VALUES (10,'Gel casting','2','How to cast','# Gel casting\n\nMix **A** and B.',1)")
    conn.execute("INSERT INTO experiment_protocols (experiment_id, protocol_id) VALUES (1, 10)")
    conn.execute("INSERT INTO tags (id, name) VALUES (5, 'migration')")
    conn.execute("INSERT INTO experiment_tags (experiment_id, tag_id) VALUES (1, 5)")
    conn.execute("INSERT INTO experiment_channels (experiment_id, channel_order, channel_label, "
                 "target, modality) VALUES (1, 0, 'Blue', 'F-actin', 'Fluorescence')")
    conn.commit()
    conn.close()

    data = root / "data"
    _touch(data / "TFMSP-01" / "raw" / "img.tif", datetime(2025, 3, 10, 12, 0).timestamp())
    _touch(data / "TFMSP-02" / "raw" / "img.tif", datetime(2025, 4, 15, 9, 0).timestamp())

    reports = root / "reports"
    (reports / "weekly").mkdir(parents=True)
    (reports / "weekly" / "tfm_progress.md").write_text(
        "# TFM progress\n\n**Series:** TFMSP\n\n**Date:** 2025-03-10\n\n{{experiments}}\n\nLooking good.\n"
    )
    (reports / "notes.md").write_text("# Random notes\n\nNo series here.\n")

    pres = root / "presentations" / "2025-05-01_Lab_meeting"
    pres.mkdir(parents=True)
    (pres / "index.html").write_text('<html><img src="slides/1.png"></html>')
    (pres / "slides").mkdir()
    (pres / "slides" / "1.png").write_bytes(b"x")

    cfg = root / "labbook.toml"
    cfg.write_text(
        f'data_root = "{root}"\n\n[scanner]\nrun_on_startup = false\n\n'
        '[[scan_roots]]\nname = "data"\npath = "data"\n'
    )
    monkeypatch.setenv("LABBOOK_CONFIG", str(cfg))
    SDGL(root).scan_from_config()
    return root


def test_local_refs_keeps_relative_skips_external():
    html = (
        '<a href="experiments.html">x</a>'
        '<img src="reports/a/fig.png">'
        '<a href="https://example.com">y</a>'
        '<a href="//cdn/z.js">z</a>'
        '<a href="mailto:a@b.c">m</a>'
        '<a href="#top">t</a>'
        '<img src="data:image/png;base64,AAAA">'
        '<video><source src="reports/a/m.mp4?v=2#t"></video>'
    )
    assert _local_refs(html) == [
        "experiments.html", "reports/a/fig.png", "reports/a/m.mp4"
    ]


def test_staticize_drops_server_only_literals():
    html = (
        '<head>\n    <script src="auth.js"></script>\n</head>\n'
        '<div class="nav">\n'
        '        <a href="/">Data Graph</a>\n'
        '        <a href="experiments.html">Experiments</a>\n'
        '    </div>\n'
        '            <a href="/" class="card">\n'
        '                <div class="card-icon">D</div>\n'
        '                <div class="card-title">Data Graph</div>\n'
        '            </a>\n'
        '            <a href="reports.html" class="card">keep</a>\n'
    )
    out = _staticize(html)
    assert "auth.js" not in out
    assert 'href="/"' not in out
    assert "Data Graph" not in out
    assert 'href="experiments.html"' in out      # nav itself stays
    assert 'href="reports.html" class="card"' in out  # other cards stay


def test_strip_nav_removes_whole_nav_block():
    html = (
        'before\n'
        '    <div class="nav">\n'
        '        <a href="experiments.html">Experiments</a>\n'
        '    </div>\n'
        'after\n'
    )
    out = _strip_nav(html)
    assert '<div class="nav">' not in out
    assert "Experiments" not in out
    assert "before" in out and "after" in out


def test_collect_assets_transitive_and_skips(tmp_path):
    root = tmp_path / "root"
    dest = tmp_path / "dest"
    # A presentation page links to a nested self-contained presentation html,
    # which in turn links a slide and a movie; a build script must NOT be copied.
    (root / "presentations" / "P").mkdir(parents=True)
    (root / "presentations" / "P" / "index.html").write_text(
        '<img src="slides/1.png"><source src="movie.mp4">'
    )
    (root / "presentations" / "P" / "slides").mkdir()
    (root / "presentations" / "P" / "slides" / "1.png").write_bytes(b"PNG")
    (root / "presentations" / "P" / "movie.mp4").write_bytes(b"MP4DATA")
    (root / "presentations" / "P" / "build.sh").write_text("echo unused")
    dest.mkdir()

    start = [("", '<a href="presentations/P/index.html">P</a>'
                  '<a href="experiments.html">sibling</a>')]
    # experiments.html is a generated sibling page already present in dest:
    (dest / "experiments.html").write_text("<html>generated</html>")

    seen, missing, total = _collect_assets(start, root, dest, generated={"experiments.html"})

    assert (dest / "presentations" / "P" / "index.html").is_file()
    assert (dest / "presentations" / "P" / "slides" / "1.png").read_bytes() == b"PNG"
    assert (dest / "presentations" / "P" / "movie.mp4").is_file()
    assert not (dest / "presentations" / "P" / "build.sh").exists()  # unreferenced
    index_text = '<img src="slides/1.png"><source src="movie.mp4">'
    assert total == len(b"PNG") + len(b"MP4DATA") + len(index_text)
    assert missing == []


def test_collect_assets_reports_missing(tmp_path):
    root = tmp_path / "root"; root.mkdir()
    dest = tmp_path / "dest"; dest.mkdir()
    start = [("", '<img src="reports/gone.png">')]
    seen, missing, total = _collect_assets(start, root, dest, generated=set())
    assert missing == ["reports/gone.png"]
    assert total == 0


def test_export_all_layout_and_staticized(data_root, tmp_path):
    from eln.share import export_all
    dest = tmp_path / "bundle"
    result = export_all(data_root, dest)
    for page in ["index.html", "experiments.html", "protocols.html",
                 "reports.html", "presentations.html"]:
        assert (dest / page).is_file(), page
    home = (dest / "index.html").read_text()
    assert 'href="/"' not in home and "auth.js" not in home
    nav_page = (dest / "experiments.html").read_text()
    assert ">Data Graph<" not in nav_page          # server-only link dropped
    assert ">Experiments<" in nav_page             # nav otherwise intact
    assert (dest / "presentations" / "2025-05-01_Lab_meeting"
                 / "slides" / "1.png").is_file()
    assert result["files"] >= 1 and result["bytes"] >= 1


def test_export_all_refuses_dest_inside_root(data_root):
    from eln.share import _assert_dest_outside_root
    with pytest.raises(ValueError):
        _assert_dest_outside_root(data_root / "reports" / "out", data_root)
    _assert_dest_outside_root(data_root.parent / "out", data_root)


def test_generate_reports_only_one_file(data_root, tmp_path):
    from eln.generators.reports import generate_reports
    out_dir = tmp_path / "out"
    path = generate_reports(data_root, catalog_out=out_dir,
                            only="reports/weekly/tfm_progress.md",
                            output_name="one.html")
    assert path.name == "one.html"
    html = path.read_text()
    assert "TFM progress" in html        # the selected report
    assert "Random notes" not in html    # the other report excluded


def test_export_item_report_flat_no_nav(data_root, tmp_path):
    from eln.share import export_item
    dest = tmp_path / "rep"
    result = export_item(data_root, dest, "report", "reports/weekly/tfm_progress.md")
    index = (dest / "index.html").read_text()
    assert "TFM progress" in index
    assert '<div class="nav">' not in index   # standalone, nav stripped
    assert "auth.js" not in index
    assert result["missing"] == []


def test_export_item_presentation_mirrored_with_redirect(data_root, tmp_path):
    from eln.share import export_item
    dest = tmp_path / "pres"
    export_item(data_root, dest, "presentation", "2025-05-01_Lab_meeting")
    redirect = (dest / "index.html").read_text()
    assert "2025-05-01_Lab_meeting/index.html" in redirect   # meta-refresh target
    assert (dest / "presentations" / "2025-05-01_Lab_meeting" / "index.html").is_file()
    assert (dest / "presentations" / "2025-05-01_Lab_meeting"
                 / "slides" / "1.png").is_file()


def test_export_item_unknown_kind(data_root, tmp_path):
    from eln.share import export_item
    with pytest.raises(ValueError):
        export_item(data_root, tmp_path / "x", "bogus", "whatever")
