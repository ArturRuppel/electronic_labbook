"""SDGL engine: naming grammar + scan, with the debugged refinements as
acceptance criteria (materialized raw-only start_date, hidden-folder exclusion)."""

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
def data_root(tmp_path):
    """A data root with experiments.db, sdgl.toml, and a small CODE-NN tree."""
    root = tmp_path
    db = root / "experiments.db"
    init_db.init_db(db)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO experiment_codes (title, code) VALUES ('Traction Force', 'TFMSP')")
    conn.execute("INSERT INTO experiments (experiment_type, repetition, file_path) VALUES ('Traction Force', 1, 'x')")
    conn.execute("INSERT INTO experiments (experiment_type, repetition, file_path) VALUES ('Traction Force', 2, 'x')")
    conn.commit()
    conn.close()

    (root / "sdgl.toml").write_text(
        '[scanner]\nrun_on_startup = false\n\n[[scan_roots]]\nname = "data"\npath = "data"\n'
    )

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


def test_scan_recognizes_and_materializes_dates(data_root):
    root, db, expected = data_root
    summary = SDGL(root).scan_from_config()

    assert summary["recognized"] == 2     # TFMSP-01, TFMSP-02
    assert summary["aggregates"] == 1     # bare TFMSP folder

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    dates = {
        r["experiment_id"]: r["value"]
        for r in conn.execute("SELECT experiment_id, value FROM experiment_metadata WHERE key='start_date'")
    }
    conn.close()
    # Materialized start_date == earliest RAW mtime (earlier non-raw early.csv ignored).
    assert dates[1] == expected[1]
    assert dates[2] == expected[2]


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


def test_start_date_rides_inside_experiments_sql(data_root, tmp_path):
    root, db, expected = data_root
    SDGL(root).scan_from_config()
    sql = tmp_path / "out.sql"
    dump_db.dump(db, sql)
    text = sql.read_text()
    assert "start_date" in text
    assert expected[1] in text


def test_scan_roots_reports_progress(data_root):
    """scan_roots emits a per-root event and a final 'done' summary event."""
    root, _db, _expected = data_root
    events = []
    SDGL(root).scan_roots([{"name": "data", "path": "data"}], progress=events.append)
    assert any(e.get("phase") == "root" and e.get("root") == "data" for e in events)
    assert any(e.get("phase") == "done" for e in events)
