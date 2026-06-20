# Static-Bundle Sharing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `labbook export` engine (with authoring-UI buttons) that writes a self-contained, relative-linked static HTML bundle of the whole catalog, a single report, or a single presentation — droppable on a Gaia share or hosted on GitHub Pages.

**Architecture:** A new `eln/share.py` orchestrates: run the existing generators unchanged, post-process each emitted page with `_staticize()` to strip three known server-only literals (Data Graph nav link, home Data Graph card, `auth.js`), then **transitively** walk every page's local `src`/`href` and copy only referenced files into the bundle (mirroring the served flat-at-root URL space, so relative links work untouched under `file://` and Pages). The CLI and a Flask endpoint are thin entry points; the authoring overlay adds buttons.

**Tech Stack:** Python stdlib (`pathlib`, `re`, `shutil`, `os`), Flask (existing server), `pytest`. **No new dependencies.**

> **Environment note (from project memory):** run tests with miniconda's `pytest`, **not** the repo `.venv`. The parent session runs pytest; subagents only write code.

---

## File structure

- **Create** `eln/share.py` — the bundle builder. Pure-ish module: `export_all`, `export_item`, and internals `_local_refs`, `_staticize`, `_strip_nav`, `_collect_assets`, `_assert_dest_outside_root`, `preview_*` helpers. One responsibility: turn a rendered catalog into a static bundle.
- **Create** `tests/test_share.py` — unit + end-to-end tests against a tiny fixture data-repo (pattern copied from `tests/generators/test_generate.py`).
- **Modify** `eln/generators/reports.py` — add `only=`/`output_name=` params to `generate_reports`; add a `data-report-src` attribute to each report card.
- **Modify** `eln/generators/presentations.py` — add a `data-pres-dir` attribute to each presentation row.
- **Modify** `eln/cli.py` — `export` subcommand.
- **Modify** `eln/server/app.py` — `POST /api/export/preview` + `/api/export/start`.
- **Modify** `catalog/edit-overlay.js` — "Export catalog" toolbar button + per-item export buttons.
- **Modify** `labbook.toml.example` — document export.
- **Modify** `docs/ROADMAP.md` — mark step 12 done at the end.

---

## Task 1: Page-staticizing + ref-extraction helpers

**Files:**
- Create: `eln/share.py`
- Test: `tests/test_share.py`

These are pure string functions — the foundation everything else builds on.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_share.py
from eln.share import _local_refs, _staticize, _strip_nav


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_share.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'eln.share'`.

- [ ] **Step 3: Write the module + helpers**

```python
# eln/share.py
"""Static-bundle export (Roadmap step 12).

Turns the rendered catalog into a self-contained, relative-linked static HTML
bundle openable via ``file://`` or hostable on GitHub Pages. Three granularities:
the whole catalog (:func:`export_all`), a single report, or a single presentation
(:func:`export_item`). The bundle mirrors the live server's flat-at-root URL space
so the generators' relative media links (``reports/…``, ``presentations/…``) work
untouched. Only files the pages actually reference are copied.
"""

import os
import re
import shutil
from pathlib import Path

# Refs we never copy: external, in-page, or inline data URIs.
_EXTERNAL = re.compile(r"^(?:[a-z]+:|//|#)")
_REF = re.compile(r'(?:src|href)="([^"]+)"')
# The three fixed, known server-only literals a generated page carries.
_AUTH_JS = re.compile(r'[ \t]*<script src="auth\.js"></script>\n?')
_NAV_GRAPH_LINK = re.compile(r'[ \t]*<a href="/">Data Graph</a>\n?')
_HOME_GRAPH_CARD = re.compile(r'[ \t]*<a href="/" class="card">.*?</a>\s*?\n?', re.DOTALL)
_NAV_BLOCK = re.compile(r'[ \t]*<div class="nav">.*?</div>\s*?\n?', re.DOTALL)


def _local_refs(html):
    """Return in-order local (copyable) ``src``/``href`` targets, query/fragment
    stripped. External (`http:`, `//`, `mailto:`, `#`, `data:`) refs are dropped."""
    out = []
    for raw in _REF.findall(html):
        if _EXTERNAL.match(raw):
            continue
        ref = raw.split("#", 1)[0].split("?", 1)[0]
        if ref:
            out.append(ref)
    return out


def _staticize(html):
    """Drop the three server-only literals from a generated page (the Data Graph
    nav link + home card, and the ``auth.js`` script). Media links are untouched."""
    html = _AUTH_JS.sub("", html)
    html = _NAV_GRAPH_LINK.sub("", html)
    html = _HOME_GRAPH_CARD.sub("", html)
    return html


def _strip_nav(html):
    """Remove the entire ``<div class="nav">…</div>`` block (single-item exports
    are standalone, with no catalog nav)."""
    return _NAV_BLOCK.sub("", html)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_share.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add eln/share.py tests/test_share.py
git commit -m "feat(share): page-staticize + local-ref helpers for static export"
```

---

## Task 2: Transitive asset collector

**Files:**
- Modify: `eln/share.py`
- Test: `tests/test_share.py`

`_collect_assets` walks pages, copies referenced in-tree files (recursing into copied HTML), and reports counts + missing refs. This is the core that makes presentations (page → `presentations/X/index.html` → `slides/*.png`) work.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_share.py
from eln.share import _collect_assets


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
    assert total == len(b"PNG") + len(b"MP4DATA") + len("<img src=\"slides/1.png\"><source src=\"movie.mp4\">")
    assert missing == []


def test_collect_assets_reports_missing(tmp_path):
    root = tmp_path / "root"; root.mkdir()
    dest = tmp_path / "dest"; dest.mkdir()
    start = [("", '<img src="reports/gone.png">')]
    seen, missing, total = _collect_assets(start, root, dest, generated=set())
    assert missing == ["reports/gone.png"]
    assert total == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_share.py::test_collect_assets_transitive_and_skips -v`
Expected: FAIL with `ImportError: cannot import name '_collect_assets'`.

- [ ] **Step 3: Implement `_collect_assets`**

```python
# add to eln/share.py
_HTML_SUFFIXES = {".html", ".htm"}


def _collect_assets(start_pages, root, dest, generated):
    """Transitively copy every referenced in-tree file into ``dest``.

    ``start_pages`` is a list of ``(base, html)`` where ``base`` is the page's
    directory relative to ``root`` (``""`` for a flat-at-root page); refs resolve
    against it. ``generated`` is the set of relpaths already produced by the
    generators (sibling pages like ``experiments.html``) — referenced but neither
    copied nor flagged missing. Recurses into any copied HTML so nested decks are
    followed. Returns ``(seen, missing, total_bytes)``.
    """
    root, dest = Path(root), Path(dest)
    seen = set(generated)
    missing, total = [], 0
    queue = list(start_pages)
    while queue:
        base, html = queue.pop()
        for ref in _local_refs(html):
            rel = os.path.normpath(os.path.join(base, ref)).replace(os.sep, "/")
            if rel in seen or rel.startswith(".."):
                continue
            seen.add(rel)
            src = root / rel
            if src.is_file():
                out = dest / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, out)
                total += src.stat().st_size
                if src.suffix.lower() in _HTML_SUFFIXES:
                    queue.append((os.path.dirname(rel), src.read_text(errors="ignore")))
            elif not (dest / rel).exists():
                missing.append(rel)
    return seen, missing, total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_share.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add eln/share.py tests/test_share.py
git commit -m "feat(share): transitive referenced-asset collector"
```

---

## Task 3: `export_all` (full catalog bundle) + destination guard

**Files:**
- Modify: `eln/share.py`
- Test: `tests/test_share.py`

- [ ] **Step 1: Add the shared fixture + failing test**

Copy the `data_root` fixture from `tests/generators/test_generate.py` into `tests/test_share.py` (it builds a tiny data-repo: `experiments.db`, an SDGL scan, two reports, one presentation). Then:

```python
# add to tests/test_share.py (plus the copied `data_root` fixture + its imports)
import pytest
from eln.share import export_all, _assert_dest_outside_root


def test_export_all_layout_and_staticized(data_root, tmp_path):
    dest = tmp_path / "bundle"
    result = export_all(data_root, dest)
    # Core pages exist, flat at root.
    for page in ["index.html", "experiments.html", "protocols.html",
                 "reports.html", "presentations.html"]:
        assert (dest / page).is_file(), page
    home = (dest / "index.html").read_text()
    assert 'href="/"' not in home and "auth.js" not in home
    nav_page = (dest / "experiments.html").read_text()
    assert ">Data Graph<" not in nav_page          # server-only link dropped
    assert ">Experiments<" in nav_page             # nav otherwise intact
    # Referenced presentation asset pulled in transitively.
    assert (dest / "presentations" / "2025-05-01_Lab_meeting"
                 / "slides" / "1.png").is_file()
    assert result["files"] >= 1 and result["bytes"] >= 1


def test_export_all_refuses_dest_inside_root(data_root):
    with pytest.raises(ValueError):
        _assert_dest_outside_root(data_root / "reports" / "out", data_root)
    # A sibling dest is fine:
    _assert_dest_outside_root(data_root.parent / "out", data_root)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_share.py::test_export_all_layout_and_staticized -v`
Expected: FAIL with `ImportError: cannot import name 'export_all'`.

- [ ] **Step 3: Implement `export_all` + guard**

```python
# add to eln/share.py
from eln.generators import generate_all

CORE_PAGES = ("index.html", "experiments.html", "protocols.html", "reports.html")


def _assert_dest_outside_root(dest, root):
    """Refuse a destination inside the data-repo tree (so an export can't land in
    reports/ and get published). Raises ValueError; otherwise returns resolved dest."""
    dest, root = Path(dest).resolve(), Path(root).resolve()
    if dest == root or root in dest.parents:
        raise ValueError(f"export destination {dest} is inside the data repo {root}")
    return dest


def export_all(root, dest):
    """Write the full static catalog bundle to ``dest``. Returns a result dict
    ``{files, bytes, missing}``."""
    root = Path(root)
    dest = _assert_dest_outside_root(dest, root)
    dest.mkdir(parents=True, exist_ok=True)

    # 1. Render every catalog page straight into the bundle (flat at root).
    written = generate_all(root, catalog_out=dest)

    # 2. Staticize each generated page in place + collect them as walk seeds.
    generated = set()
    start_pages = []
    for path in written.values():
        rel = Path(path).name
        generated.add(rel)
        text = _staticize(Path(path).read_text())
        Path(path).write_text(text)
        start_pages.append(("", text))

    # 3. Transitively copy referenced assets.
    _seen, missing, total = _collect_assets(start_pages, root, dest, generated)
    return {"files": len(_seen) - len(generated), "bytes": total, "missing": missing}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_share.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add eln/share.py tests/test_share.py
git commit -m "feat(share): export_all full-catalog bundle + dest guard"
```

---

## Task 4: Single-report render support in the reports generator

**Files:**
- Modify: `eln/generators/reports.py` (function `generate_reports`, def at line 584; report-files glob near line 603; output near line 693)
- Test: `tests/test_share.py`

`export_item` needs to render exactly one report. Add `only=` (relpath under `reports/`) and `output_name=` params without changing default behavior.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_share.py
from eln.generators.reports import generate_reports


def test_generate_reports_only_one_file(data_root, tmp_path):
    out_dir = tmp_path / "out"
    path = generate_reports(data_root, catalog_out=out_dir,
                            only="reports/weekly/tfm_progress.md",
                            output_name="one.html")
    assert path.name == "one.html"
    html = path.read_text()
    assert "TFM progress" in html        # the selected report
    assert "Random notes" not in html    # the other report excluded
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_share.py::test_generate_reports_only_one_file -v`
Expected: FAIL — `generate_reports() got an unexpected keyword argument 'only'`.

- [ ] **Step 3: Edit `generate_reports`**

Change the signature (line ~584) from:

```python
def generate_reports(root, catalog_out=None, plugins=None):
```
to:
```python
def generate_reports(root, catalog_out=None, plugins=None, only=None, output_name="reports.html"):
```

After the `report_files = sorted(...)` assignment (near line 603), add filtering:

```python
        if only is not None:
            only_path = (root / only).resolve()
            report_files = [p for p in report_files if p.resolve() == only_path]
```

Change the output filename (near line 694) from:

```python
    output_file = catalog_dir / "reports.html"
```
to:
```python
    output_file = catalog_dir / output_name
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_share.py tests/generators/test_generate.py -v`
Expected: PASS (the existing generator tests still pass — defaults unchanged).

- [ ] **Step 5: Commit**

```bash
git add eln/generators/reports.py tests/test_share.py
git commit -m "feat(reports): single-report render (only=/output_name=) for export"
```

---

## Task 5: `export_item` (single report + single presentation)

**Files:**
- Modify: `eln/share.py`
- Test: `tests/test_share.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_share.py
from eln.share import export_item


def test_export_item_report_flat_no_nav(data_root, tmp_path):
    dest = tmp_path / "rep"
    result = export_item(data_root, dest, "report", "reports/weekly/tfm_progress.md")
    index = (dest / "index.html").read_text()
    assert "TFM progress" in index
    assert '<div class="nav">' not in index   # standalone, nav stripped
    assert "auth.js" not in index
    assert result["missing"] == []


def test_export_item_presentation_mirrored_with_redirect(data_root, tmp_path):
    dest = tmp_path / "pres"
    export_item(data_root, dest, "presentation", "2025-05-01_Lab_meeting")
    redirect = (dest / "index.html").read_text()
    assert "2025-05-01_Lab_meeting/index.html" in redirect   # meta-refresh target
    assert (dest / "presentations" / "2025-05-01_Lab_meeting" / "index.html").is_file()
    assert (dest / "presentations" / "2025-05-01_Lab_meeting"
                 / "slides" / "1.png").is_file()


def test_export_item_unknown_kind(data_root, tmp_path):
    with pytest.raises(ValueError):
        export_item(data_root, tmp_path / "x", "bogus", "whatever")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_share.py::test_export_item_report_flat_no_nav -v`
Expected: FAIL — `cannot import name 'export_item'`.

- [ ] **Step 3: Implement `export_item`**

```python
# add to eln/share.py
from eln.generators.reports import generate_reports

_REDIRECT = '<!doctype html><meta charset="utf-8">' \
            '<meta http-equiv="refresh" content="0; url={target}">' \
            '<title>Redirecting…</title><a href="{target}">Open</a>\n'


def export_item(root, dest, kind, ident):
    """Write a standalone bundle for a single ``report`` or ``presentation``.

    ``ident`` is the report path relative to ``root`` (e.g.
    ``reports/weekly/tfm_progress.md``) or the presentation directory name under
    ``presentations/``. Returns ``{files, bytes, missing}``.
    """
    root = Path(root)
    dest = _assert_dest_outside_root(dest, root)
    dest.mkdir(parents=True, exist_ok=True)

    if kind == "report":
        # Render just this report flat at the bundle root as index.html, nav-less.
        path = generate_reports(root, catalog_out=dest, only=ident,
                                output_name="index.html")
        html = _strip_nav(_staticize(Path(path).read_text()))
        Path(path).write_text(html)
        _seen, missing, total = _collect_assets([("", html)], root, dest,
                                                generated={"index.html"})
    elif kind == "presentation":
        # Mirror the self-contained deck + a root redirect to it.
        rel = f"presentations/{ident}/index.html"
        src = root / rel
        if not src.is_file():
            raise ValueError(f"presentation not found: {rel}")
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        (dest / "index.html").write_text(_REDIRECT.format(target=rel))
        _seen, missing, total = _collect_assets(
            [(f"presentations/{ident}", src.read_text(errors="ignore"))],
            root, dest, generated={rel, "index.html"})
    else:
        raise ValueError(f"unknown export kind: {kind!r}")

    return {"files": len(_seen) - 1, "bytes": total, "missing": missing}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_share.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add eln/share.py tests/test_share.py
git commit -m "feat(share): export_item for single report + single presentation"
```

---

## Task 6: Determinism test (no churn)

**Files:**
- Test: `tests/test_share.py`

- [ ] **Step 1: Write the test**

```python
# add to tests/test_share.py
import filecmp


def test_export_all_deterministic(data_root, tmp_path):
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
```

- [ ] **Step 2: Run it**

Run: `pytest tests/test_share.py::test_export_all_deterministic -v`
Expected: PASS (generators already guarantee no timestamp churn; home "Last updated" is date-only, so two same-day exports match).

- [ ] **Step 3: Commit**

```bash
git add tests/test_share.py
git commit -m "test(share): export_all is byte-deterministic"
```

---

## Task 7: CLI `labbook export`

**Files:**
- Modify: `eln/cli.py` (add `cmd_export` near the other `cmd_*` funcs ~line 164; add subparser in `build_parser` ~line 229)
- Test: `tests/test_share.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_share.py
from eln.cli import build_parser, cmd_export


def test_cli_export_all(data_root, tmp_path, monkeypatch):
    dest = tmp_path / "out"
    cfg = data_root / "labbook.toml"
    monkeypatch.setenv("LABBOOK_CONFIG", str(cfg))
    args = build_parser().parse_args(["export", "--all", "--dest", str(dest)])
    rc = cmd_export(args)
    assert rc == 0
    assert (dest / "index.html").is_file()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_share.py::test_cli_export_all -v`
Expected: FAIL — `cannot import name 'cmd_export'`.

- [ ] **Step 3: Add `cmd_export` and the subparser**

Add the command function (mirrors `cmd_regenerate`'s `_load`/`_ensure_db` pattern; `_ensure_db`, `_load` already exist in `eln/cli.py`):

```python
def cmd_export(args):
    from eln.share import export_all, export_item

    config = _load(args)
    _ensure_db(config)
    if args.all:
        result = export_all(config.data_root, args.dest)
    elif args.report:
        result = export_item(config.data_root, args.dest, "report", args.report)
    elif args.presentation:
        result = export_item(config.data_root, args.dest, "presentation", args.presentation)
    else:
        print("nothing to export: pass --all, --report ID, or --presentation ID",
              file=sys.stderr)
        return 1
    print(f"Exported {result['files']} files ({result['bytes']:,} bytes) to {args.dest}")
    for rel in result["missing"]:
        print(f"  WARNING missing referenced asset (skipped): {rel}", file=sys.stderr)
    return 0
```

In `build_parser`, after the `backup` subparser block (~line 232), add:

```python
    p = sub.add_parser("export", help="write a self-contained static HTML bundle")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true", help="export the whole catalog")
    g.add_argument("--report", help="export a single report (path under reports/)")
    g.add_argument("--presentation", help="export a single presentation (dir name)")
    p.add_argument("--dest", required=True, help="output folder for the bundle")
    p.set_defaults(func=cmd_export)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_share.py tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add eln/cli.py tests/test_share.py
git commit -m "feat(cli): labbook export (--all/--report/--presentation --dest)"
```

---

## Task 8: Per-item identifiers in the report/presentation pages

**Files:**
- Modify: `eln/generators/reports.py` (report-card markup) and `eln/generators/presentations.py` (presentation row markup)
- Test: `tests/test_share.py`

The overlay's per-item Export button needs a stable id on each card/row. Emit a `data-` attribute carrying the export identifier (report relpath under `root`; presentation dir name).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_share.py
from eln.generators import generate_catalog  # noqa: F401  (ensures import path)
from eln.generators.presentations import generate_presentations


def test_report_card_has_data_src(data_root, tmp_path):
    out = tmp_path / "c"
    generate_reports(data_root, catalog_out=out)
    html = (out / "reports.html").read_text()
    assert 'data-report-src="reports/weekly/tfm_progress.md"' in html


def test_presentation_row_has_data_dir(data_root, tmp_path):
    out = tmp_path / "c"
    generate_presentations(data_root, catalog_out=out)
    html = (out / "presentations.html").read_text()
    assert 'data-pres-dir="2025-05-01_Lab_meeting"' in html
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_share.py::test_report_card_has_data_src -v`
Expected: FAIL — the attribute is absent.

- [ ] **Step 3: Add the attributes**

In `eln/generators/reports.py`, locate where each report's card `<div class="report-card">` is built (inside the `for report_file in report_files:` loop). Add the relpath as a data attribute on that opening div, e.g.:

```python
            rel_src = report_file.relative_to(root).as_posix()
            # … wherever the card opening tag is assembled:
            #   <div class="report-card" data-report-src="{rel_src}">
```
Thread `rel_src` into the card's opening-tag f-string so it becomes
`<div class="report-card" data-report-src="reports/weekly/tfm_progress.md">`.

In `eln/generators/presentations.py`, the per-presentation `<tr>` (around line 60) gains the dir name:

```python
        rows += f"""
            <tr data-pres-dir="{p['dirname']}">
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_share.py tests/generators/test_generate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add eln/generators/reports.py eln/generators/presentations.py tests/test_share.py
git commit -m "feat(generators): data- export ids on report cards + presentation rows"
```

---

## Task 9: Server export endpoints

**Files:**
- Modify: `eln/server/app.py` (add routes beside the backup routes ~line 312; reuse `request`, `jsonify`, `sys`, `subprocess` already imported)
- Test: `tests/server/test_app.py`

Two endpoints mirroring the backup flow: a **preview** (count + size + missing, no write) and a **start** (do the export). The folder picker reuses the existing `/api/sdgl/backup/choose-folder` route (no change needed).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/server/test_app.py — follow the file's existing client fixture pattern.
def test_api_export_start_all(client_and_root, tmp_path):
    client, root = client_and_root           # adapt to the fixture's actual name
    dest = tmp_path / "exp_out"
    resp = client.post("/api/export/start",
                       json={"mode": "all", "dest": str(dest)})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["files"] >= 1
    assert (dest / "index.html").is_file()
```

> If `tests/server/test_app.py` exposes the app/root under a different fixture name, use that; the assertion shape stays the same.

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/server/test_app.py -k export -v`
Expected: FAIL — 404 (route not registered).

- [ ] **Step 3: Add the routes**

In `eln/server/app.py`, just after the backup routes (~line 386), add:

```python
    @app.route("/api/export/preview", methods=["POST"])
    def api_export_preview():
        """Dry-run an export: report file count + total bytes + missing refs, and
        whether the chosen dest already holds files (overwrite warning).

        Renders into a throwaway temp dir so the count reflects the real walk; the
        temp dir is discarded. Body: {mode, id?, dest?}."""
        import tempfile
        from eln.share import export_all, export_item
        data = request.get_json(force=True) or {}
        mode = data.get("mode")
        with tempfile.TemporaryDirectory() as tmp:
            try:
                if mode == "all":
                    result = export_all(data_root, tmp)
                elif mode in ("report", "presentation"):
                    result = export_item(data_root, tmp, mode, data.get("id", ""))
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
        data = request.get_json(force=True) or {}
        mode, dest = data.get("mode"), data.get("dest")
        if not dest:
            return jsonify({"error": "no destination chosen"}), 400
        try:
            if mode == "all":
                result = export_all(data_root, dest)
            elif mode in ("report", "presentation"):
                result = export_item(data_root, dest, mode, data.get("id", ""))
            else:
                return jsonify({"error": f"bad mode: {mode}"}), 400
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(result)
```

> `data_root` is the closure variable `create_app` already uses for the other routes — confirm the exact name in `app.py` and match it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/server/test_app.py -k export -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add eln/server/app.py tests/server/test_app.py
git commit -m "feat(server): /api/export/preview + /api/export/start"
```

---

## Task 10: Authoring-overlay export buttons

**Files:**
- Modify: `catalog/edit-overlay.js`

No automated test (consistent with the repo — overlay JS is verified manually). Adds an "Export catalog" toolbar button and per-item Export buttons that call `choose-folder` then `/api/export/start`.

- [ ] **Step 1: Add an Export button to the toolbar**

In the `toolbar.innerHTML` template (line ~15), add after the Publish button:

```html
        <button class="eln-toolbar-btn" id="eln-export-btn">Export catalog</button>
```

- [ ] **Step 2: Add a shared export helper + wire the toolbar button**

After the Publish click handler (~line 66), add:

```javascript
    // --- Export (catalog or a single item): choose folder → preview → confirm → start ---
    function postJSON(url, body) {
        return fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        }).then(function(r) { return r.json(); });
    }

    function runExport(mode, id, label) {
        showToast('Choosing destination…', 'info');
        fetch('/api/sdgl/backup/choose-folder', {method: 'POST'})
            .then(function(r) { return r.json(); })
            .then(function(folder) {
                var dest = folder && folder.path;
                if (!dest) { showToast('Export cancelled.', 'info'); return; }
                return postJSON('/api/export/preview', {mode: mode, id: id, dest: dest})
                    .then(function(p) {
                        if (p.error) { showToast('Error: ' + p.error, 'error'); return; }
                        var kb = Math.round(p.bytes / 1024);
                        var msg = 'Export ' + label + ': ' + p.files + ' files (' + kb + ' KB) to ' + dest + '.';
                        if (p.dest_nonempty) { msg += '\nThe destination already contains files — overwrite?'; }
                        msg += '\n\nProceed?';
                        if (!window.confirm(msg)) { showToast('Export cancelled.', 'info'); return; }
                        showToast('Exporting ' + label + '…', 'info');
                        return postJSON('/api/export/start', {mode: mode, id: id, dest: dest})
                            .then(function(d) {
                                if (d.error) { showToast('Error: ' + d.error, 'error'); return; }
                                var done = 'Exported ' + d.files + ' files to ' + dest;
                                if (d.missing && d.missing.length) {
                                    done += ' (' + d.missing.length + ' missing asset(s) skipped)';
                                }
                                showToast(done, 'success');
                            });
                    });
            })
            .catch(function(err) { showToast('Network error: ' + err.message, 'error'); });
    }

    var exportBtn = document.getElementById('eln-export-btn');
    if (exportBtn) {
        exportBtn.addEventListener('click', function() {
            runExport('all', '', 'catalog');
        });
    }
```

> The `choose-folder` endpoint returns the chosen path; match the key the
> existing backup UI reads (`folder.path` here — confirm against the backup
> caller and align if it differs).

- [ ] **Step 3: Add per-report Export buttons**

In the `if (page === 'reports.html')` block (~line 113), inside the `cards.forEach`, after the Edit button is built, add (the card carries `data-report-src` from Task 8):

```javascript
            var src = card.getAttribute('data-report-src');
            if (src) {
                var ex = document.createElement('a');
                ex.className = 'eln-edit-btn';
                ex.textContent = 'Export';
                ex.href = '#';
                ex.style.float = 'right';
                ex.style.marginRight = '0.5rem';
                ex.addEventListener('click', function(e) {
                    e.preventDefault();
                    runExport('report', src, 'report');
                });
                card.insertBefore(ex, card.firstChild);
            }
```

- [ ] **Step 4: Add per-presentation Export buttons**

Add a new page block (presentations rows carry `data-pres-dir` from Task 8):

```javascript
    if (page === 'presentations.html') {
        var prows = document.querySelectorAll('tr[data-pres-dir]');
        prows.forEach(function(row) {
            var dir = row.getAttribute('data-pres-dir');
            var td = document.createElement('td');
            var ex = document.createElement('a');
            ex.className = 'eln-edit-btn';
            ex.textContent = 'Export';
            ex.href = '#';
            ex.addEventListener('click', function(e) {
                e.preventDefault();
                runExport('presentation', dir, 'presentation');
            });
            td.appendChild(ex);
            row.appendChild(td);
        });
    }
```

- [ ] **Step 5: Manual verification**

Run: `labbook admin` (or `python -m eln.cli admin`), open `reports.html` and `presentations.html` in the served view, confirm the **Export catalog** toolbar button and per-item **Export** buttons appear; click one, pick a temp folder, confirm the success toast and that the folder contains `index.html`.

- [ ] **Step 6: Commit**

```bash
git add catalog/edit-overlay.js
git commit -m "feat(overlay): Export catalog + per-item export buttons"
```

---

## Task 11: Docs + roadmap

**Files:**
- Modify: `labbook.toml.example`, `docs/ROADMAP.md`

- [ ] **Step 1: Document export in `labbook.toml.example`**

Append a short comment block (no required config — destination is per-call):

```toml
# Sharing / export (Roadmap step 12). `labbook export` writes a self-contained,
# relative-linked static HTML bundle you can drop on the Gaia share (open
# index.html over file://) or host on GitHub Pages — no server needed for
# viewers. Three granularities: the whole catalog (--all), a single progress
# report (--report PATH), or a single presentation (--presentation DIRNAME),
# each to a folder you pick with --dest. The authoring view (`labbook admin`)
# also exposes an "Export catalog" button plus per-item Export buttons. Export
# only produces the folder; putting it on Gaia or Pages is a manual follow-on.
# No [export] config is required.
```

- [ ] **Step 2: Mark step 12 done in `docs/ROADMAP.md`**

Update the `### 12.` heading to append `· _done_`, and update the **Next step** section's closing sentence (currently "…Sharing (Phase F, step 12) … is the remaining major work") to record that step 12 (static-bundle export — full catalog / single report / single presentation, via `labbook export` + authoring-overlay buttons, folder-only) is now done, completing the roadmap. Keep the date-style consistent with existing entries.

- [ ] **Step 3: Full test sweep**

Run: `pytest -q`
Expected: PASS (whole suite green).

- [ ] **Step 4: Commit**

```bash
git add labbook.toml.example docs/ROADMAP.md
git commit -m "docs(share): document labbook export; roadmap step 12 done"
```

---

## Self-review notes (for the implementer)

- **Confirm closure/fixture names** before editing: `data_root` (the create_app data-repo arg in `eln/server/app.py`) and the server test's client fixture name in `tests/server/test_app.py`. The plan flags both inline.
- **`choose-folder` response shape:** Task 10 assumes `{path: …}`. Check the existing backup UI caller and align the key if it differs.
- **Report-card opening tag:** Task 8 needs the exact f-string that emits `<div class="report-card">` in `reports.py`; add the attribute there rather than post-processing.
- **No new dependencies, no generator-behavior changes** for default callers — the `only=`/`output_name=` defaults and the new `data-` attributes are the only generated-output changes, and the determinism test (Task 6) guards churn.
- **`Path` in `app.py`:** the preview route's `dest_nonempty` check uses `pathlib.Path` — confirm it's already imported at the top of `eln/server/app.py` (it is used widely); add the import if absent.
- **Preview/guard lives in the UI, not the CLI:** `labbook export` is intentionally non-interactive (scriptable, like `labbook publish`) — it exports directly without a preview/confirm. The preview + overwrite-warning guard from the spec is realized in the authoring-overlay flow (choose-folder → `/api/export/preview` → `confirm()` → `/api/export/start`).
