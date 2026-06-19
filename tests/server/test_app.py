"""End-to-end tests for the Flask app against a tiny data root."""

import sqlite3

import pytest

from eln.db import init_db
from eln.server import create_app


@pytest.fixture
def app_root(tmp_path):
    """A data root with experiments.db (one experiment, one protocol)."""
    root = tmp_path
    db = root / "experiments.db"
    init_db.init_db(db)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO experiment_codes (title, code) VALUES ('Traction Force', 'TFMSP')")
    conn.execute(
        "INSERT INTO experiments (id, experiment_type, repetition, excluded, file_path) "
        "VALUES (1, 'Traction Force', 1, 0, 'x')"
    )
    conn.execute(
        "INSERT INTO protocols (id, name, version, content, is_latest) "
        "VALUES (10, 'Gel casting', '1', '# Gel casting', 1)"
    )
    conn.commit()
    conn.close()
    (root / "reports").mkdir()
    app = create_app(root, scan_roots=[{"name": "data", "path": root / "data"}])
    app.config.update(TESTING=True)
    return root, app


@pytest.fixture
def client(app_root):
    _, app = app_root
    return app.test_client()


# --- experiments ------------------------------------------------------------

def test_list_experiments_has_experiment_id(client):
    resp = client.get("/api/experiments")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["experiment_id"] == "TFMSP-01"


def test_create_experiment_assigns_next_rep(client):
    resp = client.post("/api/experiments", json={"experiment_type": "Traction Force"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["experiment_id"] == "TFMSP-02"


def test_create_excluded_rep(client):
    resp = client.post(
        "/api/experiments",
        json={"experiment_type": "Traction Force", "repetition": "X1"},
    )
    assert resp.get_json()["experiment_id"] == "TFMSP-X01"


def test_create_new_title_needs_code(client):
    resp = client.post("/api/experiments", json={"experiment_type": "Migration"})
    assert resp.status_code == 400
    resp = client.post(
        "/api/experiments", json={"experiment_type": "Migration", "code": "MIGRA"}
    )
    assert resp.status_code == 200
    assert resp.get_json()["experiment_id"] == "MIGRA-01"


def test_update_and_delete_experiment(client):
    client.put("/api/experiments/1", json={"cell_types": "HUVEC", "tags": ["migration"]})
    got = client.get("/api/experiments/1").get_json()
    assert got["cell_types"] == "HUVEC"
    assert got["tags"] == ["migration"]
    assert client.delete("/api/experiments/1").status_code == 200
    assert client.get("/api/experiments/1").status_code == 404


# --- field values (autocomplete / fungibility) ------------------------------

def _seed_field_values(tmp_path):
    """A data root with two experiments and channels using fungible markers."""
    root = tmp_path
    db = root / "experiments.db"
    init_db.init_db(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO experiments (id, experiment_type, cell_types, microscope, file_path) "
        "VALUES (1, 'Traction Force', 'HUVEC, NIH-3T3', 'Nikon TiE2', 'a')"
    )
    conn.execute(
        "INSERT INTO experiments (id, experiment_type, cell_types, microscope, file_path) "
        "VALUES (2, 'Migration', 'HUVEC', 'Zeiss LSM', 'b')"
    )
    # Two experiments label the same dye differently: "GFP" and "488".
    conn.execute(
        "INSERT INTO experiment_channels (experiment_id, channel_order, channel_label, target, modality) "
        "VALUES (1, 1, 'Green', 'GFP', NULL)"
    )
    conn.execute(
        "INSERT INTO experiment_channels (experiment_id, channel_order, channel_label, target, modality) "
        "VALUES (2, 1, 'Green', '488', NULL)"
    )
    conn.execute(
        "INSERT INTO experiment_channels (experiment_id, channel_order, channel_label, target, modality) "
        "VALUES (1, 5, 'Brightfield', NULL, 'Phase contrast')"
    )
    conn.commit()
    conn.close()
    (root / "reports").mkdir()
    return root


def test_field_values_distinct_and_split(tmp_path):
    app = create_app(_seed_field_values(tmp_path))
    data = app.test_client().get("/api/field-values").get_json()
    assert data["experiment_type"] == ["Migration", "Traction Force"]
    # cell_types is comma-split and de-duplicated across experiments.
    assert data["cell_types"] == ["HUVEC", "NIH-3T3"]
    assert data["microscope"] == ["Nikon TiE2", "Zeiss LSM"]
    assert data["channel_modality"] == ["Phase contrast"]


def test_field_values_collapses_fungible_channels(tmp_path):
    root = _seed_field_values(tmp_path)
    app = create_app(root, channel_aliases=[["GFP", "488", "FITC"]])
    data = app.test_client().get("/api/field-values").get_json()
    # "GFP" and "488" collapse to the canonical "GFP" — one suggestion.
    assert data["channel_target"] == ["GFP"]


def test_field_values_without_aliases_keeps_variants(tmp_path):
    app = create_app(_seed_field_values(tmp_path))
    data = app.test_client().get("/api/field-values").get_json()
    assert data["channel_target"] == ["488", "GFP"]


# --- protocols & reports ----------------------------------------------------

def test_protocols_and_reports_crud(client):
    assert client.get("/api/protocols").get_json()[0]["name"] == "Gel casting"

    assert client.post(
        "/api/reports", json={"filename": "r.md", "content": "# hi"}
    ).status_code == 200
    assert client.get("/api/reports/r.md").get_json()["content"] == "# hi"
    assert client.put("/api/reports/r.md", json={"content": "# bye"}).status_code == 200
    assert client.get("/api/reports/r.md").get_json()["content"] == "# bye"
    assert client.delete("/api/reports/r.md").status_code == 200
    assert client.get("/api/reports/r.md").status_code == 404

    # A non-.md filename is rejected.
    assert client.post("/api/reports", json={"filename": "x.txt"}).status_code == 400


# --- HTML serving + overlay -------------------------------------------------

def test_index_serves_sdgl_with_overlay(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "edit-overlay.js" in html          # overlay injected
    assert '<script src="auth.js">' not in html  # auth stripped

    assert client.get("/auth.js").get_data(as_text=True).startswith("// auth disabled")
    assert client.get("/edit-overlay.js").status_code == 200


def test_generated_page_served_after_regenerate(client):
    # Not generated yet → 404.
    assert client.get("/experiments.html").status_code == 404
    assert client.post("/api/regenerate").status_code == 200
    resp = client.get("/experiments.html")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "TFMSP-01" in html
    assert "edit-overlay.js" in html  # overlay injected into generated pages too


def _seed_backup_root(tmp_path):
    """Create a data-repo root with one experiment node + one real file location.
    Returns (root, node_id, src_file)."""
    from eln.sdgl import SDGL
    root = tmp_path / "repo"
    root.mkdir()
    sdgl = SDGL(root)
    node_id = "experiment:TFMSP-01"
    sdgl.upsert_node(node_id, "experiment", "TFM", None, None, {"code": "TFMSP"})
    src = tmp_path / "src" / "raw" / "a.tif"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"hello")
    st = src.stat()
    sdgl.upsert_location(node_id, "gaia", str(src), role="file", qualifier="raw",
                         rel_path="raw/a.tif", size=st.st_size, mtime=st.st_mtime,
                         is_dir=0, metadata={"name": "a.tif"})
    return root, node_id, src


def test_backup_preview_route(tmp_path):
    from eln.server import create_app
    root, node_id, _src = _seed_backup_root(tmp_path)
    client = create_app(root).test_client()
    resp = client.post("/api/sdgl/backup/preview",
                       json={"selections": [{"node_id": node_id, "rel_path": ""}]})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["file_count"] == 1
    assert body["total_size"] == 5


def test_backup_preview_requires_selections(tmp_path):
    from eln.server import create_app
    root, _node, _src = _seed_backup_root(tmp_path)
    client = create_app(root).test_client()
    resp = client.post("/api/sdgl/backup/preview", json={"selections": []})
    assert resp.status_code == 400


def test_backup_start_and_status(tmp_path):
    from eln.server import create_app
    root, node_id, _src = _seed_backup_root(tmp_path)
    dest = tmp_path / "dest"
    app = create_app(root)
    client = app.test_client()
    resp = client.post("/api/sdgl/backup/start",
                       json={"selections": [{"node_id": node_id, "rel_path": ""}],
                             "dest": str(dest)})
    assert resp.status_code == 200
    # Worker is a daemon thread; join it via the app's job state.
    import time
    for _ in range(100):
        status = client.get("/api/sdgl/backup/status").get_json()
        if status["status"] in ("done", "error"):
            break
        time.sleep(0.02)
    assert status["status"] == "done"
    assert status["summary"]["copied"] == 1
    assert (dest / "TFMSP" / "TFMSP-01" / "raw" / "a.tif").read_bytes() == b"hello"


def test_backup_choose_folder_route(tmp_path):
    from unittest import mock
    from eln.server import create_app
    root, _node, _src = _seed_backup_root(tmp_path)
    client = create_app(root).test_client()
    fake = mock.Mock(stdout="/picked/path\n", returncode=0)
    with mock.patch("eln.server.app.subprocess.run", return_value=fake):
        resp = client.post("/api/sdgl/backup/choose-folder")
    assert resp.status_code == 200
    assert resp.get_json()["path"] == "/picked/path"


# --- plugin-driven serving --------------------------------------------------

def test_presentations_static_mount_serves_file(tmp_path):
    """The presentations plugin's StaticMount serves slide assets under its prefix."""
    from eln.server import create_app
    deck = tmp_path / "repo" / "presentations" / "2026-01-01_talk"
    deck.mkdir(parents=True)
    (deck / "index.html").write_text("<h1>Deck</h1>")
    client = create_app(tmp_path / "repo").test_client()
    resp = client.get("/presentations/2026-01-01_talk/index.html")
    assert resp.status_code == 200
    assert b"Deck" in resp.data


def test_presentations_html_is_a_generated_page(tmp_path):
    """presentations.html is served as a generated page via the plugin's nav href."""
    from eln.server import create_app
    catalog = tmp_path / "repo" / "catalog"
    catalog.mkdir(parents=True)
    (catalog / "presentations.html").write_text("<html><body>P</body></html>")
    client = create_app(tmp_path / "repo").test_client()
    resp = client.get("/presentations.html")
    assert resp.status_code == 200
    assert b"P" in resp.data
