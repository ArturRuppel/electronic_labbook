# Viewer Editing & Admin-Panel Absorption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Absorb the separate `admin.html` editor into the main catalogue pages — create/edit happens inline via modal overlays, reports gain a git-backed version selector, documents become first-class (full CRUD), and Publish rebuilds `catalog/` so the unified view never goes stale.

**Architecture:** Backend stays Flask (`eln/server/app.py`) + the publish flow (`eln/server/publish.py`); we add `/api/documents` (cloned from the reports endpoints) and report-version endpoints (backed by git via `eln/analysis/gitref.py`), and make `publish()` call `generate_all(root)`. Frontend: a new `catalog/forms.js` module owns the create/edit forms (extracted from `admin.js`/`admin.html`) and is injected into a `<dialog>` modal by `catalog/edit-overlay.js`; `admin.html`/`admin.js` are deleted.

**Tech Stack:** Python 3 / Flask / pytest / nbformat / sqlite3; vanilla browser JS (no build step, no JS test harness — JS is verified via Python route tests + manual browser checks).

**Spec:** `docs/superpowers/specs/2026-06-24-viewer-editing-and-admin-absorption-design.md`

**Testing note (project memory):** the **parent** session runs pytest using **miniconda's** `pytest` (not the repo `.venv`); subagents cannot run Python. Run tests from the repo root.

---

## File structure

**Backend (Python):**
- `eln/server/publish.py` — `publish()` calls `generate_all(root)`; docstring fix. *(modify)*
- `eln/analysis/gitref.py` — add `file_history()` and `file_at_commit()`. *(modify)*
- `eln/server/app.py` — new `/api/documents` CRUD; new report-version endpoints; `/forms.js` route replaces `/admin.js`; module docstring update. *(modify)*

**Frontend (JS/HTML):**
- `catalog/forms.js` — modal + extracted forms (experiment/protocol/document/report). *(create)*
- `catalog/edit-overlay.js` — Edit/Add buttons call `forms.js`; documents Edit; reports version selector; post-save regenerate+reload; toolbar `+X` links removed. *(modify)*
- `catalog/edit-overlay.css` — modal + version-selector + Add-button styles. *(modify)*
- `catalog/admin.html`, `catalog/admin.js` — *(delete)*
- `.gitignore` — remove `!catalog/admin.html`. *(modify)*

**Tests:**
- `tests/server/test_publish.py` — publish rebuilds `catalog/`. *(modify)*
- `tests/analysis/test_gitref.py` — `file_history`/`file_at_commit`. *(modify; create if absent)*
- `tests/server/test_app.py` — documents CRUD, report versions, `/forms.js` + no `/admin.js`. *(modify)*

The generators need **no markup changes**: every catalogue page already exposes the hooks the overlay needs — `<div class="header"><h1>…</h1></div>` (all four pages), `#experiments-table tbody tr[data-id]`, `.protocol-group[id]`, and `.report-card[data-report-src]` (reports *and* documents both render `report-card` with `data-report-src`).

---

## Task order

Backend first (Tasks 1–5, fully TDD), then the frontend port (Tasks 6–11). Each task ends with a commit.

---

## Task 1: Publish rebuilds `catalog/`

**Files:**
- Modify: `eln/server/publish.py:1-8` (docstring), `eln/server/publish.py:71-76` (add `generate_all`)
- Test: `tests/server/test_publish.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/server/test_publish.py`:

```python
def test_publish_rebuilds_catalog(data_repo):
    # No catalog/ exists yet; publish must generate it so the local view is fresh.
    assert not (data_repo / "catalog" / "experiments.html").exists()

    result = publish(data_repo, push=False)
    assert result["success"] is True

    catalog = data_repo / "catalog"
    assert (catalog / "experiments.html").exists()
    assert (catalog / "reports.html").exists()

    # catalog/ is a derived build artifact — it must NOT be committed.
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=str(data_repo), capture_output=True, text=True
    ).stdout
    assert "catalog/experiments.html" not in tracked
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_publish.py::test_publish_rebuilds_catalog -v`
Expected: FAIL — `catalog/experiments.html` does not exist (publish doesn't generate).

- [ ] **Step 3: Implement — call `generate_all` in `publish()`**

In `eln/server/publish.py`, add the import near the top (after line 14, `from eln.db.dump_db import dump`):

```python
from eln.generators import generate_all
```

Then in `publish()`, insert the regeneration between materializing codes (step 1) and dumping (step 2). Replace lines 71-76:

```python
    # 1. Materialize derived identifiers (CODE-NN) before dumping; dates stay
    #    derived from raw-file mtimes at generation time and need no materializing.
    allocate_experiment_codes(db_path)

    # 1b. Rebuild the static catalog/ from the live DB so the local view tab is
    #     never stale after an edit-then-publish. catalog/ stays gitignored — it
    #     is a derived build artifact, not committed (see PUBLISH_PATHS below).
    generate_all(root, root / "catalog")

    # 2. Dump the database to its diffable form inside the data repo.
    dump(db_path, root / "experiments.sql")
```

- [ ] **Step 4: Fix the stale docstring**

Replace `eln/server/publish.py:1-8` (the module docstring) with:

```python
"""Publish flow for the data repo.

Unlike the original monorepo (which committed the binary ``data/experiments.db``),
the clean-rebuild publish materializes the database into its diffable form —
``experiments.sql`` via :func:`eln.db.dump` — and commits *that* to the **data**
repo, then pushes. The static ``catalog/`` is rebuilt in-process on every publish
(:func:`eln.generators.generate_all`) so the local view is never stale, but it is
intentionally **not** committed — it is a derived build artifact and stays
gitignored in the data repo.
"""
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/server/test_publish.py -v`
Expected: PASS (both the new test and the existing `test_publish_dumps_sql_and_commits`).

- [ ] **Step 6: Commit**

```bash
git add eln/server/publish.py tests/server/test_publish.py
git commit -m "feat(publish): rebuild catalog/ on every publish so the view is never stale"
```

---

## Task 2: Git helpers for file history

**Files:**
- Modify: `eln/analysis/gitref.py` (append two functions)
- Test: `tests/analysis/test_gitref.py` (create if absent)

- [ ] **Step 1: Write the failing test**

Create/append `tests/analysis/test_gitref.py`:

```python
import subprocess

from eln.analysis.gitref import file_history, file_at_commit


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)


def _repo_with_two_versions(tmp_path):
    root = tmp_path
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@e.com"], root)
    _git(["config", "user.name", "T"], root)
    f = root / "reports" / "r.md"
    f.parent.mkdir()
    f.write_text("v1\n")
    _git(["add", "."], root)
    _git(["commit", "-q", "-m", "first"], root)
    f.write_text("v2\n")
    _git(["add", "."], root)
    _git(["commit", "-q", "-m", "second"], root)
    return root


def test_file_history_newest_first(tmp_path):
    root = _repo_with_two_versions(tmp_path)
    history = file_history(root, "reports/r.md")
    assert [h["subject"] for h in history] == ["second", "first"]
    assert all(len(h["sha"]) >= 7 and h["date"] for h in history)


def test_file_at_commit_returns_old_content(tmp_path):
    root = _repo_with_two_versions(tmp_path)
    history = file_history(root, "reports/r.md")
    oldest = history[-1]["sha"]
    assert file_at_commit(root, oldest, "reports/r.md") == "v1\n"


def test_file_history_untracked_is_empty(tmp_path):
    root = _repo_with_two_versions(tmp_path)
    assert file_history(root, "reports/nope.md") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/analysis/test_gitref.py -v`
Expected: FAIL — `ImportError: cannot import name 'file_history'`.

- [ ] **Step 3: Implement — append to `eln/analysis/gitref.py`**

```python
def file_history(repo_dir, path):
    """Return ``[{sha, date, subject}, …]`` for commits that touched ``path``,
    newest first. ``path`` is relative to ``repo_dir``. Returns ``[]`` outside a
    repo, for an untracked path, or on any git error (mirrors ``_git``)."""
    out = _git(
        repo_dir,
        "log", "--follow", "--format=%H%x1f%cI%x1f%s", "--", str(path),
    )
    if not out:
        return []
    history = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            history.append({"sha": parts[0], "date": parts[1], "subject": parts[2]})
    return history


def file_at_commit(repo_dir, sha, path):
    """Return the text content of ``path`` as of commit ``sha``, or None if the
    blob is absent at that commit / git errors. ``path`` is relative to ``repo_dir``."""
    return _git(repo_dir, "show", f"{sha}:{path}")
```

Note: `_git` strips trailing whitespace, so `file_at_commit` returns content without a trailing newline-only tail; the test uses `"v1\n"` — adjust the helper to preserve exact bytes. To keep exact content, add a non-stripping variant. Replace the `file_at_commit` body with a direct call that does **not** strip:

```python
def file_at_commit(repo_dir, sha, path):
    """Return the exact text content of ``path`` as of commit ``sha`` (no
    stripping), or None if the blob is absent / git errors."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "show", f"{sha}:{path}"],
            capture_output=True, text=True,
        )
    except (OSError, ValueError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/analysis/test_gitref.py -v`
Expected: PASS (all three).

- [ ] **Step 5: Commit**

```bash
git add eln/analysis/gitref.py tests/analysis/test_gitref.py
git commit -m "feat(gitref): add file_history and file_at_commit for report versioning"
```

---

## Task 3: Report-version endpoints

**Files:**
- Modify: `eln/server/app.py` — add two routes after `update_report`/`delete_report` (after line 968), before the `# ==================== REGENERATE` block.
- Test: `tests/server/test_app.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/server/test_app.py` (a self-contained git-repo fixture, since the default `app_root` isn't a git repo):

```python
import subprocess
from eln.server import create_app


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)


def _report_repo(tmp_path):
    root = tmp_path
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@e.com"], root)
    _git(["config", "user.name", "T"], root)
    rp = root / "reports" / "r"
    rp.mkdir(parents=True)
    (rp / "r.md").write_text("# v1\n")
    _git(["add", "."], root)
    _git(["commit", "-q", "-m", "first"], root)
    (rp / "r.md").write_text("# v2\n")
    _git(["add", "."], root)
    _git(["commit", "-q", "-m", "second"], root)
    return root


def test_report_versions_lists_commits(tmp_path):
    app = create_app(_report_repo(tmp_path), scan_roots=[])
    data = app.test_client().get("/api/reports/r/r.md/versions").get_json()
    assert [v["subject"] for v in data["versions"]] == ["second", "first"]


def test_report_at_version_returns_old_content(tmp_path):
    app = create_app(_report_repo(tmp_path), scan_roots=[])
    client = app.test_client()
    versions = client.get("/api/reports/r/r.md/versions").get_json()["versions"]
    oldest = versions[-1]["sha"]
    data = client.get(f"/api/reports/r/r.md?version={oldest}").get_json()
    assert data["content"] == "# v1\n"
    assert data["version"] == oldest
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_app.py::test_report_versions_lists_commits -v`
Expected: FAIL — 404 (route not defined).

- [ ] **Step 3: Implement — add the version routes**

Add the import at the top of `eln/server/app.py` (with the other `eln.analysis` usage — they import lazily inside functions there, so do the same to match style). Insert after `delete_report` (after line 968):

```python
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
```

Then extend the existing `get_report` (lines 899-916) so a `?version=<sha>` query renders the historical blob read-only. Replace the body of `get_report` with:

```python
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
```

Note: `_resolve_report_path` resolves under `reports_path`; `root.resolve()` is the repo root, so `relative_to(root.resolve())` yields e.g. `reports/r/r.md` — the path git expects.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/server/test_app.py -k "report_versions or report_at_version" -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add eln/server/app.py tests/server/test_app.py
git commit -m "feat(api): report-version endpoints backed by git history"
```

---

## Task 4: Documents CRUD endpoints

**Files:**
- Modify: `eln/server/app.py` — bind `documents_path` (near line 116) and add a `# ==================== DOCUMENTS` block (place it right after the reports block, before `# ==================== REGENERATE`).
- Test: `tests/server/test_app.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/server/test_app.py`:

```python
def test_documents_create_get_update_delete(app_root):
    app = app_root  # fixture returns the app
    client = app.test_client()

    # create
    r = client.post("/api/documents", json={"filename": "note/note.md", "content": "# hi\n"})
    assert r.status_code == 200, r.get_json()

    # list
    listed = client.get("/api/documents").get_json()
    assert any(d["filename"] == "note/note.md" for d in listed)

    # get
    got = client.get("/api/documents/note/note.md").get_json()
    assert got["content"] == "# hi\n"

    # update
    assert client.put("/api/documents/note/note.md", json={"content": "# bye\n"}).status_code == 200
    assert client.get("/api/documents/note/note.md").get_json()["content"] == "# bye\n"

    # delete
    assert client.delete("/api/documents/note/note.md").status_code == 200
    assert client.get("/api/documents/note/note.md").status_code == 404


def test_documents_reject_escape(app_root):
    client = app_root.test_client()
    r = client.post("/api/documents", json={"filename": "../evil.md", "content": "x"})
    assert r.status_code == 400
```

The `app_root` fixture (lines 11-33) returns the app already; confirm it does. If it returns a tuple or app, adjust `app = app_root` accordingly. Ensure the fixture creates `root / "documents"` is **not** required — the create route makes parents.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_app.py::test_documents_create_get_update_delete -v`
Expected: FAIL — 404 (routes not defined).

- [ ] **Step 3: Implement — bind the documents path**

In `create_app`, near line 116 (`reports_path = root / "reports"`), add:

```python
    documents_path = root / "documents"
```

- [ ] **Step 4: Implement — the documents block**

Insert after the reports endpoints (after the version routes from Task 3), before `# ==================== REGENERATE`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/server/test_app.py -k documents -v`
Expected: PASS (both documents tests).

- [ ] **Step 6: Commit**

```bash
git add eln/server/app.py tests/server/test_app.py
git commit -m "feat(api): documents CRUD endpoints (mirrors reports, under documents/)"
```

---

## Task 5: Serve `forms.js`; retire `/admin.js`; docstring

**Files:**
- Modify: `eln/server/app.py:182-184` (route), `eln/server/app.py:8` (docstring)
- Test: `tests/server/test_app.py`

This precedes creating `forms.js` so the route exists; `forms.js` itself is built in Tasks 6–8. To let the route test pass before the file exists, create a stub `catalog/forms.js` here.

- [ ] **Step 1: Write the failing test**

Add to `tests/server/test_app.py`:

```python
def test_forms_js_served_and_admin_js_gone(app_root):
    client = app_root.test_client()
    assert client.get("/forms.js").status_code == 200
    assert client.get("/admin.js").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_app.py::test_forms_js_served_and_admin_js_gone -v`
Expected: FAIL — `/forms.js` 404, `/admin.js` 200.

- [ ] **Step 3: Create the stub module**

Create `catalog/forms.js`:

```javascript
// Inline create/edit forms, injected into a modal by edit-overlay.js.
// Populated in Tasks 6–8.
(function () {
    'use strict';
    window.elnForms = window.elnForms || {};
})();
```

- [ ] **Step 4: Replace the route**

In `eln/server/app.py`, replace lines 182-184:

```python
    @app.route("/forms.js")
    def serve_forms_js():
        return send_from_directory(str(assets), "forms.js")
```

- [ ] **Step 5: Update the module docstring**

In `eln/server/app.py:8`, change the parenthetical that lists the shipped frontend from `(sdgl.html, admin.html/js, edit-overlay.*)` to `(sdgl.html, edit-overlay.*, forms.js)`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/server/test_app.py::test_forms_js_served_and_admin_js_gone -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add eln/server/app.py catalog/forms.js tests/server/test_app.py
git commit -m "feat(server): serve forms.js, retire /admin.js route"
```

---

## Task 6: `forms.js` — modal shell + shared form helpers

The next three tasks port `catalog/admin.js` (1088 lines) into `catalog/forms.js`. The form-building logic moves **largely verbatim**; the adaptations are: (a) wrap each form in a `<dialog>` the module injects, (b) replace inline `onclick="fn()"` in the form HTML with attached listeners, (c) point the API base at same-origin (`/api`, not `http://localhost:5000/api`), and (d) reset form state each time a form opens.

**Files:**
- Modify: `catalog/forms.js`
- Modify: `catalog/edit-overlay.css` (modal styles)
- Verify: manual (no JS test harness)

- [ ] **Step 1: Add the modal shell + API base to `forms.js`**

Replace the stub body of `catalog/forms.js` with the shell (helpers from Tasks 7–8 attach to `window.elnForms`):

```javascript
// Inline create/edit forms, injected into a modal by edit-overlay.js.
(function () {
    'use strict';

    const API_BASE_URL = '/api'; // same-origin; admin.js used an absolute localhost URL.
    const forms = (window.elnForms = window.elnForms || {});

    // --- Modal shell -------------------------------------------------------
    let dlg = null;
    function modal() {
        if (dlg) return dlg;
        dlg = document.createElement('dialog');
        dlg.className = 'eln-form-modal';
        dlg.innerHTML =
            '<form method="dialog" class="eln-form-modal-close-row">' +
            '<button value="cancel" class="eln-form-modal-close" aria-label="Close">&times;</button>' +
            '</form><div class="eln-form-modal-body"></div>';
        document.body.appendChild(dlg);
        return dlg;
    }
    function openModal(innerHTML) {
        const m = modal();
        m.querySelector('.eln-form-modal-body').innerHTML = innerHTML;
        if (!m.open) m.showModal();
        return m.querySelector('.eln-form-modal-body');
    }
    function closeModal() {
        if (dlg && dlg.open) dlg.close();
    }
    forms._openModal = openModal;
    forms._closeModal = closeModal;
    forms._api = API_BASE_URL;

    // --- After-save hook: regenerate catalog then reload so the view is fresh.
    forms._afterSave = function afterSave() {
        return fetch(API_BASE_URL + '/regenerate', { method: 'POST' })
            .then(function () { window.location.reload(); });
    };

    // --- Small helpers reused by all forms ---------------------------------
    forms._postJSON = function (url, method, body) {
        return fetch(API_BASE_URL + url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); });
    };
})();
```

- [ ] **Step 2: Add modal CSS**

Append to `catalog/edit-overlay.css`:

```css
.eln-form-modal {
    width: min(900px, 92vw);
    max-height: 88vh;
    overflow: auto;
    border: none;
    border-radius: 10px;
    padding: 0;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
}
.eln-form-modal::backdrop { background: rgba(0, 0, 0, 0.45); }
.eln-form-modal-close-row { display: flex; justify-content: flex-end; }
.eln-form-modal-close {
    background: none; border: none; font-size: 1.6rem; line-height: 1;
    padding: 0.5rem 0.9rem; cursor: pointer; color: #667;
}
.eln-form-modal-body { padding: 0 1.5rem 1.5rem; }
.eln-form-modal-body h2 { margin-bottom: 1rem; }
/* Page-level Add buttons injected by edit-overlay.js */
.eln-add-btn {
    display: inline-block; margin-left: 1rem; padding: 0.4rem 0.9rem;
    background: #667eea; color: #fff; border: none; border-radius: 6px;
    font-size: 0.85rem; cursor: pointer; text-decoration: none;
}
.eln-add-btn:hover { background: #5568d3; }
```

- [ ] **Step 3: Port the shared field helpers from `admin.js`**

Into the `forms.js` IIFE, copy these functions **verbatim** from `catalog/admin.js`, then attach the ones called from injected HTML to `forms.` (so listeners can reach them):

- `loadFieldValues` (admin.js:157-176) and `loadTagSuggestions` (227-238) — change each `fetch(\`${API_BASE_URL}…\`)` to use the module's `API_BASE_URL` (already `/api`).
- Tag chips: `renderTagChips` (240-258), `addTag` (260-268), `removeTag` (269-273), `setExperimentTags` (274-282). These reference module-scoped `let currentTags = [];` — declare it at the top of the IIFE.
- Cell-type chips: `splitCellTypes` (283-289), `renderCellTypeChips` (290-308), `addCellType` (309-317), `removeCellType` (318-322), `setExperimentCellTypes` (323-329) with module-scoped `let currentCellTypes = [];`.
- Channels: `getChannelsFromForm` (330-357) and its render/populate helpers (read admin.js 357-431 and copy the channel-row builders + the code↔title autofill block: `suggestCodeForTitle`, `suggestTitleForCode`, `populateExperimentForm`, plus the `knownTitles`/`knownCodes` maps they use).

Because `removeTag`/`removeCellType` are invoked from generated chip buttons, attach them: `forms._removeTag = removeTag; forms._removeCellType = removeCellType;` and in the chip render functions replace any inline `onclick` with `remove.addEventListener('click', …)` calls (admin.js already builds chips with `addEventListener` at lines 250-256 / 299-305 — keep that pattern).

- [ ] **Step 4: Manual verify (smoke)**

Start the server (parent: `labbook admin` or the project's run command), open `http://localhost:5000/experiments.html`, open the browser console, run `window.elnForms._openModal('<h2>hi</h2>')`. Expected: a centered modal with a close button appears and closes via the ✕ / Esc.

- [ ] **Step 5: Commit**

```bash
git add catalog/forms.js catalog/edit-overlay.css
git commit -m "feat(forms): modal shell + shared field helpers ported from admin.js"
```

---

## Task 7: `forms.js` — experiment & protocol forms

**Files:**
- Modify: `catalog/forms.js`
- Verify: manual

- [ ] **Step 1: Add the experiment form template**

Copy the `<form id="experiment-form">…</form>` markup from `catalog/admin.html:603-744` into a JS template string `EXPERIMENT_FORM_HTML` at the top of the `forms.js` IIFE. Wrap it with a heading: prefix `'<h2 id="exp-form-title">Add experiment</h2>'`. Remove any inline `onkeyup="filterExperiments()"`/`onclick="…"` that referenced the admin **list** (the search box and list `#exp-search`, `#exp-loading`, `#experiments-list` belong to the admin browser, not the form — drop those list elements; keep only the form fields).

- [ ] **Step 2: Implement `openExperimentForm`**

Add to the IIFE and export:

```javascript
    forms.openExperimentForm = async function (id) {
        const body = forms._openModal(EXPERIMENT_FORM_HTML);
        body.querySelector('#exp-form-title').textContent = id ? 'Edit experiment' : 'Add experiment';
        currentTags = [];
        currentCellTypes = [];
        await loadFieldValues();
        await loadTagSuggestions();
        await loadProtocolsForCheckboxes();   // ported from admin.js (loadProtocolsForCheckboxes)
        wireCodeTitleAutofill();               // attaches input listeners (ported suggest* fns)
        renderTagChips();
        renderCellTypeChips();
        if (id) {
            const resp = await fetch(forms._api + '/experiments/' + id);
            populateExperimentForm(await resp.json());  // ported
        }
        const form = body.querySelector('#experiment-form');
        form.addEventListener('submit', async function (e) {
            e.preventDefault();
            const payload = collectExperimentPayload();   // ported from admin.js submit handler
            const method = id ? 'PUT' : 'POST';
            const url = id ? '/experiments/' + id : '/experiments';
            const { ok, body: res } = await forms._postJSON(url, method, payload);
            if (!ok) { alert(res.error || 'Save failed'); return; }
            forms._closeModal();
            await forms._afterSave();
        });
    };
```

`collectExperimentPayload`, `loadProtocolsForCheckboxes`, `wireCodeTitleAutofill`, `populateExperimentForm` are the corresponding pieces of the admin.js `#experiment-form` submit handler and helpers (admin.js ~595-700) — port them, reading field values by the same element ids (`#exp-type`, `#exp-code`, `#exp-rep`, `#exp-microscope`, `#exp-live-fixed`, `#exp-thumbnail`, `#exp-comments`, `getChannelsFromForm()`, `currentTags`, `currentCellTypes`, checked protocol checkboxes). Keep the same JSON keys the server expects (verified against `create_experiment`/`update_experiment` in app.py:600-755).

- [ ] **Step 3: Add the protocol form + `openProtocolForm`**

Copy `<form id="protocol-form">` (admin.html:750-795) into `PROTOCOL_FORM_HTML` (prefix an `<h2 id="proto-form-title">`). Implement:

```javascript
    forms.openProtocolForm = async function (id) {
        const body = forms._openModal(PROTOCOL_FORM_HTML);
        body.querySelector('#proto-form-title').textContent = id ? 'Edit protocol' : 'Add protocol';
        if (id) {
            const resp = await fetch(forms._api + '/protocols/' + id);
            populateProtocolForm(await resp.json());   // ported from admin.js
        }
        body.querySelector('#protocol-form').addEventListener('submit', async function (e) {
            e.preventDefault();
            const payload = collectProtocolPayload();  // ported
            const method = id ? 'PUT' : 'POST';
            const url = id ? '/protocols/' + id : '/protocols';
            const { ok, body: res } = await forms._postJSON(url, method, payload);
            if (!ok) { alert(res.error || 'Save failed'); return; }
            forms._closeModal();
            await forms._afterSave();
        });
    };
```

Port `populateProtocolForm`/`collectProtocolPayload` from the admin.js protocol submit handler (search admin.js for `protocol-form`), preserving the field ids and JSON keys the server's `/api/protocols` POST/PUT expect (app.py:795-851).

- [ ] **Step 4: Manual verify**

With the server running: on `experiments.html` console, run `window.elnForms.openExperimentForm()` → fill required fields → Save → modal closes, page reloads, the new row is present. Then `window.elnForms.openExperimentForm(1)` → fields prefilled → change a tag → Save → reload shows the change. Repeat for `openProtocolForm()` on `protocols.html`.

- [ ] **Step 5: Commit**

```bash
git add catalog/forms.js
git commit -m "feat(forms): inline experiment and protocol create/edit forms"
```

---

## Task 8: `forms.js` — document & report editors

**Files:**
- Modify: `catalog/forms.js`
- Verify: manual

- [ ] **Step 1: Add the report editor (`openReportEditor`)**

Copy the report editing UI from `admin.html:801-838` (the markdown `<textarea id="report-content">` group and the notebook `#report-notebook-cells` group) into `REPORT_EDITOR_HTML` (heading `<h2>Edit report</h2>`; drop the `#report-filename` create field — reports are never created here). Port the admin.js report load/save logic (admin.js ~946-1062: it GETs `/api/reports/<name>`, branches on `type === 'notebook'` to render per-cell textareas vs a single markdown textarea, and PUTs back `{content}` or `{cells:[{index,source}]}`). Implement:

```javascript
    forms.openReportEditor = async function (filename) {
        const body = forms._openModal(REPORT_EDITOR_HTML);
        const resp = await fetch(forms._api + '/reports/' + encodeURIComponent(filename));
        const data = await resp.json();
        renderReportEditor(body, data);            // ported: markdown vs notebook-cells
        body.querySelector('#report-form').addEventListener('submit', async function (e) {
            e.preventDefault();
            const payload = collectReportPayload(body, data); // {content} or {cells}
            const { ok, body: res } = await forms._postJSON(
                '/reports/' + encodeURIComponent(filename), 'PUT', payload);
            if (!ok) { alert(res.error || 'Save failed'); return; }
            forms._closeModal();
            await forms._afterSave();
        });
    };
```

- [ ] **Step 2: Add the document editor + creator (`openDocumentForm`)**

Documents reuse the report editor UI but target `/api/documents` and support **create** (new markdown file). Implement:

```javascript
    forms.openDocumentForm = async function (path) {
        // path omitted → create a new markdown document; path given → edit.
        const isCreate = !path;
        const body = forms._openModal(DOCUMENT_FORM_HTML); // report-editor markup + a filename field shown only on create
        const fnameField = body.querySelector('#doc-filename-group');
        fnameField.style.display = isCreate ? '' : 'none';
        if (!isCreate) {
            const resp = await fetch(forms._api + '/documents/' + encodeURIComponent(path));
            renderReportEditor(body, await resp.json()); // same renderer, markdown/notebook
        }
        body.querySelector('#report-form').addEventListener('submit', async function (e) {
            e.preventDefault();
            if (isCreate) {
                const filename = body.querySelector('#doc-filename').value.trim();
                const content = body.querySelector('#report-content').value;
                const { ok, body: res } = await forms._postJSON('/documents', 'POST', { filename, content });
                if (!ok) { alert(res.error || 'Create failed'); return; }
            } else {
                const payload = collectReportPayload(body, { /* type from loaded data */ });
                const { ok, body: res } = await forms._postJSON(
                    '/documents/' + encodeURIComponent(path), 'PUT', payload);
                if (!ok) { alert(res.error || 'Save failed'); return; }
            }
            forms._closeModal();
            await forms._afterSave();
        });
    };
```

`DOCUMENT_FORM_HTML` = the report-editor markup plus, above it, a create-only filename group:

```javascript
    const DOC_FILENAME_GROUP =
        '<div class="form-group full-width" id="doc-filename-group">' +
        '<label for="doc-filename">Filename (e.g. note/note.md)</label>' +
        '<input type="text" id="doc-filename" placeholder="folder/name.md" />' +
        '</div>';
```

Track the loaded document `type` (markdown/notebook) in a closure var so `collectReportPayload` builds `{content}` or `{cells}` correctly on edit.

- [ ] **Step 3: Manual verify**

Server running. On `reports.html`: `window.elnForms.openReportEditor('<existing-report-relpath>')` → edit text → Save → reload shows change (markdown) / changed markdown cell (notebook), code cells preserved. On `documents.html`: `window.elnForms.openDocumentForm()` → filename `note/note.md`, content `# Note` → Save → reload shows the new document card; then `openDocumentForm('note/note.md')` → edit → Save → reload shows the edit.

- [ ] **Step 4: Commit**

```bash
git add catalog/forms.js
git commit -m "feat(forms): inline report editor and document create/edit"
```

---

## Task 9: `edit-overlay.js` — wire buttons to `forms.js`, add Add buttons, post-save freshness

**Files:**
- Modify: `catalog/edit-overlay.js`
- Verify: manual

- [ ] **Step 1: Load `forms.js` alongside the overlay**

The server injects only `edit-overlay.css` + `edit-overlay.js` (`OVERLAY_SNIPPET`, app.py:64-67). Update `OVERLAY_SNIPPET` in `eln/server/app.py` to also load forms.js:

```python
OVERLAY_SNIPPET = '''
<link rel="stylesheet" href="/edit-overlay.css">
<script src="/forms.js"></script>
<script src="/edit-overlay.js"></script>
'''
```

(`forms.js` defines `window.elnForms` before `edit-overlay.js` runs.)

- [ ] **Step 2: Replace the toolbar `+X` links**

In `catalog/edit-overlay.js:10-18`, remove the three `+ Experiment / + Protocol / + Report` anchor lines from the toolbar `innerHTML`, leaving the label, Publish, and Export buttons:

```javascript
    toolbar.innerHTML = `
        <span class="eln-toolbar-label">Lab Notebook</span>
        <button class="eln-toolbar-btn publish" id="eln-publish-btn">Publish</button>
        <button class="eln-toolbar-btn" id="eln-export-btn">Export catalog</button>
    `;
```

- [ ] **Step 3: Experiments — Edit opens modal + page Add button**

Replace the experiments block (edit-overlay.js:118-140) so Edit calls `forms.openExperimentForm(id)` instead of navigating, and inject an Add button into the page `.header`:

```javascript
    function addPageAddButton(label, onClick) {
        var header = document.querySelector('.header');
        if (!header) return;
        var btn = document.createElement('button');
        btn.className = 'eln-add-btn';
        btn.textContent = label;
        btn.addEventListener('click', onClick);
        header.appendChild(btn);
    }

    if (page === 'experiments.html') {
        document.querySelectorAll('#experiments-table tbody tr').forEach(function (row) {
            var id = row.getAttribute('data-id');
            if (!id) return;
            var td = document.createElement('td');
            var a = document.createElement('a');
            a.className = 'eln-edit-btn';
            a.href = '#';
            a.textContent = 'Edit';
            a.addEventListener('click', function (e) { e.preventDefault(); window.elnForms.openExperimentForm(id); });
            td.appendChild(a);
            row.appendChild(td);
        });
        var headerRow = document.querySelector('#experiments-table thead tr');
        if (headerRow) { var th = document.createElement('th'); th.style.cursor = 'default'; headerRow.appendChild(th); }
        addPageAddButton('+ Add experiment', function () { window.elnForms.openExperimentForm(); });
    }
```

- [ ] **Step 4: Protocols — Edit opens modal + page Add button**

In the `protocols.html` block (edit-overlay.js:142-170), change the Edit anchor from `a.href = '/admin.html?edit=protocol&id=' + id;` to:

```javascript
            a.href = '#';
            a.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); window.elnForms.openProtocolForm(id); });
```

(keep the existing Export button) and after the `groups.forEach(...)` loop add:

```javascript
        addPageAddButton('+ Add protocol', function () { window.elnForms.openProtocolForm(); });
```

- [ ] **Step 5: Reports — Edit opens modal (no Add)**

In the `reports.html` block (edit-overlay.js:172-204), change the Edit anchor from the `/admin.html?edit=report&name=…` href to:

```javascript
                a.href = '#';
                a.addEventListener('click', function (e) { e.preventDefault(); window.elnForms.openReportEditor(filename); });
```

(Keep the Export button. No Add button for reports.)

- [ ] **Step 6: Documents — new Edit per card + page Add button**

Add a new page block (documents render `.report-card` with `data-report-src="documents/<rel>"`):

```javascript
    if (page === 'documents.html') {
        document.querySelectorAll('.report-card').forEach(function (card) {
            var src = card.getAttribute('data-report-src');
            var filename = src ? src.replace(/^documents\//, '') : null;
            if (!filename) return;
            var a = document.createElement('a');
            a.className = 'eln-edit-btn';
            a.href = '#';
            a.textContent = 'Edit';
            a.style.float = 'right';
            a.addEventListener('click', function (e) { e.preventDefault(); window.elnForms.openDocumentForm(filename); });
            card.insertBefore(a, card.firstChild);
        });
        addPageAddButton('+ Add document', function () { window.elnForms.openDocumentForm(); });
    }
```

- [ ] **Step 7: Manual verify**

Server running. Visit each page: experiments/protocols show a `+ Add …` button in the header and per-row/per-group Edit opens the modal; documents show per-card Edit + an Add button; reports show Edit (modal) and no Add. The bottom toolbar shows only Publish + Export. Every save reloads the page with the change visible (no manual regenerate, no publish needed).

- [ ] **Step 8: Commit**

```bash
git add catalog/edit-overlay.js eln/server/app.py
git commit -m "feat(overlay): inline Edit/Add via forms.js; documents support; freshness on save"
```

---

## Task 10: Reports version indicator + selector

**Files:**
- Modify: `catalog/edit-overlay.js` (reports block), `catalog/edit-overlay.css`
- Verify: manual

- [ ] **Step 1: Inject the version selector per report card**

In the `reports.html` block of `edit-overlay.js`, for each card with `data-report-src`, fetch its versions and render an indicator + dropdown. Add inside the existing `cards.forEach`:

```javascript
            // Version indicator + selector (git-backed; live-server only).
            (function (card, filename) {
                fetch('/api/reports/' + filename.split('/').map(encodeURIComponent).join('/') + '/versions')
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        var versions = (data && data.versions) || [];
                        if (versions.length === 0) return; // unpublished / not in git → no selector
                        var wrap = document.createElement('span');
                        wrap.className = 'eln-version';
                        var label = document.createElement('span');
                        label.className = 'eln-version-label';
                        label.textContent = 'Published v' + versions.length + ' · ' + versions[0].date.slice(0, 10);
                        var sel = document.createElement('select');
                        sel.className = 'eln-version-select';
                        versions.forEach(function (v, i) {
                            var opt = document.createElement('option');
                            opt.value = v.sha;
                            opt.textContent = 'v' + (versions.length - i) + ' · ' + v.date.slice(0, 10) + ' · ' + v.subject;
                            sel.appendChild(opt);
                        });
                        sel.addEventListener('click', function (e) { e.stopPropagation(); });
                        sel.addEventListener('change', function () { showReportVersion(card, filename, sel.value); });
                        wrap.appendChild(label);
                        wrap.appendChild(sel);
                        var header = card.querySelector('.report-header') || card;
                        header.appendChild(wrap);
                    })
                    .catch(function () { /* git/server unavailable → no selector */ });
            })(card, filename);
```

Add `showReportVersion` near the other helpers in `edit-overlay.js`:

```javascript
    function showReportVersion(card, filename, sha) {
        var url = '/api/reports/' + filename.split('/').map(encodeURIComponent).join('/') + '?version=' + encodeURIComponent(sha);
        fetch(url).then(function (r) { return r.json(); }).then(function (data) {
            var content = card.querySelector('.report-content');
            if (!content) return;
            // Read-only historical view. Markdown is shown verbatim in a <pre>;
            // notebooks show their raw source (no re-execution).
            var pre = document.createElement('pre');
            pre.className = 'eln-version-pre';
            pre.textContent = data.content || '';
            content.innerHTML = '';
            content.appendChild(pre);
        });
    }
```

Note: `filename` here is the report identifier relative to `reports/` (the same value computed at edit-overlay.js:180). The selector and read-only view are **live-server only**; on the static export the `/api/...` fetch fails and the `.catch` leaves the card unchanged (latest, no selector) — the intended graceful degradation.

- [ ] **Step 2: Add version-selector CSS**

Append to `catalog/edit-overlay.css`:

```css
.eln-version { margin-left: 1rem; font-size: 0.8rem; color: #556; display: inline-flex; gap: 0.4rem; align-items: center; }
.eln-version-select { font-size: 0.8rem; }
.eln-version-pre { white-space: pre-wrap; background: #f6f8fa; padding: 1rem; border-radius: 6px; overflow: auto; }
```

- [ ] **Step 3: Manual verify**

In a data repo whose `reports/` has ≥2 Publish commits touching one report: open `reports.html`, confirm the card shows `Published vN · <date>` and a dropdown of versions; selecting an older version replaces the body with that version's content read-only; the latest stays the default. In a report with no git history, no selector appears.

- [ ] **Step 4: Commit**

```bash
git add catalog/edit-overlay.js catalog/edit-overlay.css
git commit -m "feat(reports): git-backed version indicator + selector (live-server only)"
```

---

## Task 11: Delete the admin panel + final cleanup

**Files:**
- Delete: `catalog/admin.html`, `catalog/admin.js`
- Modify: `.gitignore`
- Verify: full test run + manual

- [ ] **Step 1: Delete the admin files**

```bash
git rm catalog/admin.html catalog/admin.js
```

- [ ] **Step 2: Remove the gitignore exception**

In `.gitignore`, delete the line `!catalog/admin.html` (around line 20). Leave `!catalog/sdgl.html` and `!catalog/home_template.html`.

- [ ] **Step 3: Grep for dangling references**

Run: `grep -rn "admin\.html\|admin\.js" catalog eln tests`
Expected: no matches in `catalog/edit-overlay.js`, `eln/server/app.py`, or tests. (The module docstring at app.py:8 was updated in Task 5.) Fix any stragglers.

- [ ] **Step 4: Full test suite**

Run: `pytest -q`
Expected: PASS (no regressions; new publish/gitref/app tests green).

- [ ] **Step 5: Manual end-to-end verify (the original bug)**

Server running on a real data repo:
1. Open `experiments.html`, Edit an experiment, add a tag, Save.
2. Confirm the tag appears in the view immediately (page reloaded after save — no Publish needed).
3. Click **Publish**.
4. Confirm the toast reports success and that `catalog/experiments.html` was rebuilt (the tag persists) while `git -C <root> ls-files | grep catalog` shows nothing (catalog/ uncommitted).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: delete admin panel; editing now lives inline in the viewer"
```

---

## Self-review notes (coverage map)

- Spec §1 editor architecture → Tasks 5–9 (forms.js, modal, delete admin).
- Spec §2 per-surface Edit/Add → Tasks 7 (exp/proto), 8 (doc/report), 9 (buttons).
- Spec §3 reports version selector → Tasks 2, 3, 10.
- Spec §4 freshness wiring → Task 1 (publish) + Task 6 `_afterSave` / Task 9 (inline save reload).
- Spec §5 new documents endpoints → Task 4.
- Spec §6 toolbar → Task 9 step 2.
- Out-of-scope held: export untouched; code unversioned; reports view-only (Task 10 renders read-only, no restore).
```
