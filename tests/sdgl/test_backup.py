import hashlib
import time
from pathlib import Path

from eln.sdgl import SDGL
from eln.sdgl.backup import (
    hash_file, dest_subpath, resolve_logical_files, classify, plan_backup,
    run_backup, BackupJob,
)


def test_hash_file_matches_hashlib(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello world" * 1000)
    assert hash_file(str(f)) == hashlib.sha256(f.read_bytes()).hexdigest()


def test_dest_subpath_experiment():
    assert dest_subpath("experiment:TFMSP-01") == Path("TFMSP") / "TFMSP-01"


def test_dest_subpath_excluded_repetition():
    assert dest_subpath("experiment:COV2D-X03") == Path("COV2D") / "COV2D-X03"


def test_dest_subpath_aggregate():
    assert dest_subpath("aggregate_analysis:TFMSP") == Path("TFMSP") / "TFMSP_aggregate"


def _sdgl_with_files(tmp_path, files):
    """Build an SDGL whose one experiment node points at real temp files.

    ``files`` = list of (rel_path, content_bytes). Returns (sdgl, node_id).
    Writes each file under tmp_path/src and records a file_location for it.
    """
    root = tmp_path / "repo"
    root.mkdir()
    sdgl = SDGL(root)
    node_id = "experiment:TFMSP-01"
    sdgl.upsert_node(node_id, "experiment", "TFM", None, None, {"code": "TFMSP"})
    src = tmp_path / "src"
    src.mkdir()
    for rel, content in files:
        disk = src / rel
        disk.parent.mkdir(parents=True, exist_ok=True)
        disk.write_bytes(content)
        st = disk.stat()
        sdgl.upsert_location(
            node_id, "gaia", str(disk), role="file",
            qualifier=("raw" if rel.startswith("raw/") else ""),
            rel_path=rel, size=st.st_size, mtime=st.st_mtime, is_dir=0,
            metadata={"name": disk.name},
        )
    return sdgl, node_id


def test_resolve_whole_node(tmp_path):
    sdgl, node_id = _sdgl_with_files(tmp_path, [("raw/a.tif", b"a"), ("analysis/b.csv", b"bb")])
    conn = sdgl.connect()
    try:
        logical = resolve_logical_files(conn, [{"node_id": node_id, "rel_path": ""}])
    finally:
        conn.close()
    assert set(rel for (_n, rel) in logical) == {"raw/a.tif", "analysis/b.csv"}


def test_resolve_folder_prefix(tmp_path):
    sdgl, node_id = _sdgl_with_files(tmp_path, [("raw/a.tif", b"a"), ("analysis/b.csv", b"bb")])
    conn = sdgl.connect()
    try:
        logical = resolve_logical_files(conn, [{"node_id": node_id, "rel_path": "raw"}])
    finally:
        conn.close()
    assert set(rel for (_n, rel) in logical) == {"raw/a.tif"}


def test_resolve_dedups_overlapping_selections(tmp_path):
    sdgl, node_id = _sdgl_with_files(tmp_path, [("raw/a.tif", b"a")])
    conn = sdgl.connect()
    try:
        logical = resolve_logical_files(conn, [
            {"node_id": node_id, "rel_path": ""},
            {"node_id": node_id, "rel_path": "raw/a.tif"},
        ])
    finally:
        conn.close()
    # One logical file, one physical copy (not two from the overlap).
    assert len(logical[(node_id, "raw/a.tif")]) == 1


def test_classify_single_copy(tmp_path):
    sdgl, node_id = _sdgl_with_files(tmp_path, [("raw/a.tif", b"a")])
    conn = sdgl.connect()
    try:
        logical = resolve_logical_files(conn, [{"node_id": node_id, "rel_path": ""}])
        result = classify(list(logical.values())[0])
    finally:
        conn.close()
    assert result["status"] == "ok"


def test_classify_missing(tmp_path):
    sdgl, node_id = _sdgl_with_files(tmp_path, [("raw/a.tif", b"a")])
    # Delete the file on disk after it was recorded.
    conn = sdgl.connect()
    try:
        row = conn.execute("SELECT path FROM file_locations WHERE rel_path = 'raw/a.tif'").fetchone()
        Path(row["path"]).unlink()
        logical = resolve_logical_files(conn, [{"node_id": node_id, "rel_path": ""}])
        result = classify(list(logical.values())[0])
    finally:
        conn.close()
    assert result["status"] == "missing"


def test_classify_identical_duplicates_collapse(tmp_path):
    sdgl, node_id = _sdgl_with_files(tmp_path, [("raw/a.tif", b"same")])
    # Record a second physical copy with identical content at a different path.
    conn = sdgl.connect()
    second = tmp_path / "mirror" / "a.tif"
    second.parent.mkdir(parents=True)
    second.write_bytes(b"same")
    st = second.stat()
    sdgl.upsert_location(node_id, "backup-drive", str(second), role="file",
                         qualifier="raw", rel_path="raw/a.tif", size=st.st_size,
                         mtime=st.st_mtime, is_dir=0, metadata={"name": "a.tif"}, conn=conn)
    conn.commit()
    try:
        logical = resolve_logical_files(conn, [{"node_id": node_id, "rel_path": ""}])
        result = classify(logical[(node_id, "raw/a.tif")])
    finally:
        conn.close()
    assert result["status"] == "ok"  # identical -> silently pick one


def test_classify_conflicting_duplicates(tmp_path):
    sdgl, node_id = _sdgl_with_files(tmp_path, [("raw/a.tif", b"version-one")])
    conn = sdgl.connect()
    second = tmp_path / "mirror" / "a.tif"
    second.parent.mkdir(parents=True)
    second.write_bytes(b"version-two-differs")
    st = second.stat()
    sdgl.upsert_location(node_id, "backup-drive", str(second), role="file",
                         qualifier="raw", rel_path="raw/a.tif", size=st.st_size,
                         mtime=st.st_mtime, is_dir=0, metadata={"name": "a.tif"}, conn=conn)
    conn.commit()
    try:
        logical = resolve_logical_files(conn, [{"node_id": node_id, "rel_path": ""}])
        result = classify(logical[(node_id, "raw/a.tif")])
    finally:
        conn.close()
    assert result["status"] == "conflict"
    assert len(result["copies"]) == 2


def test_plan_backup_counts_and_size(tmp_path):
    sdgl, node_id = _sdgl_with_files(tmp_path, [("raw/a.tif", b"aaa"), ("analysis/b.csv", b"bbbb")])
    conn = sdgl.connect()
    try:
        plan = plan_backup(conn, [{"node_id": node_id, "rel_path": ""}])
    finally:
        conn.close()
    assert plan["file_count"] == 2
    assert plan["total_size"] == 3 + 4
    assert plan["missing"] == []
    assert plan["conflicts"] == []


def test_plan_backup_reports_missing(tmp_path):
    sdgl, node_id = _sdgl_with_files(tmp_path, [("raw/a.tif", b"aaa")])
    conn = sdgl.connect()
    try:
        Path(conn.execute("SELECT path FROM file_locations LIMIT 1").fetchone()["path"]).unlink()
        plan = plan_backup(conn, [{"node_id": node_id, "rel_path": ""}])
    finally:
        conn.close()
    assert plan["file_count"] == 0
    assert plan["missing"] == [{"node_id": node_id, "rel_path": "raw/a.tif"}]


def test_run_backup_copies_by_code(tmp_path):
    sdgl, node_id = _sdgl_with_files(tmp_path, [("raw/a.tif", b"aaa"), ("analysis/b.csv", b"bbbb")])
    dest = tmp_path / "dest"
    conn = sdgl.connect()
    try:
        summary = run_backup(conn, [{"node_id": node_id, "rel_path": ""}], str(dest))
    finally:
        conn.close()
    assert summary["copied"] == 2
    assert (dest / "TFMSP" / "TFMSP-01" / "raw" / "a.tif").read_bytes() == b"aaa"
    assert (dest / "TFMSP" / "TFMSP-01" / "analysis" / "b.csv").read_bytes() == b"bbbb"


def test_run_backup_skips_missing(tmp_path):
    sdgl, node_id = _sdgl_with_files(tmp_path, [("raw/a.tif", b"aaa")])
    dest = tmp_path / "dest"
    conn = sdgl.connect()
    try:
        Path(conn.execute("SELECT path FROM file_locations LIMIT 1").fetchone()["path"]).unlink()
        summary = run_backup(conn, [{"node_id": node_id, "rel_path": ""}], str(dest))
    finally:
        conn.close()
    assert summary["copied"] == 0
    assert summary["skipped"] == [{"node_id": node_id, "rel_path": "raw/a.tif", "reason": "missing on disk"}]


def test_run_backup_applies_conflict_resolution(tmp_path):
    sdgl, node_id = _sdgl_with_files(tmp_path, [("raw/a.tif", b"version-one")])
    conn = sdgl.connect()
    second = tmp_path / "mirror" / "a.tif"
    second.parent.mkdir(parents=True)
    second.write_bytes(b"version-two-wins")
    st = second.stat()
    chosen_id = sdgl.upsert_location(node_id, "backup-drive", str(second), role="file",
                                     qualifier="raw", rel_path="raw/a.tif", size=st.st_size,
                                     mtime=st.st_mtime, is_dir=0, metadata={"name": "a.tif"}, conn=conn)
    conn.commit()
    dest = tmp_path / "dest"
    try:
        summary = run_backup(
            conn, [{"node_id": node_id, "rel_path": ""}], str(dest),
            resolutions={f"{node_id}\nraw/a.tif": chosen_id},
        )
    finally:
        conn.close()
    assert summary["copied"] == 1
    assert (dest / "TFMSP" / "TFMSP-01" / "raw" / "a.tif").read_bytes() == b"version-two-wins"


def test_run_backup_skips_unresolved_conflict(tmp_path):
    sdgl, node_id = _sdgl_with_files(tmp_path, [("raw/a.tif", b"one")])
    conn = sdgl.connect()
    second = tmp_path / "mirror" / "a.tif"
    second.parent.mkdir(parents=True)
    second.write_bytes(b"two-differs")
    st = second.stat()
    sdgl.upsert_location(node_id, "drive", str(second), role="file", qualifier="raw",
                         rel_path="raw/a.tif", size=st.st_size, mtime=st.st_mtime, is_dir=0,
                         metadata={"name": "a.tif"}, conn=conn)
    conn.commit()
    dest = tmp_path / "dest"
    try:
        summary = run_backup(conn, [{"node_id": node_id, "rel_path": ""}], str(dest))
    finally:
        conn.close()
    assert summary["copied"] == 0
    assert summary["skipped"][0]["reason"] == "unresolved conflict"


def test_run_backup_emits_progress(tmp_path):
    sdgl, node_id = _sdgl_with_files(tmp_path, [("raw/a.tif", b"aaa")])
    dest = tmp_path / "dest"
    events = []
    conn = sdgl.connect()
    try:
        run_backup(conn, [{"node_id": node_id, "rel_path": ""}], str(dest), progress=events.append)
    finally:
        conn.close()
    phases = [e["phase"] for e in events]
    assert phases[0] == "start" and phases[-1] == "done"
    assert events[-1]["summary"]["copied"] == 1


def test_backup_job_snapshot_isolation():
    job = BackupJob()
    job.update(status="running", done_files=1)
    snap = job.snapshot()
    snap["status"] = "tampered"
    assert job.snapshot()["status"] == "running"
