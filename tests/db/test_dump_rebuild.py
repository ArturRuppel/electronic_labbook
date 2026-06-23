"""Round-trip + determinism tests for eln.db dump/rebuild plumbing."""

import sqlite3

import pytest

from eln.db import connect, init_db, dump_db, rebuild_db


def _populate(db_path):
    """Insert representative rows: NULLs, unicode, quotes, FKs, junctions, blob."""
    conn = connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO protocols (name, version, description, content, is_latest) "
        "VALUES (?, ?, ?, ?, 1)",
        ("TFM prep", "1.0", "He said \"go\"", "line1\nline2"),
    )
    cur.execute(
        "INSERT INTO experiments (experiment_uid, repetition, experiment_type, cell_types, file_path, comments) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("AA01", 1, "TFM", "REF52; NIH3T3", "/data/AA01", None),
    )
    cur.execute(
        "INSERT INTO experiments (experiment_uid, repetition, experiment_type, file_path, comments) "
        "VALUES (?, ?, ?, ?, ?)",
        ("AB02", 1, "fixed", "/data/AB02", "ünïcödé ☃ and ' quote"),
    )
    cur.execute("INSERT INTO experiment_codes (title, code) VALUES ('Nestin KO vs Ctrl', 'AA')")
    cur.execute("INSERT INTO reports (title, file_path) VALUES ('2026-02 NestinKO', 'reports/r1/r1.md')")
    cur.execute("INSERT INTO experiment_reports (experiment_id, report_id) VALUES (1, 1)")
    cur.execute(
        "INSERT INTO experiment_metadata (experiment_id, key, value) VALUES (1, 'instrument_serial', 'MX-2026-014')"
    )
    cur.execute("INSERT INTO tags (name) VALUES ('vimentin')")
    cur.execute("INSERT INTO experiment_tags (experiment_id, tag_id) VALUES (1, 1)")
    cur.execute("INSERT INTO experiment_protocols (experiment_id, protocol_id) VALUES (1, 1)")
    cur.execute(
        "INSERT INTO experiment_channels (experiment_id, channel_order, channel_label, target, modality) "
        "VALUES (1, 0, '488', 'GFP', 'fluorescence')"
    )
    conn.commit()
    conn.close()


def test_init_creates_all_tables(tmp_path):
    db = tmp_path / "experiments.db"
    init_db.init_db(db)
    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {
        "protocols",
        "reports",
        "experiments",
        "experiment_codes",
        "experiment_metadata",
        "tags",
        "experiment_tags",
        "experiment_protocols",
        "experiment_reports",
        "experiment_channels",
    } <= names


def test_roundtrip_byte_identical(tmp_path):
    """rebuild -> dump again must be byte-identical to the first dump."""
    db = tmp_path / "experiments.db"
    init_db.init_db(db)
    _populate(db)

    sql1 = tmp_path / "experiments.sql"
    dump_db.dump(db, sql1)

    db2 = tmp_path / "rebuilt.db"
    rebuild_db.rebuild(sql1, db2)

    sql2 = tmp_path / "experiments2.sql"
    dump_db.dump(db2, sql2)

    assert sql1.read_bytes() == sql2.read_bytes()


def test_dump_is_stable_across_repeats(tmp_path):
    """Dumping the same db twice yields identical output (determinism)."""
    db = tmp_path / "experiments.db"
    init_db.init_db(db)
    _populate(db)
    a = tmp_path / "a.sql"
    b = tmp_path / "b.sql"
    dump_db.dump(db, a)
    dump_db.dump(db, b)
    assert a.read_bytes() == b.read_bytes()


def test_data_survives_roundtrip(tmp_path):
    db = tmp_path / "experiments.db"
    init_db.init_db(db)
    _populate(db)
    sql = tmp_path / "experiments.sql"
    dump_db.dump(db, sql)
    db2 = tmp_path / "rebuilt.db"
    rebuild_db.rebuild(sql, db2)

    conn = sqlite3.connect(db2)
    assert conn.execute("SELECT value FROM experiment_metadata WHERE key='instrument_serial'").fetchone()[0] == "MX-2026-014"
    assert conn.execute("SELECT comments FROM experiments WHERE experiment_uid='AB02'").fetchone()[0] == "ünïcödé ☃ and ' quote"
    assert conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0] == 2
    assert conn.execute("SELECT code FROM experiment_codes WHERE title='Nestin KO vs Ctrl'").fetchone()[0] == "AA"
    conn.close()


def test_rebuild_idempotent_noop(tmp_path):
    """rebuild is a no-op when the binary exists and --force is not given."""
    db = tmp_path / "experiments.db"
    init_db.init_db(db)
    _populate(db)
    sql = tmp_path / "experiments.sql"
    dump_db.dump(db, sql)

    target = tmp_path / "out.db"
    rebuild_db.rebuild(sql, target)
    mtime = target.stat().st_mtime_ns
    # second call without force must not touch the file
    rebuild_db.rebuild(sql, target)
    assert target.stat().st_mtime_ns == mtime
    # with force it rebuilds
    rebuild_db.rebuild(sql, target, force=True)


def test_dump_missing_db_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        dump_db.dump(tmp_path / "nope.db", tmp_path / "out.sql")
