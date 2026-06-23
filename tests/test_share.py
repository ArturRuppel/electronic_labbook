"""Static-bundle export: helpers, full/single export, CLI."""

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
    conn.execute("INSERT INTO protocols (id, name, version, description, content, is_latest) "
                 "VALUES (11,'Staining','1','How to stain','# Staining\n\nAdd **dye**.',1)")
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
    # A realistic deck: slide 1 via plain <img>, slide 2 via reveal.js
    # data-background-image, slide 3 via a single-quoted <img>, plus a handout
    # referenced by nothing — all must reach the bundle (whole deck copied).
    (pres / "index.html").write_text(
        '<html><img src="slides/1.png">'
        '<section data-background-image="slides/2.png"></section>'
        "<img src='slides/3.png'></html>"
    )
    (pres / "slides").mkdir()
    (pres / "slides" / "1.png").write_bytes(b"x")
    (pres / "slides" / "2.png").write_bytes(b"x")
    (pres / "slides" / "3.png").write_bytes(b"x")
    (pres / "handout.pdf").write_bytes(b"PDF")

    cfg = root / "labbook.toml"
    cfg.write_text(
        f'data_root = "{root}"\n\n[scanner]\nrun_on_startup = false\n\n'
        '[[scan_roots]]\nname = "data"\npath = "data"\n'
    )
    monkeypatch.setenv("LABBOOK_CONFIG", str(cfg))
    SDGL(root).scan_from_config()
    # A real data repo carries experiments.sql (the source of truth the db is
    # built from); dump it so the CLI's _ensure_db is a realistic no-op.
    from eln.db.dump_db import dump
    dump(db, root / "experiments.sql")
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


def test_staticize_drops_auth_and_repoints_graph_link():
    html = (
        '<head>\n    <script src="auth.js"></script>\n</head>\n'
        '<div class="nav">\n'
        '        <a href="/">Data Graph</a>\n'
        '        <a href="experiments.html">Experiments</a>\n'
        '    </div>\n'
    )
    out = _staticize(html)
    assert "auth.js" not in out
    assert 'href="/"' not in out                       # dynamic root repointed
    # The Data Graph nav link now points at the bundle's static SDGL snapshot.
    assert '<a href="sdgl.html">Data Graph</a>' in out
    assert 'href="experiments.html"' in out            # nav itself stays


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


def test_collect_assets_copies_whole_deck(tmp_path):
    root = tmp_path / "root"
    dest = tmp_path / "dest"
    # A catalog page links to a presentation deck. Decks are copied wholesale, so
    # every file in the deck dir reaches the bundle — including a slide referenced
    # only via reveal.js data-background and a file referenced by nothing at all.
    deck = root / "presentations" / "P"
    deck.mkdir(parents=True)
    (deck / "index.html").write_text(
        '<img src="slides/1.png">'
        '<section data-background-image="slides/2.png"></section>'
    )
    (deck / "slides").mkdir()
    (deck / "slides" / "1.png").write_bytes(b"PNG1")
    (deck / "slides" / "2.png").write_bytes(b"PNG2")     # data-background only
    (deck / "movie.mp4").write_bytes(b"MP4DATA")          # referenced by nothing
    (deck / "build.sh").write_text("echo unused")         # referenced by nothing
    dest.mkdir()

    start = [("", '<a href="presentations/P/index.html">P</a>'
                  '<a href="experiments.html">sibling</a>')]
    # experiments.html is a generated sibling page already present in dest:
    (dest / "experiments.html").write_text("<html>generated</html>")

    seen, missing, total = _collect_assets(start, root, dest, generated={"experiments.html"})

    pdest = dest / "presentations" / "P"
    assert (pdest / "index.html").is_file()
    assert (pdest / "slides" / "1.png").read_bytes() == b"PNG1"
    assert (pdest / "slides" / "2.png").read_bytes() == b"PNG2"   # data-background slide
    assert (pdest / "movie.mp4").is_file()
    assert (pdest / "build.sh").is_file()                          # whole deck copied
    deck_bytes = sum(p.stat().st_size for p in deck.rglob("*") if p.is_file())
    assert total == deck_bytes
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
    # The bundle root redirects to the static SDGL page (the live app's front door).
    home = (dest / "index.html").read_text()
    assert 'href="/"' not in home and "auth.js" not in home
    assert "sdgl.html" in home                      # redirect target
    nav_page = (dest / "experiments.html").read_text()
    assert '<a href="sdgl.html">Data Graph</a>' in nav_page  # repointed, not dropped
    assert ">Experiments<" in nav_page             # nav otherwise intact
    deck = dest / "presentations" / "2025-05-01_Lab_meeting"
    assert (deck / "slides" / "1.png").is_file()
    assert (deck / "slides" / "2.png").is_file()   # data-background slide reaches bundle
    assert (deck / "handout.pdf").is_file()         # whole deck copied
    assert result["files"] >= 1 and result["bytes"] >= 1


def test_export_all_writes_static_sdgl_snapshot(data_root, tmp_path):
    import json, re
    from eln.share import export_all
    dest = tmp_path / "bundle"
    result = export_all(data_root, dest)

    # The static SDGL page carries its data snapshot embedded inline (not as a
    # sibling JSON the page fetches) so the bundle renders when opened from disk.
    page = (dest / "sdgl.html").read_text()
    assert "window.SDGL_STATIC = true" in page      # static mode on
    assert "auth.js" not in page                     # server-only script dropped
    assert '<a href="sdgl.html">Data Graph</a>' in page  # own nav repointed
    assert not (dest / "sdgl_data.json").exists()    # data is inline, not fetched

    embedded = re.search(r"window\.SDGL_DATA = (\{.*?\});</script>", page, re.S)
    assert embedded, "snapshot must be embedded inline in the page"
    snapshot = json.loads(embedded.group(1))
    assert "experiments" in snapshot["tree"]         # same shape as /api/sdgl/tree
    # The TFMSP series scanned into the fixture surfaces in the snapshot.
    assert any(g.get("code") == "TFMSP" for g in snapshot["tree"]["experiments"])

    # Bundle is internally consistent: the repointed Data Graph links resolve.
    assert result["missing"] == []


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
    # Standalone export: body shown open, header non-collapsible (no toggle/icon).
    assert 'class="report-header standalone"' in html
    assert 'class="report-details" id="details-tfm_progress" style="display: block;"' in html
    assert 'onclick="toggleReport(' not in html
    assert '<span class="expand-icon"' not in html


def test_export_item_report_flat_no_nav(data_root, tmp_path):
    from eln.share import export_item
    dest = tmp_path / "rep"
    result = export_item(data_root, dest, "report", "reports/weekly/tfm_progress.md")
    index = (dest / "index.html").read_text()
    assert "TFM progress" in index
    assert '<div class="nav">' not in index   # standalone, nav stripped
    assert "auth.js" not in index
    assert result["missing"] == []


def test_generate_protocol_catalog_only_one(data_root, tmp_path):
    from eln.generators.protocols import generate_protocol_catalog
    out_dir = tmp_path / "out"
    path = generate_protocol_catalog(data_root, catalog_out=out_dir, only="10",
                                     output_name="one.html")
    assert path.name == "one.html"
    html = path.read_text()
    assert "Gel casting" in html      # the selected protocol
    assert "Staining" not in html     # the other protocol excluded
    # Standalone export: body shown open, header non-collapsible (no toggle/icon).
    assert 'class="protocol-header standalone"' in html
    assert 'class="protocol-details" id="details-10" style="display: block;"' in html
    assert 'onclick="toggleProtocol(' not in html
    assert '<span class="expand-icon"' not in html


def test_export_item_protocol_flat_no_nav(data_root, tmp_path):
    from eln.share import export_item
    dest = tmp_path / "proto"
    result = export_item(data_root, dest, "protocol", "10")
    index = (dest / "index.html").read_text()
    assert "Gel casting" in index
    assert "Staining" not in index
    assert '<div class="nav">' not in index   # standalone, nav stripped
    assert "auth.js" not in index
    assert result["missing"] == []


def test_export_item_protocol_not_found(data_root, tmp_path):
    from eln.share import export_item
    with pytest.raises(ValueError):
        export_item(data_root, tmp_path / "x", "protocol", "9999")


def test_export_item_presentation_mirrored_with_redirect(data_root, tmp_path):
    from eln.share import export_item
    dest = tmp_path / "pres"
    export_item(data_root, dest, "presentation", "2025-05-01_Lab_meeting")
    redirect = (dest / "index.html").read_text()
    assert "2025-05-01_Lab_meeting/index.html" in redirect   # meta-refresh target
    deck = dest / "presentations" / "2025-05-01_Lab_meeting"
    assert (deck / "index.html").is_file()
    assert (deck / "slides" / "1.png").is_file()
    assert (deck / "slides" / "3.png").is_file()   # single-quoted <img> slide
    assert (deck / "handout.pdf").is_file()         # unreferenced asset, copied anyway


def test_export_item_unknown_kind(data_root, tmp_path):
    from eln.share import export_item
    with pytest.raises(ValueError):
        export_item(data_root, tmp_path / "x", "bogus", "whatever")


def test_export_all_deterministic(data_root, tmp_path):
    import filecmp
    from eln.share import export_all
    a, b = tmp_path / "a", tmp_path / "b"
    export_all(data_root, a)
    export_all(data_root, b)
    mismatches = []
    for fa in a.rglob("*"):
        if fa.is_file():
            fb = b / fa.relative_to(a)
            if not (fb.is_file() and filecmp.cmp(fa, fb, shallow=False)):
                mismatches.append(str(fa.relative_to(a)))
    assert mismatches == []


def test_cli_export_all(data_root, tmp_path, monkeypatch):
    from eln.cli import build_parser, cmd_export
    dest = tmp_path / "out"
    cfg = data_root / "labbook.toml"
    monkeypatch.setenv("LABBOOK_CONFIG", str(cfg))
    args = build_parser().parse_args(["export", "--all", "--dest", str(dest)])
    rc = cmd_export(args)
    assert rc == 0
    assert (dest / "index.html").is_file()


def test_report_card_has_data_src(data_root, tmp_path):
    from eln.generators.reports import generate_reports
    out = tmp_path / "c"
    generate_reports(data_root, catalog_out=out)
    html = (out / "reports.html").read_text()
    assert 'data-report-src="reports/weekly/tfm_progress.md"' in html


def test_report_card_title_uses_series_identity(data_root, tmp_path):
    """A series-linked report's card header is 'CODE — canonical title' (from
    experiment_codes), not its markdown H1; a standalone report keeps its H1."""
    from eln.generators.reports import generate_reports
    out = tmp_path / "c"
    generate_reports(data_root, catalog_out=out)
    html = (out / "reports.html").read_text()
    # tfm_progress.md declares '**Series:** TFMSP'; TFMSP -> 'Traction Force'.
    assert "TFMSP — Traction Force" in html
    # The free-form H1 still renders in the body, just not as the header title.
    # (Headings now carry a slug id so in-page anchor links resolve.)
    assert '<h1 id="tfm-progress">TFM progress</h1>' in html
    # notes.md has no series, so it falls back to its H1.
    assert "Random notes" in html


def test_presentation_row_has_data_dir(data_root, tmp_path):
    from eln.generators.presentations import generate_presentations
    out = tmp_path / "c"
    generate_presentations(data_root, catalog_out=out)
    html = (out / "presentations.html").read_text()
    assert 'data-pres-dir="2025-05-01_Lab_meeting"' in html
