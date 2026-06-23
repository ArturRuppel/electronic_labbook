"""SDGL engine: naming grammar + scan, with the debugged refinements as
acceptance criteria (raw-only date derivation, hidden-folder exclusion)."""

import os
import sqlite3
from datetime import datetime

import pytest

from eln.db import init_db, dump_db
from eln.sdgl import SDGL, format_experiment_id, parse_code_folder, parse_id_folder


# --- pure naming grammar ----------------------------------------------------

def test_parse_id_folder_active_and_excluded():
    assert parse_id_folder("TFMSP-01") == {"code": "TFMSP", "rep": 1, "excluded": False}
    assert parse_id_folder("COV2D-X03") == {"code": "COV2D", "rep": 3, "excluded": True}
    # SPHIM-010 is rep 10, a different experiment (not rep 1).
    assert parse_id_folder("SPHIM-010") == {"code": "SPHIM", "rep": 10, "excluded": False}
    assert parse_id_folder("NOTES") is None
    # Exact names only — no trailing tags. Downstream structure comes from nesting.
    assert parse_id_folder("TFMSP-01_growth") is None
    assert parse_id_folder("TFMSP-01 extra") is None


def test_parse_code_folder_only_bare_codes():
    assert parse_code_folder("TFMSP") == {"code": "TFMSP"}
    # CODE-NN forms are NOT bare-code folders.
    assert parse_code_folder("TFMSP-01") is None
    # Exact 5-char code only — no trailing tags.
    assert parse_code_folder("TFMSP_aggregate") is None


def test_format_experiment_id():
    assert format_experiment_id("TFMSP", 1) == "TFMSP-01"
    assert format_experiment_id("TFMSP", 12) == "TFMSP-12"
    assert format_experiment_id("COV2D", 3, excluded=True) == "COV2D-X03"


# --- scan fixture -----------------------------------------------------------

def _touch(path, ts):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    os.utime(path, (ts, ts))


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """A data root with experiments.db, a small CODE-NN tree, and a unified
    labbook.toml discoverable via LABBOOK_CONFIG (so scan_from_config works)."""
    root = tmp_path
    db = root / "experiments.db"
    init_db.init_db(db)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO experiment_codes (title, code) VALUES ('Traction Force', 'TFMSP')")
    conn.execute("INSERT INTO experiments (experiment_type, repetition, file_path) VALUES ('Traction Force', 1, 'x')")
    conn.execute("INSERT INTO experiments (experiment_type, repetition, file_path) VALUES ('Traction Force', 2, 'x')")
    conn.commit()
    conn.close()

    cfg = root / "labbook.toml"
    cfg.write_text(
        f'data_root = "{root}"\n\n[scanner]\nrun_on_startup = false\n\n'
        '[[scan_roots]]\nname = "data"\npath = "data"\n'
    )
    monkeypatch.setenv("LABBOOK_CONFIG", str(cfg))

    data = root / "data"
    # Rep 1: raw file (the experiment start) plus a LATER analysis output and an
    # EARLIER non-raw file (must be ignored — raw-only date derivation).
    ts_raw1 = datetime(2025, 3, 10, 12, 0).timestamp()
    _touch(data / "TFMSP-01" / "raw" / "img.tif", ts_raw1)
    _touch(data / "TFMSP-01" / "analysis" / "out.csv", datetime(2025, 6, 1).timestamp())
    _touch(data / "TFMSP-01" / "analysis" / "early.csv", datetime(2025, 1, 1).timestamp())  # earlier, non-raw
    # Hidden dir + hidden file must never be recorded.
    _touch(data / "TFMSP-01" / ".hidden" / "secret.tif", ts_raw1)
    _touch(data / "TFMSP-01" / "raw" / ".DS_Store", ts_raw1)
    # Rep 2: a different raw start date.
    ts_raw2 = datetime(2025, 4, 15, 9, 0).timestamp()
    _touch(data / "TFMSP-02" / "raw" / "img.tif", ts_raw2)
    # Bare-code aggregate folder.
    _touch(data / "TFMSP" / "summary.pdf", datetime(2025, 7, 1).timestamp())

    expected = {
        1: datetime.fromtimestamp(ts_raw1).strftime("%Y-%m-%d"),
        2: datetime.fromtimestamp(ts_raw2).strftime("%Y-%m-%d"),
    }
    return root, db, expected


def test_scan_recognizes_folders(data_root):
    root, db, expected = data_root
    summary = SDGL(root).scan_from_config()

    assert summary["recognized"] == 2     # TFMSP-01, TFMSP-02
    assert summary["aggregates"] == 1     # bare TFMSP folder


def test_scan_derives_date_from_earliest_raw_mtime(data_root):
    """The single experiment date is derived live from the earliest RAW mtime
    (earlier non-raw early.csv ignored) — exposed via the SDGL tree, not stored."""
    root, db, expected = data_root
    sdgl = SDGL(root)
    sdgl.scan_from_config()
    reps = {
        rep["id"]: rep["date"]
        for group in sdgl.tree()["experiments"]
        for rep in group["repetitions"]
    }
    assert reps["TFMSP-01"] == expected[1]
    assert reps["TFMSP-02"] == expected[2]


def test_scan_scrubs_legacy_start_date(data_root):
    """A legacy materialized start_date is deleted on scan; no date is stored."""
    root, db, _ = data_root
    sdgl = SDGL(root)
    sdgl.scan_from_config()
    # Inject a stale start_date as if written by an older scanner.
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO experiment_metadata (experiment_id, key, value) "
        "VALUES (1, 'start_date', '2020-01-01') "
        "ON CONFLICT(experiment_id, key) DO UPDATE SET value = excluded.value"
    )
    conn.commit()
    conn.close()

    sdgl.scan_from_config()  # re-scan should scrub it

    conn = sqlite3.connect(db)
    remaining = conn.execute(
        "SELECT COUNT(*) FROM experiment_metadata WHERE key = 'start_date'"
    ).fetchone()[0]
    conn.close()
    assert remaining == 0


def test_hidden_paths_never_recorded(data_root):
    root, db, _ = data_root
    sdgl = SDGL(root)
    sdgl.scan_from_config()
    conn = sdgl.connect()
    paths = [r["path"] for r in conn.execute("SELECT path FROM file_locations")]
    conn.close()
    assert paths, "expected some recorded locations"
    assert not any(".hidden" in p for p in paths)
    assert not any(".DS_Store" in p for p in paths)


def test_rescan_self_heals_recorded_hidden_path(data_root):
    """A previously-recorded hidden path is pruned on the next scan."""
    root, db, _ = data_root
    sdgl = SDGL(root)
    sdgl.scan_from_config()
    # Inject a stale hidden location as if recorded by an older scanner.
    conn = sdgl.connect()
    conn.execute(
        "INSERT INTO file_locations (id, node_id, root_name, path, role, exists_now) "
        "VALUES ('location:stale', 'experiment:TFMSP-01', 'data', ?, 'file', 1)",
        (str(root / "data" / "TFMSP-01" / ".hidden" / "secret.tif"),),
    )
    conn.commit()
    conn.close()

    sdgl.scan_from_config()  # re-scan should prune it

    conn = sdgl.connect()
    remaining = conn.execute(
        "SELECT COUNT(*) FROM file_locations WHERE id = 'location:stale'"
    ).fetchone()[0]
    conn.close()
    assert remaining == 0


def test_start_date_not_stored_in_experiments_sql(data_root, tmp_path):
    """The date is derived live, never stored, so it does not ride inside the
    diffable experiments.sql dump."""
    root, db, expected = data_root
    SDGL(root).scan_from_config()
    sql = tmp_path / "out.sql"
    dump_db.dump(db, sql)
    text = sql.read_text()
    assert "start_date" not in text


def test_scan_roots_reports_progress(data_root):
    """scan_roots emits a per-root event and a final 'done' summary event."""
    root, _db, _expected = data_root
    events = []
    SDGL(root).scan_roots([{"name": "data", "path": "data"}], progress=events.append)
    assert any(e.get("phase") == "root" and e.get("root") == "data" for e in events)
    assert any(e.get("phase") == "done" for e in events)


# --- report sync (markdown + notebooks) -------------------------------------

import json


def _ipynb(markdown):
    return json.dumps({
        "cells": [{"cell_type": "markdown", "source": markdown},
                  {"cell_type": "code", "source": "print('hidden')", "outputs": []}],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
    })


def test_sync_reports_indexes_notebook_and_skips_readme(data_root):
    """A .ipynb report is registered (from its markdown cells) and README.md is
    not; an alphanumeric **Series:** code links the report to its experiments."""
    root, db, _ = data_root
    # Series COV2D has a digit -> exercises the alphanumeric series match.
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO experiment_codes (title, code) VALUES ('Coverage', 'COV2D')")
    conn.execute("INSERT INTO experiments (experiment_type, repetition, excluded, file_path) "
                 "VALUES ('Coverage', 1, 0, 'x')")
    conn.commit()
    conn.close()

    reports = root / "reports"
    reports.mkdir()
    (reports / "README.md").write_text("# reports\n\nFolder docs, not a report.\n")
    (reports / "cov2d.ipynb").write_text(
        _ipynb("# COV2D — analysis\n\n**Series:** COV2D\n\n{{experiments}}\n"))

    SDGL(root).scan_from_config()

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    paths = {r["file_path"] for r in conn.execute("SELECT file_path FROM reports")}
    titles = {r["file_path"]: r["title"] for r in conn.execute("SELECT file_path, title FROM reports")}
    conn.close()
    assert "reports/cov2d.ipynb" in paths
    assert "reports/README.md" not in paths
    assert titles["reports/cov2d.ipynb"] == "COV2D — analysis"  # H1 from a markdown cell

    sdgl = SDGL(root)
    c = sdgl.connect()
    has_report = c.execute(
        "SELECT COUNT(*) FROM edges WHERE relation_type = 'has_report' "
        "AND source_id = 'experiment:COV2D-01'"
    ).fetchone()[0]
    c.close()
    assert has_report == 1  # alphanumeric series code linked, not dropped


def test_sync_reports_prunes_deleted_notebook(data_root):
    """Deleting a report file prunes its row and node on the next scan."""
    root, db, _ = data_root
    reports = root / "reports"
    reports.mkdir()
    nb = reports / "note.ipynb"
    nb.write_text(_ipynb("# Note\n\nNo series here.\n"))
    SDGL(root).scan_from_config()

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM reports WHERE file_path = 'reports/note.ipynb'").fetchone()[0] == 1
    conn.close()

    nb.unlink()
    SDGL(root).scan_from_config()

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM reports WHERE file_path = 'reports/note.ipynb'").fetchone()[0] == 0
    conn.close()


def test_sync_reports_renamed_file_does_not_duplicate_node(data_root):
    """Renaming a report file must not leave an orphan graph node behind.

    A rename inserts a new report row (new id -> new node) for the new path; the
    old row is pruned, so the per-row prune can't reach the old node. The graph
    must still end with exactly one report node + one has_report edge per series,
    not a duplicate listing.
    """
    root, db, _ = data_root
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO experiment_codes (title, code) VALUES ('Coverage', 'COV2D')")
    conn.execute("INSERT INTO experiments (experiment_type, repetition, excluded, file_path) "
                 "VALUES ('Coverage', 1, 0, 'x')")
    conn.commit()
    conn.close()

    old = root / "reports" / "auto"
    old.mkdir(parents=True)
    (old / "COV2D.md").write_text("# COV2D\n\n**Series:** COV2D\n\n{{experiments}}\n")
    SDGL(root).scan_from_config()

    # Rename: reports/auto/COV2D.md -> reports/COV2D/COV2D.md
    new = root / "reports" / "COV2D"
    new.mkdir(parents=True)
    (new / "COV2D.md").write_text((old / "COV2D.md").read_text())
    (old / "COV2D.md").unlink()
    old.rmdir()
    SDGL(root).scan_from_config()

    sdgl = SDGL(root)
    c = sdgl.connect()
    report_nodes = c.execute("SELECT COUNT(*) FROM nodes WHERE id LIKE 'report:%'").fetchone()[0]
    has_report = c.execute(
        "SELECT COUNT(*) FROM edges WHERE relation_type = 'has_report' "
        "AND source_id = 'experiment:COV2D-01'"
    ).fetchone()[0]
    c.close()
    assert report_nodes == 1   # the renamed report, not the old orphan too
    assert has_report == 1     # listed once, not twice

    conn = sqlite3.connect(db)
    paths = [r[0] for r in conn.execute("SELECT file_path FROM reports")]
    conn.close()
    assert paths == ["reports/COV2D/COV2D.md"]
