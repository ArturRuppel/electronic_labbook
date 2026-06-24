"""Flask app factory for the local lab-notebook server.

Ported from the original ``api_server.py``. Two changes for the clean rebuild:

- the server is bound to a **data-repo root** (``create_app(root)``) instead of
  assuming code and data share one directory. Generated pages and data assets
  (reports/, presentations/, thumbnails/) live under that root; the static
  frontend (sdgl.html, admin.html/js, edit-overlay.*) ships in the *code* repo's
  ``catalog/`` and is found via ``ASSETS_DIR``;
- catalog regeneration runs the generators in-process (``generate_all``) rather
  than shelling out to ``scripts/``, and publish dumps ``experiments.sql`` to the
  data repo (see :mod:`eln.server.publish`).

The server is local-only and unauthenticated by design; ``auth.js`` (the GitLab
Pages password gate) is served as a no-op so locally edited pages never prompt.
"""

import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import nbformat
from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

from eln.channels import build_alias_map, canonical_channel
from eln.generators import generate_all
from eln.generators.reports import discover_report_files
from eln.plugins import discover_plugins, effective_scan_roots
from eln.sdgl import (
    SDGL,
    allocate_experiment_codes,
    format_experiment_id,
    hashing_options,
)
from eln.sdgl.backup import BackupJob, plan_backup, run_backup
from eln.server import publish as publish_mod
from eln.server.experiment_ids import (
    ExperimentIdError,
    attach_experiment_id,
    ensure_code_schema,
    resolve_code_for_title,
    resolve_repetition,
)

# Static frontend assets live in the code repo's catalog/ (this file is
# eln/server/app.py → parents[2] is the code-repo root).
ASSETS_DIR = Path(__file__).resolve().parents[2] / "catalog"

# Generated pages (written into the data root's catalog/) are served from there;
# everything else is a static asset served from ASSETS_DIR.
# Core generated pages. Plugin-contributed pages (e.g. presentations.html) are
# added per-app from each plugin's nav href.
CORE_GENERATED_PAGES = {
    "experiments.html",
    "protocols.html",
    "reports.html",
}

OVERLAY_SNIPPET = '''
<link rel="stylesheet" href="/edit-overlay.css">
<script src="/edit-overlay.js"></script>
'''

_AUTH_SCRIPT_RE = re.compile(r'<script\s+src=["\']auth\.js["\']\s*>\s*</script>')


def _read_notebook_markdown_cells(path):
    """Return ``[{index, source}, …]`` for the markdown cells of the notebook
    at *path*. The index is the cell's position in the full cell list, so it
    round-trips unambiguously through :func:`_apply_markdown_cell_edits`."""
    nb = nbformat.read(str(path), as_version=4)
    return [
        {"index": i, "source": cell.source}
        for i, cell in enumerate(nb.cells)
        if cell.cell_type == "markdown"
    ]


def _apply_markdown_cell_edits(path, edits):
    """Overwrite the source of the markdown cells named in *edits* (a list of
    ``{index, source}``) in the notebook at *path*, leaving code cells and all
    outputs untouched, then write it back. nbformat canonicalises formatting so
    unedited cells round-trip without churn. Raises ValueError if an index is
    out of range or does not point at a markdown cell."""
    nb = nbformat.read(str(path), as_version=4)
    for edit in edits:
        idx = edit.get("index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(nb.cells):
            raise ValueError(f"cell index out of range: {idx!r}")
        if nb.cells[idx].cell_type != "markdown":
            raise ValueError(f"cell {idx} is not a markdown cell")
        nb.cells[idx].source = edit.get("source", "")
    nbformat.write(nb, str(path))


def create_app(root, *, eln_db_path=None, sdgl_db_path=None, assets_dir=None,
               scan_roots=None, channel_aliases=None, scanner=None, timestamp=None):
    """Build the Flask app bound to data-repo ``root``.

    ``scan_roots`` is the injected list of scan-root configs (from the unified
    ``labbook.toml``); the scan route uses it instead of reading a per-repo file.
    ``channel_aliases`` is the list of channel equivalence groups (also from the
    config); it drives fungible-marker collapsing in the field-values endpoint.
    ``scanner`` is the ``[scanner]`` config table; it supplies the content-hashing
    settings used by the scan route and background scan.
    """
    root = Path(root)
    database_path = Path(eln_db_path) if eln_db_path else root / "experiments.db"
    sdgl_db_path = Path(sdgl_db_path) if sdgl_db_path else root / "sdgl.db"
    catalog_dir = root / "catalog"
    reports_path = root / "reports"
    documents_path = root / "documents"
    thumbnails_path = root / "thumbnails"
    assets = Path(assets_dir) if assets_dir else ASSETS_DIR

    app = Flask(__name__)
    CORS(app)  # Enable CORS for local development

    channel_alias_map = build_alias_map(channel_aliases)

    plugins = discover_plugins()
    # Configured scan roots plus any a plugin contributes (scan-root extension point).
    app.config["SCAN_ROOTS"] = effective_scan_roots(scan_roots, root, plugins)
    content_hash, hash_max_bytes = hashing_options(scanner)
    app.config["CONTENT_HASHING"] = content_hash
    app.config["HASH_MAX_BYTES"] = hash_max_bytes
    app.config["TIMESTAMP"] = timestamp or {}
    generated_pages = CORE_GENERATED_PAGES | {
        p.nav.href for p in plugins if p.nav and p.nav.href.endswith(".html")
    }

    # ---- helpers -----------------------------------------------------------

    def get_db():
        import sqlite3
        conn = sqlite3.connect(database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_sdgl():
        return SDGL(root, eln_db_path=database_path, sdgl_db_path=sdgl_db_path)

    backup_job = BackupJob()

    def serve_html_with_overlay(filename):
        """Serve a generated page (from the data root) or a static frontend
        asset (from the code repo) with the edit overlay injected."""
        if filename in generated_pages:
            filepath = catalog_dir / filename
        else:
            filepath = assets / filename
        if not filepath.exists():
            return "Not found", 404
        html = filepath.read_text(encoding="utf-8")
        # Strip auth.js (no password prompt locally) and inject the overlay.
        html = _AUTH_SCRIPT_RE.sub("", html)
        html = html.replace("</body>", OVERLAY_SNIPPET + "</body>")
        return Response(html, mimetype="text/html")

    # ==================== HTML SERVING WITH OVERLAY ====================

    @app.route("/")
    def serve_index():
        return serve_html_with_overlay("sdgl.html")

    @app.route("/<page>.html")
    def serve_page(page):
        return serve_html_with_overlay(f"{page}.html")

    @app.route("/edit-overlay.js")
    def serve_overlay_js():
        return send_from_directory(str(assets), "edit-overlay.js")

    @app.route("/edit-overlay.css")
    def serve_overlay_css():
        return send_from_directory(str(assets), "edit-overlay.css")

    @app.route("/admin.js")
    def serve_admin_js():
        return send_from_directory(str(assets), "admin.js")

    @app.route("/auth.js")
    def serve_auth_js_noop():
        """Serve empty auth.js so any remaining references don't 404."""
        return Response("// auth disabled locally", mimetype="application/javascript")

    @app.route("/reports/<path:filepath>")
    def serve_report_asset(filepath):
        return send_from_directory(str(reports_path), filepath, conditional=True)

    @app.route("/thumbnails/<path:filepath>")
    def serve_thumbnail_asset(filepath):
        return send_from_directory(str(thumbnails_path), filepath, conditional=True)

    # Plugin-contributed serving: static mounts (e.g. presentations slide assets)
    # plus any custom routes a plugin registers. A factory binds each mount's
    # source so the loop variable isn't captured late.
    def _make_static_handler(source_dir):
        def handler(filepath):
            return send_from_directory(str(source_dir), filepath)
        return handler

    for _plugin in plugins:
        mount = _plugin.static_mount
        if mount:
            app.add_url_rule(
                f"/{mount.url_prefix}/<path:filepath>",
                endpoint=f"plugin_static_{_plugin.name}",
                view_func=_make_static_handler(mount.source(root)),
            )
        if _plugin.register_routes:
            _plugin.register_routes(app, root)

    # ==================== SCIENTIFIC DATA GRAPH LAYER ====================

    @app.route("/api/sdgl/provenance/verify", methods=["GET"])
    def sdgl_verify_provenance():
        """Flag stamped artifacts whose on-disk content diverges from the
        hash recorded at stamp time (modified) or that are gone (missing)."""
        from eln.analysis import verify_provenance
        return jsonify(verify_provenance(root))

    @app.route("/api/sdgl/tree", methods=["GET"])
    def sdgl_tree():
        return jsonify(get_sdgl().tree())

    @app.route("/api/sdgl/open", methods=["POST"])
    def sdgl_open_location():
        data = request.json or {}
        location_id = data.get("location_id")
        if not location_id:
            return jsonify({"error": "location_id is required"}), 400

        location = get_sdgl().get_location(location_id)
        if not location:
            return jsonify({"error": "Location not found"}), 404
        if not location.get("exists_now") or not Path(location["path"]).exists():
            return jsonify({"error": "Location is missing"}), 400

        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", location["path"]])
            elif sys.platform.startswith("win"):
                subprocess.Popen(["cmd", "/c", "start", "", location["path"]], shell=False)
            else:
                subprocess.Popen(["xdg-open", location["path"]])
        except OSError as e:
            return jsonify({"error": str(e)}), 500
        return jsonify({"success": True, "message": "Opening location"})

    @app.route("/api/sdgl/scan", methods=["POST"])
    def sdgl_scan():
        data = request.json or {}
        roots = data.get("roots")
        if roots is None:
            roots = app.config["SCAN_ROOTS"]
        result = get_sdgl().scan_roots(
            roots,
            content_hash=app.config["CONTENT_HASHING"],
            hash_max_bytes=app.config["HASH_MAX_BYTES"],
        )
        if not roots:
            result["message"] = "No scan roots configured"
        return jsonify(result)

    @app.route("/api/sdgl/verify-hashes", methods=["POST"])
    def sdgl_verify_hashes():
        node_id = (request.json or {}).get("node_id")
        return jsonify(get_sdgl().verify_hashes(node_id))

    @app.route("/api/timestamp/verify", methods=["GET"])
    def timestamp_verify():
        """Verify recorded RFC 3161 tokens and whether the live snapshot is
        anchored (layer 3)."""
        from eln import timestamp as ts_mod
        cfg = ts_mod.resolve_timestamp_config(app.config.get("TIMESTAMP"))
        return jsonify(ts_mod.verify_all(root, cfg))

    @app.route("/api/sdgl/provenance/stamp", methods=["POST"])
    def sdgl_provenance_stamp():
        """Commit the checkbox-selected files (same selection model as backup).

        Treatment follows the content classification (see README):
        - ``kind="curated"`` — hand-made, irreproducible artifacts are *versioned
          like code*: the file is **copied into the data repo** under
          ``curated/<EXPERIMENT-ID>/<path-relative-to-the-experiment>`` (only the
          experiment-relative path is preserved, never the external absolute path),
          then stamped (tool/method) so the committed copy carries its provenance.
        - ``kind="derived"`` — automatic outputs stay on the filesystem and are
          recorded by reference only (the existing stamp behaviour).

        Body: {selections: [{node_id, rel_path}], kind, function?, params?,
        notebook?, tool?, method?}. Returns {stamped: [rel_path...], errors:[...]}.
        """
        from eln.analysis import stamp
        from eln.sdgl.backup import classify, resolve_logical_files

        data = request.json or {}
        selections = data.get("selections") or []
        if not selections:
            return jsonify({"error": "no selections"}), 400
        kind = data.get("kind", "curated")
        if kind not in ("derived", "curated"):
            return jsonify({"error": f"bad kind: {kind}"}), 400
        # Validate before any file is copied, so a bad request never leaves an
        # orphan copy in the data repo.
        if kind == "curated" and not (data.get("tool") and data.get("method")):
            return jsonify({"error": "curated artifacts require both tool and method"}), 400

        conn = get_sdgl().connect()
        try:
            logical = resolve_logical_files(conn, selections)
        finally:
            conn.close()
        if not logical:
            return jsonify({"error": "no files resolved from the selection"}), 400

        stamped, errors = [], []
        for (node_id, rel), copies in sorted(logical.items()):
            result = classify(copies)
            if result["status"] == "missing":
                errors.append({"node_id": node_id, "rel_path": rel, "error": "no copy on disk"})
                continue
            chosen = result.get("chosen") or result["copies"][0]
            try:
                if kind == "curated":
                    # Copy into the data repo, preserving only the path relative to
                    # the experiment ID (the selection's rel_path already is that).
                    exp_id = node_id.split(":", 1)[1]
                    dest = Path(root) / "curated" / exp_id / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(chosen["path"], dest)
                    stamp_path = dest
                else:
                    stamp_path = chosen["path"]
                record = stamp(
                    stamp_path, kind=kind, produced_by=node_id, root=root,
                    function=data.get("function"), params=data.get("params"),
                    notebook=data.get("notebook"),
                    tool=data.get("tool"), method=data.get("method"),
                )
                stamped.append(record["path"])
            except (ValueError, FileNotFoundError, OSError) as exc:
                errors.append({"node_id": node_id, "rel_path": rel, "error": str(exc)})

        status = 400 if errors and not stamped else 200
        return jsonify({"stamped": stamped, "errors": errors,
                        "count": len(stamped)}), status

    @app.route("/api/sdgl/backup/choose-folder", methods=["POST"])
    def sdgl_backup_choose_folder():
        """Open a native folder dialog in a subprocess and return the chosen path.
        Returns {"path": null} when cancelled / unavailable so the UI can fall back
        to a typed path."""
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "eln.sdgl.folder_dialog"],
                capture_output=True, text=True, timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return jsonify({"error": str(exc)}), 500
        path = (proc.stdout or "").strip()
        return jsonify({"path": path or None})

    @app.route("/api/sdgl/backup/preview", methods=["POST"])
    def sdgl_backup_preview():
        data = request.json or {}
        selections = data.get("selections") or []
        if not selections:
            return jsonify({"error": "no selections"}), 400
        conn = get_sdgl().connect()
        try:
            return jsonify(plan_backup(conn, selections))
        finally:
            conn.close()

    @app.route("/api/sdgl/backup/start", methods=["POST"])
    def sdgl_backup_start():
        data = request.json or {}
        selections = data.get("selections") or []
        dest = data.get("dest")
        resolutions = data.get("resolutions") or {}
        if not selections:
            return jsonify({"error": "no selections"}), 400
        if not dest:
            return jsonify({"error": "no destination"}), 400
        if backup_job.snapshot().get("status") == "running":
            return jsonify({"error": "a backup is already running"}), 409
        try:
            Path(dest).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return jsonify({"error": f"cannot use destination: {exc}"}), 400

        backup_job.update(status="running", done_files=0, total_files=0,
                          done_bytes=0, total_bytes=0, current=None,
                          summary=None, error=None)

        def report(event):
            if event["phase"] == "start":
                backup_job.update(total_files=event["total_files"],
                                  total_bytes=event["total_bytes"])
            elif event["phase"] == "file":
                backup_job.update(done_files=event["done_files"],
                                  total_files=event["total_files"],
                                  done_bytes=event["done_bytes"],
                                  total_bytes=event["total_bytes"],
                                  current=event["current"])
            elif event["phase"] == "done":
                backup_job.update(status="done", summary=event["summary"])

        def run():
            conn = get_sdgl().connect()
            try:
                run_backup(conn, selections, dest, resolutions=resolutions, progress=report)
            except Exception as exc:  # noqa: BLE001
                backup_job.update(status="error", error=str(exc))
            finally:
                conn.close()

        threading.Thread(target=run, name="sdgl-backup", daemon=True).start()
        return jsonify({"status": "running"})

    @app.route("/api/sdgl/backup/status", methods=["GET"])
    def sdgl_backup_status():
        return jsonify(backup_job.snapshot())

    # ==================== STATIC-BUNDLE EXPORT (step 12) ====================

    @app.route("/api/export/preview", methods=["POST"])
    def api_export_preview():
        """Dry-run an export: report file count + total bytes + missing refs, and
        whether the chosen dest already holds files (overwrite warning).

        Renders into a throwaway temp dir so the count reflects the real walk; the
        temp dir is discarded. Body: {mode: 'all'|'report'|'presentation', id?, dest?}."""
        import tempfile
        from eln.share import export_all, export_item
        data = request.json or {}
        mode = data.get("mode")
        with tempfile.TemporaryDirectory() as tmp:
            try:
                if mode == "all":
                    result = export_all(root, tmp)
                elif mode in ("report", "presentation", "protocol"):
                    result = export_item(root, tmp, mode, data.get("id", ""))
                else:
                    return jsonify({"error": f"bad mode: {mode}"}), 400
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
        dest = data.get("dest")
        result["dest_nonempty"] = bool(dest) and Path(dest).is_dir() and any(Path(dest).iterdir())
        return jsonify(result)

    @app.route("/api/export/start", methods=["POST"])
    def api_export_start():
        """Write the bundle to the chosen dest. Body adds {dest: <abs path>}."""
        from eln.share import export_all, export_item
        data = request.json or {}
        mode, dest = data.get("mode"), data.get("dest")
        if not dest:
            return jsonify({"error": "no destination chosen"}), 400
        try:
            if mode == "all":
                result = export_all(root, dest)
            elif mode in ("report", "presentation", "protocol"):
                result = export_item(root, dest, mode, data.get("id", ""))
            else:
                return jsonify({"error": f"bad mode: {mode}"}), 400
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(result)

    # ==================== EXPERIMENTS ====================

    @app.route("/api/tags", methods=["GET"])
    def list_tags():
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM tags ORDER BY name")
        tags = [row[0] for row in cursor.fetchall()]
        conn.close()
        return jsonify(tags)

    @app.route("/api/field-values", methods=["GET"])
    def field_values():
        """Distinct values per field, for autocomplete (field history).

        Suggestions reflect the whole database rather than only the rows the
        admin page has loaded. Channel targets are collapsed through the
        configured fungibility map so equivalent markers ("GFP"/"488"/"FITC")
        surface as a single canonical suggestion.
        """
        conn = get_db()
        cursor = conn.cursor()

        def _distinct(sql):
            cursor.execute(sql)
            return sorted(
                {(row[0] or "").strip() for row in cursor.fetchall() if (row[0] or "").strip()},
                key=str.lower,
            )

        experiment_type = _distinct("SELECT DISTINCT experiment_type FROM experiments")
        microscope = _distinct("SELECT DISTINCT microscope FROM experiments")
        channel_modality = _distinct("SELECT DISTINCT modality FROM experiment_channels")

        # cell_types is a comma-joined string per experiment; split into parts.
        cursor.execute("SELECT cell_types FROM experiments")
        cell_types = sorted(
            {
                part.strip()
                for (value,) in cursor.fetchall()
                for part in (value or "").split(",")
                if part.strip()
            },
            key=str.lower,
        )

        # Channel targets collapse fungible variants to their canonical label.
        cursor.execute("SELECT DISTINCT target FROM experiment_channels")
        channel_target = sorted(
            {
                canonical_channel(row[0], channel_alias_map)
                for row in cursor.fetchall()
                if canonical_channel(row[0], channel_alias_map)
            },
            key=str.lower,
        )

        conn.close()
        return jsonify({
            "experiment_type": experiment_type,
            "cell_types": cell_types,
            "microscope": microscope,
            "channel_target": channel_target,
            "channel_modality": channel_modality,
        })

    @app.route("/api/experiments", methods=["GET"])
    def list_experiments():
        conn = get_db()
        cursor = conn.cursor()
        ensure_code_schema(cursor)

        # Date is derived from files, not stored; order by id (≈ chronological).
        cursor.execute("SELECT * FROM experiments ORDER BY id DESC")
        experiments = [_row_to_dict(row) for row in cursor.fetchall()]

        for exp in experiments:
            cursor.execute(
                """
                SELECT p.id, p.name, p.version
                FROM experiment_protocols ep
                JOIN protocols p ON ep.protocol_id = p.id
                WHERE ep.experiment_id = ?
                """,
                (exp["id"],),
            )
            rows = cursor.fetchall()
            exp["protocol_ids"] = [row[0] for row in rows]
            exp["protocols"] = [
                {"id": row[0], "name": row[1], "version": row[2]} for row in rows
            ]
            exp["tags"] = _get_experiment_tags(cursor, exp["id"])
            exp["channels"] = _get_experiment_channels(cursor, exp["id"])
            attach_experiment_id(cursor, exp)

        conn.close()
        return jsonify(experiments)

    @app.route("/api/experiments/<int:exp_id>", methods=["GET"])
    def get_experiment(exp_id):
        conn = get_db()
        cursor = conn.cursor()
        ensure_code_schema(cursor)

        cursor.execute("SELECT * FROM experiments WHERE id = ?", (exp_id,))
        experiment = cursor.fetchone()
        if not experiment:
            conn.close()
            return jsonify({"error": "Experiment not found"}), 404

        exp_dict = _row_to_dict(experiment)
        cursor.execute(
            "SELECT protocol_id FROM experiment_protocols WHERE experiment_id = ?",
            (exp_id,),
        )
        exp_dict["protocol_ids"] = [row[0] for row in cursor.fetchall()]
        exp_dict["tags"] = _get_experiment_tags(cursor, exp_id)
        exp_dict["channels"] = _get_experiment_channels(cursor, exp_id)
        attach_experiment_id(cursor, exp_dict)

        conn.close()
        return jsonify(exp_dict)

    @app.route("/api/experiments", methods=["POST"])
    def create_experiment():
        import sqlite3
        data = request.json
        conn = get_db()
        cursor = conn.cursor()
        ensure_code_schema(cursor)

        title = (data.get("experiment_type") or "").strip()
        if not title:
            conn.close()
            return jsonify({"error": "Title is required to assign an experiment ID."}), 400

        try:
            code = resolve_code_for_title(cursor, title, data.get("code"))
            repetition, excluded = resolve_repetition(cursor, code, data.get("repetition"))

            # Date is intentionally not stored: always derived from the earliest
            # raw-file mtime at catalog-generation time.
            cursor.execute(
                """
                INSERT INTO experiments (
                    experiment_type, cell_types, microscope,
                    live_or_fixed, comments, file_path, thumbnail_path,
                    repetition, excluded
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    data.get("cell_types"), data.get("microscope"),
                    data.get("live_or_fixed"), data.get("comments"),
                    data.get("file_path", ""), data.get("thumbnail_path"),
                    repetition, 1 if excluded else 0,
                ),
            )
            experiment_id = cursor.lastrowid

            for protocol_id in data.get("protocol_ids", []) or []:
                cursor.execute(
                    "INSERT INTO experiment_protocols (experiment_id, protocol_id) VALUES (?, ?)",
                    (experiment_id, protocol_id),
                )
            if "tags" in data:
                _set_experiment_tags(cursor, experiment_id, data.get("tags") or [])
            if "channels" in data:
                _set_experiment_channels(cursor, experiment_id, data.get("channels") or [])

            conn.commit()
            return jsonify(
                {
                    "success": True,
                    "id": experiment_id,
                    "experiment_id": format_experiment_id(code, repetition, excluded),
                    "message": "Experiment created",
                }
            )
        except ExperimentIdError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except sqlite3.IntegrityError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        finally:
            conn.close()

    @app.route("/api/experiments/<int:exp_id>", methods=["PUT"])
    def update_experiment(exp_id):
        import sqlite3
        data = request.json
        conn = get_db()
        cursor = conn.cursor()
        ensure_code_schema(cursor)

        existing = cursor.execute(
            "SELECT experiment_type, repetition, excluded FROM experiments WHERE id = ?",
            (exp_id,),
        ).fetchone()
        if existing is None:
            conn.close()
            return jsonify({"error": "Experiment not found"}), 404

        # 'date' is not an experiment field (always derived from mtimes).
        fields = ["experiment_type", "cell_types", "microscope",
                  "live_or_fixed", "comments", "file_path", "thumbnail_path"]
        set_clauses = []
        params = []
        for field in fields:
            if field in data:
                set_clauses.append(f"{field} = ?")
                params.append(data[field])

        # Manage the CODE-NN identifier only when identity fields are touched.
        manage_id = any(key in data for key in ("experiment_type", "code", "repetition"))

        if (not set_clauses and not manage_id and "protocol_ids" not in data
                and "tags" not in data and "channels" not in data):
            conn.close()
            return jsonify({"error": "No fields to update"}), 400

        try:
            if manage_id:
                title = (data.get("experiment_type", existing["experiment_type"]) or "").strip()
                if not title:
                    raise ExperimentIdError("Title is required to assign an experiment ID.")
                code = resolve_code_for_title(cursor, title, data.get("code"))
                if "repetition" in data:
                    submitted_rep = data["repetition"]
                else:
                    # Reconstruct the existing identity as a token (e.g. "X3") so
                    # editing other fields can't silently drop the excluded marker.
                    prefix = "X" if existing["excluded"] else ""
                    existing_rep = existing["repetition"]
                    submitted_rep = f"{prefix}{existing_rep}" if existing_rep is not None else None
                repetition, excluded = resolve_repetition(
                    cursor, code, submitted_rep, exclude_id=exp_id
                )
                set_clauses.append("repetition = ?")
                params.append(repetition)
                set_clauses.append("excluded = ?")
                params.append(1 if excluded else 0)

            if set_clauses:
                params.append(datetime.now().isoformat())
                params.append(exp_id)
                query = (
                    f"UPDATE experiments SET {', '.join(set_clauses)}, "
                    "modified_at = ? WHERE id = ?"
                )
                cursor.execute(query, params)

            if "protocol_ids" in data:
                cursor.execute(
                    "DELETE FROM experiment_protocols WHERE experiment_id = ?", (exp_id,)
                )
                for protocol_id in data.get("protocol_ids", []):
                    cursor.execute(
                        "INSERT INTO experiment_protocols (experiment_id, protocol_id) "
                        "VALUES (?, ?)",
                        (exp_id, protocol_id),
                    )
            if "tags" in data:
                _set_experiment_tags(cursor, exp_id, data.get("tags") or [])
            if "channels" in data:
                _set_experiment_channels(cursor, exp_id, data.get("channels") or [])

            conn.commit()
            return jsonify({"success": True, "message": "Experiment updated"})
        except ExperimentIdError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        except sqlite3.IntegrityError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        finally:
            conn.close()

    @app.route("/api/experiments/<int:exp_id>", methods=["DELETE"])
    def delete_experiment(exp_id):
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM experiments WHERE id = ?", (exp_id,))
            conn.commit()
            if cursor.rowcount > 0:
                return jsonify({"success": True, "message": "Experiment deleted"})
            return jsonify({"error": "Experiment not found"}), 404
        finally:
            conn.close()

    # ==================== PROTOCOLS ====================

    @app.route("/api/protocols", methods=["GET"])
    def list_protocols():
        show_all = request.args.get("all", "false").lower() == "true"
        conn = get_db()
        cursor = conn.cursor()
        if show_all:
            cursor.execute("SELECT * FROM protocols ORDER BY name, created_at DESC")
        else:
            cursor.execute("SELECT * FROM protocols WHERE is_latest = 1 ORDER BY name")
        protocols = [_row_to_dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify(protocols)

    @app.route("/api/protocols/<int:protocol_id>", methods=["GET"])
    def get_protocol(protocol_id):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM protocols WHERE id = ?", (protocol_id,))
        protocol = cursor.fetchone()
        conn.close()
        if protocol:
            return jsonify(_row_to_dict(protocol))
        return jsonify({"error": "Protocol not found"}), 404

    @app.route("/api/protocols", methods=["POST"])
    def create_protocol():
        import sqlite3
        data = request.json
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE protocols SET is_latest = 0 WHERE name = ?", (data["name"],))
            cursor.execute(
                """
                INSERT INTO protocols (name, version, description, content, file_path, is_latest)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (
                    data["name"], data["version"], data.get("description"),
                    data.get("content"), data.get("file_path"),
                ),
            )
            protocol_id = cursor.lastrowid
            conn.commit()
            return jsonify({"success": True, "id": protocol_id, "message": "Protocol created"})
        except sqlite3.IntegrityError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        finally:
            conn.close()

    @app.route("/api/protocols/<int:protocol_id>", methods=["PUT"])
    def update_protocol(protocol_id):
        import sqlite3
        data = request.json
        conn = get_db()
        cursor = conn.cursor()
        fields = ["name", "version", "description", "content", "file_path"]
        set_clauses = []
        params = []
        for field in fields:
            if field in data:
                set_clauses.append(f"{field} = ?")
                params.append(data[field])
        if not set_clauses:
            conn.close()
            return jsonify({"error": "No fields to update"}), 400
        params.append(protocol_id)
        query = f"UPDATE protocols SET {', '.join(set_clauses)} WHERE id = ?"
        try:
            cursor.execute(query, params)
            conn.commit()
            if cursor.rowcount > 0:
                return jsonify({"success": True, "message": "Protocol updated"})
            return jsonify({"error": "Protocol not found"}), 404
        except sqlite3.IntegrityError as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 400
        finally:
            conn.close()

    @app.route("/api/protocols/<int:protocol_id>", methods=["DELETE"])
    def delete_protocol(protocol_id):
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM protocols WHERE id = ?", (protocol_id,))
            conn.commit()
            if cursor.rowcount > 0:
                return jsonify({"success": True, "message": "Protocol deleted"})
            return jsonify({"error": "Protocol not found"}), 404
        finally:
            conn.close()

    # ==================== PROGRESS REPORTS ====================

    def _resolve_report_path(filename):
        """Resolve a report identifier (a path relative to reports/, e.g.
        ``foo/foo.md``) to an absolute path, refusing anything that escapes
        reports/ via ``..`` or an absolute path. Returns None if unsafe."""
        candidate = (reports_path / filename).resolve()
        root = reports_path.resolve()
        if candidate != root and root not in candidate.parents:
            return None
        return candidate

    @app.route("/api/reports", methods=["GET"])
    def list_reports():
        reports_path.mkdir(exist_ok=True)
        # Reports are organised one folder per report, so discovery recurses and
        # the identifier is the path relative to reports/ (not just the basename),
        # which is what the GET/PUT/DELETE routes below expect. Notebooks are
        # listed too: their markdown (text) cells are editable in the admin panel,
        # while code cells and outputs stay read-only.
        reports = []
        for report_file in discover_report_files(reports_path, suffixes=(".md", ".ipynb")):
            stat = report_file.stat()
            reports.append(
                {
                    "filename": report_file.relative_to(reports_path).as_posix(),
                    "type": "notebook" if report_file.suffix == ".ipynb" else "markdown",
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "size": stat.st_size,
                }
            )
        reports.sort(key=lambda x: x["modified"], reverse=True)
        return jsonify(reports)

    @app.route("/api/reports/<path:filename>", methods=["GET"])
    def get_report(filename):
        report_path = _resolve_report_path(filename)
        if report_path is None or not report_path.exists() or not report_path.is_file():
            return jsonify({"error": "Report not found"}), 404

        version = request.args.get("version")
        if version:
            # Historical, read-only view from git. For notebooks we hand back the
            # raw .ipynb text (the UI shows it read-only); markdown comes back as-is.
            from eln.analysis.gitref import file_at_commit
            rel = report_path.relative_to(root.resolve()).as_posix()
            content = file_at_commit(root, version, rel)
            if content is None:
                return jsonify({"error": "Version not found"}), 404
            kind = "notebook" if report_path.suffix == ".ipynb" else "markdown"
            return jsonify({"filename": filename, "type": kind,
                            "version": version, "content": content})

        # A notebook returns its markdown cells (text only) for per-cell editing;
        # code cells and outputs are never sent and stay untouched on save.
        if report_path.suffix == ".ipynb":
            try:
                cells = _read_notebook_markdown_cells(report_path)
            except Exception as e:  # noqa: BLE001 - malformed notebook → 400 to the UI
                return jsonify({"error": f"Could not read notebook: {e}"}), 400
            return jsonify({"filename": filename, "type": "notebook", "cells": cells})
        try:
            content = report_path.read_text(encoding="utf-8")
            return jsonify({"filename": filename, "type": "markdown", "content": content})
        except OSError as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/reports", methods=["POST"])
    def create_report():
        data = request.json
        filename = data.get("filename")
        content = data.get("content", "")
        if not filename or not filename.endswith(".md"):
            return jsonify({"error": "Invalid filename (must end with .md)"}), 400
        report_path = _resolve_report_path(filename)
        if report_path is None:
            return jsonify({"error": "Invalid filename"}), 400
        if report_path.exists():
            return jsonify({"error": "Report already exists"}), 400
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(content, encoding="utf-8")
            return jsonify({"success": True, "message": "Report created", "filename": filename})
        except OSError as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/reports/<path:filename>", methods=["PUT"])
    def update_report(filename):
        data = request.json or {}
        report_path = _resolve_report_path(filename)
        if report_path is None or not report_path.exists():
            return jsonify({"error": "Report not found"}), 404
        # Notebook edits carry only the changed markdown cells ({index, source});
        # apply them in place so code cells and outputs are preserved verbatim.
        if report_path.suffix == ".ipynb":
            try:
                _apply_markdown_cell_edits(report_path, data.get("cells", []))
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            except Exception as e:  # noqa: BLE001 - malformed notebook → surface to UI
                return jsonify({"error": f"Could not write notebook: {e}"}), 500
            return jsonify({"success": True, "message": "Report updated"})
        try:
            report_path.write_text(data.get("content", ""), encoding="utf-8")
            return jsonify({"success": True, "message": "Report updated"})
        except OSError as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/reports/<path:filename>", methods=["DELETE"])
    def delete_report(filename):
        report_path = _resolve_report_path(filename)
        if report_path is None or not report_path.exists():
            return jsonify({"error": "Report not found"}), 404
        try:
            report_path.unlink()
            return jsonify({"success": True, "message": "Report deleted"})
        except OSError as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/reports/<path:filename>/versions", methods=["GET"])
    def report_versions(filename):
        """List git commits that touched this report file (newest first). Each
        version is a Publish commit. Empty list outside a repo / for an untracked
        file — the UI then simply shows no selector."""
        from eln.analysis.gitref import file_history
        report_path = _resolve_report_path(filename)
        if report_path is None:
            return jsonify({"error": "Invalid filename"}), 400
        rel = report_path.relative_to(root.resolve()).as_posix()
        return jsonify({"versions": file_history(root, rel)})

    # ==================== DOCUMENTS ====================
    # Documents are freeform, series-less write-ups stored as files under
    # ROOT/documents/ (markdown or notebook), structurally identical to reports.
    # These routes mirror the report routes, pointed at documents_path.

    def _resolve_document_path(filename):
        """Resolve a document identifier (path relative to documents/) to an
        absolute path, refusing anything that escapes documents/. None if unsafe."""
        candidate = (documents_path / filename).resolve()
        base = documents_path.resolve()
        if candidate != base and base not in candidate.parents:
            return None
        return candidate

    @app.route("/api/documents", methods=["GET"])
    def list_documents():
        documents_path.mkdir(exist_ok=True)
        documents = []
        for doc_file in discover_report_files(documents_path, suffixes=(".md", ".ipynb")):
            stat = doc_file.stat()
            documents.append({
                "filename": doc_file.relative_to(documents_path).as_posix(),
                "type": "notebook" if doc_file.suffix == ".ipynb" else "markdown",
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "size": stat.st_size,
            })
        documents.sort(key=lambda x: x["modified"], reverse=True)
        return jsonify(documents)

    @app.route("/api/documents/<path:filename>", methods=["GET"])
    def get_document(filename):
        doc_path = _resolve_document_path(filename)
        if doc_path is None or not doc_path.exists() or not doc_path.is_file():
            return jsonify({"error": "Document not found"}), 404
        if doc_path.suffix == ".ipynb":
            try:
                cells = _read_notebook_markdown_cells(doc_path)
            except Exception as e:  # noqa: BLE001
                return jsonify({"error": f"Could not read notebook: {e}"}), 400
            return jsonify({"filename": filename, "type": "notebook", "cells": cells})
        try:
            content = doc_path.read_text(encoding="utf-8")
            return jsonify({"filename": filename, "type": "markdown", "content": content})
        except OSError as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/documents", methods=["POST"])
    def create_document():
        data = request.json or {}
        filename = data.get("filename")
        content = data.get("content", "")
        if not filename or not filename.endswith(".md"):
            return jsonify({"error": "Invalid filename (must end with .md)"}), 400
        doc_path = _resolve_document_path(filename)
        if doc_path is None:
            return jsonify({"error": "Invalid filename"}), 400
        if doc_path.exists():
            return jsonify({"error": "Document already exists"}), 400
        try:
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text(content, encoding="utf-8")
            return jsonify({"success": True, "message": "Document created", "filename": filename})
        except OSError as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/documents/<path:filename>", methods=["PUT"])
    def update_document(filename):
        data = request.json or {}
        doc_path = _resolve_document_path(filename)
        if doc_path is None or not doc_path.exists():
            return jsonify({"error": "Document not found"}), 404
        if doc_path.suffix == ".ipynb":
            try:
                _apply_markdown_cell_edits(doc_path, data.get("cells", []))
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            except Exception as e:  # noqa: BLE001
                return jsonify({"error": f"Could not write notebook: {e}"}), 500
            return jsonify({"success": True, "message": "Document updated"})
        try:
            doc_path.write_text(data.get("content", ""), encoding="utf-8")
            return jsonify({"success": True, "message": "Document updated"})
        except OSError as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/documents/<path:filename>", methods=["DELETE"])
    def delete_document(filename):
        doc_path = _resolve_document_path(filename)
        if doc_path is None or not doc_path.exists():
            return jsonify({"error": "Document not found"}), 404
        try:
            doc_path.unlink()
            return jsonify({"success": True, "message": "Document deleted"})
        except OSError as e:
            return jsonify({"error": str(e)}), 500

    # ==================== REGENERATE CATALOGS ====================

    @app.route("/api/regenerate", methods=["POST"])
    def regenerate_catalogs():
        """Regenerate all catalog HTML files in-process."""
        try:
            generate_all(root, catalog_dir)
            return jsonify({"success": True, "message": "Catalogs regenerated successfully"})
        except Exception as e:  # noqa: BLE001 - surface any generator failure to the UI
            return jsonify({"error": f"Failed to regenerate catalogs: {e}"}), 500

    # ==================== PUBLISH (DUMP + COMMIT + PUSH) ====================

    @app.route("/api/publish", methods=["POST"])
    def publish_route():
        """Dump experiments.sql to the data repo, commit, and push."""
        result = publish_mod.publish(root, eln_db_path=database_path)
        status = 500 if "error" in result and "success" not in result else 200
        return jsonify(result), status

    # ---- module-level helpers bound per-request ----------------------------

    def start_background_scan():
        """Start one SDGL scan over the injected scan roots without blocking
        startup. The caller decides whether to invoke this (``labbook admin
        --scan``); a no-op when no scan roots are configured."""
        roots = app.config["SCAN_ROOTS"]
        if not roots:
            return
        if database_path.exists():
            allocate_experiment_codes(database_path)

        def run_scan():
            try:
                get_sdgl().scan_roots(
                    roots,
                    content_hash=app.config["CONTENT_HASHING"],
                    hash_max_bytes=app.config["HASH_MAX_BYTES"],
                )
            except Exception as e:  # noqa: BLE001
                print(f"SDGL startup scan failed: {e}")

        threading.Thread(target=run_scan, name="sdgl-startup-scan", daemon=True).start()

    app.start_background_scan = start_background_scan
    return app


# ==================== row / tag / channel helpers ====================

def _row_to_dict(row):
    """Convert a sqlite3.Row to a dict, decoding bytes to UTF-8."""
    if row is None:
        return None
    result = {}
    for key in row.keys():
        value = row[key]
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        result[key] = value
    return result


def _get_experiment_tags(cursor, experiment_id):
    cursor.execute(
        """
        SELECT t.name FROM tags t
        JOIN experiment_tags et ON et.tag_id = t.id
        WHERE et.experiment_id = ?
        ORDER BY t.name
        """,
        (experiment_id,),
    )
    return [row[0] for row in cursor.fetchall()]


def _set_experiment_tags(cursor, experiment_id, tags):
    """Upsert tag names and rewrite the experiment's tag rows to match."""
    names = []
    seen = set()
    for raw in tags:
        name = (raw or "").strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            names.append(name)

    tag_ids = []
    for name in names:
        cursor.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
        cursor.execute("SELECT id FROM tags WHERE name = ?", (name,))
        tag_ids.append(cursor.fetchone()[0])

    cursor.execute("DELETE FROM experiment_tags WHERE experiment_id = ?", (experiment_id,))
    for tag_id in tag_ids:
        cursor.execute(
            "INSERT OR IGNORE INTO experiment_tags (experiment_id, tag_id) VALUES (?, ?)",
            (experiment_id, tag_id),
        )


def _get_experiment_channels(cursor, experiment_id):
    cursor.execute(
        """
        SELECT channel_order, channel_label, target, modality
        FROM experiment_channels
        WHERE experiment_id = ?
        ORDER BY channel_order
        """,
        (experiment_id,),
    )
    return [
        {
            "channel_order": row[0],
            "channel_label": row[1],
            "target": row[2],
            "modality": row[3],
        }
        for row in cursor.fetchall()
    ]


def _set_experiment_channels(cursor, experiment_id, channels):
    """Rewrite an experiment's channel rows. Empty channels are dropped."""
    cursor.execute("DELETE FROM experiment_channels WHERE experiment_id = ?", (experiment_id,))
    for ch in channels or []:
        target = (ch.get("target") or "").strip()
        modality = (ch.get("modality") or "").strip()
        # Skip blank rows: fluorescence with no target, or brightfield with no modality.
        if not target and not modality:
            continue
        cursor.execute(
            """
            INSERT INTO experiment_channels
                (experiment_id, channel_order, channel_label, target, modality)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                experiment_id,
                ch.get("channel_order"),
                (ch.get("channel_label") or "").strip() or None,
                target or None,
                modality or None,
            ),
        )
