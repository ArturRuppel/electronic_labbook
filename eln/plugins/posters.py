"""Posters — an SVG displayer plugin.

A poster is an SVG dropped into ``ROOT/posters/`` plus a display title. The
curated ``{title, file}`` list lives in ``ROOT/posters/posters.json`` (see
:mod:`eln.generators.posters`). This plugin wires up all four extension points
it needs: a nav entry, the static-page generator, a static mount serving the
SVGs at ``/posters/<file>``, and ``register_routes`` for the small JSON API the
viewer's Add button talks to.
"""

from pathlib import Path

from flask import jsonify, request

from eln.generators.posters import (
    generate_posters,
    list_poster_files,
    load_index,
    save_index,
)
from eln.plugins import NavLink, Plugin, StaticMount


def _register_routes(app, root):
    """Mount the posters JSON API: list entries + available files, add, remove."""

    @app.route("/api/posters", methods=["GET"])
    def list_posters():
        # `posters` is the curated, ordered list shown on the page; `files` is
        # every SVG present in the folder, for the Add form's file picker.
        return jsonify({"posters": load_index(root), "files": list_poster_files(root)})

    @app.route("/api/posters", methods=["POST"])
    def add_poster():
        data = request.json or {}
        title = (data.get("title") or "").strip()
        file = (data.get("file") or "").strip()
        if not title or not file:
            return jsonify({"error": "Both a title and a file are required."}), 400
        if file not in list_poster_files(root):
            return jsonify({"error": f"'{file}' is not an SVG in the posters folder."}), 400
        # One entry per file: re-adding a file updates its title in place.
        entries = [e for e in load_index(root) if e["file"] != file]
        entries.append({"title": title, "file": file})
        save_index(root, entries)
        return jsonify({"success": True, "message": "Poster added"})

    @app.route("/api/posters", methods=["DELETE"])
    def remove_poster():
        file = ((request.json or {}).get("file") or "").strip()
        if not file:
            return jsonify({"error": "A file is required."}), 400
        entries = [e for e in load_index(root) if e["file"] != file]
        save_index(root, entries)
        return jsonify({"success": True, "message": "Poster removed"})


plugin = Plugin(
    name="posters",
    nav=NavLink("Posters", "posters.html"),
    generate=generate_posters,
    static_mount=StaticMount("posters", lambda root: Path(root) / "posters"),
    register_routes=_register_routes,
)
