# Unified `labbook` CLI + Config Unification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `python -m eln.*` entry points with one installable `labbook` command, and unify `sdgl.toml` + the data-repo pointer into a single gitignored `labbook.toml` in the code repo.

**Architecture:** A new `eln/config.py` loads the unified config (discovered from the package's code-repo checkout, overridable by `--config`/`LABBOOK_CONFIG`/`--root`/`ELN_ROOT`) into a `Config` dataclass. A new `eln/cli.py` argparse dispatcher offers `admin`, `scan`, `regenerate`, `rebuild`, `publish`, `backup`, each calling existing library functions. The engine and server stop reading `sdgl.toml` directly; scan config is injected.

**Tech Stack:** Python 3.9+, argparse, `tomllib`/`tomli`, Flask (existing), pytest.

**Spec:** `docs/superpowers/specs/2026-06-19-labbook-cli-design.md`

---

## File Structure

- **Create** `eln/config.py` — config discovery + `load_config` + `Config` dataclass.
- **Create** `eln/cli.py` — argparse dispatcher + subcommand handlers + small helpers (`_ensure_db`).
- **Create** `labbook.toml.example` — committed template (replaces `sdgl.toml.example`).
- **Create** `tests/test_config.py`, `tests/test_cli.py`.
- **Modify** `pyproject.toml` — add `[project.scripts] labbook = "eln.cli:main"`.
- **Modify** `.gitignore` — ignore `labbook.toml`; drop the `sdgl.toml` line.
- **Modify** `eln/sdgl/engine.py` — add `progress` callback to `scan_roots`; the module-level scan helper reads `load_config`.
- **Modify** `eln/server/app.py` — `create_app` takes injected scan config; scan route uses it.
- **Modify** `eln/server/publish.py` — add the >90 MB staged-file guardrail + repo-size report.
- **Delete** `eln/server/__main__.py`, `eln/generators/__main__.py`, `sdgl.toml.example`.
- **Modify** `tests/server/test_app.py`, `tests/sdgl/test_scan.py`, `tests/generators/test_generate.py` — migrate `sdgl.toml` fixtures to the new config/DI.

---

## Task 1: `eln/config.py` — unified config loader

**Files:**
- Create: `eln/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
import os
import pytest
from pathlib import Path

from eln.config import Config, find_config_path, load_config


def _write_config(tmp_path, data_root, extra=""):
    cfg = tmp_path / "labbook.toml"
    cfg.write_text(
        f'data_root = "{data_root}"\n\n'
        '[scanner]\nrun_on_startup = false\n\n'
        '[[scan_roots]]\nname = "data"\npath = "data"\n' + extra,
        encoding="utf-8",
    )
    return cfg


def test_load_config_resolves_data_root_and_relative_scan_roots(tmp_path):
    data = tmp_path / "data-repo"
    data.mkdir()
    cfg = _write_config(tmp_path, data)
    c = load_config(cfg)
    assert isinstance(c, Config)
    assert c.data_root == data.resolve()
    assert c.scan_roots[0]["name"] == "data"
    # relative scan-root path resolves against data_root
    assert c.scan_roots[0]["path"] == (data / "data").resolve()


def test_absolute_scan_root_is_left_absolute(tmp_path):
    data = tmp_path / "data-repo"
    data.mkdir()
    ext = tmp_path / "external"
    cfg = _write_config(
        tmp_path, data,
        extra=f'\n[[scan_roots]]\nname = "ext"\npath = "{ext}"\n',
    )
    c = load_config(cfg)
    assert c.scan_roots[1]["path"] == ext.resolve()


def test_root_override_beats_config(tmp_path):
    data = tmp_path / "data-repo"
    other = tmp_path / "other"
    other.mkdir()
    cfg = _write_config(tmp_path, data)
    c = load_config(cfg, root_override=str(other))
    assert c.data_root == other.resolve()


def test_env_root_beats_config_but_not_override(tmp_path, monkeypatch):
    data = tmp_path / "data-repo"
    env_root = tmp_path / "env"
    env_root.mkdir()
    cli_root = tmp_path / "cli"
    cli_root.mkdir()
    cfg = _write_config(tmp_path, data)
    monkeypatch.setenv("ELN_ROOT", str(env_root))
    assert load_config(cfg).data_root == env_root.resolve()
    assert load_config(cfg, root_override=str(cli_root)).data_root == cli_root.resolve()


def test_missing_config_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.toml")


def test_no_data_root_raises(tmp_path):
    cfg = tmp_path / "labbook.toml"
    cfg.write_text("[scanner]\nrun_on_startup = false\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(cfg)


def test_find_config_path_uses_env_override(tmp_path, monkeypatch):
    target = tmp_path / "custom.toml"
    monkeypatch.setenv("LABBOOK_CONFIG", str(target))
    assert find_config_path() == target


def test_find_config_path_derives_from_package(monkeypatch):
    monkeypatch.delenv("LABBOOK_CONFIG", raising=False)
    # The code repo (dir containing pyproject.toml) holds labbook.toml.
    path = find_config_path()
    assert path.name == "labbook.toml"
    assert (path.parent / "pyproject.toml").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eln.config'`.

- [ ] **Step 3: Write `eln/config.py`**

```python
# eln/config.py
"""Unified configuration for the labbook CLI.

One ``labbook.toml`` (gitignored, in the code repo) replaces the old in-repo
``sdgl.toml`` and additionally records ``data_root`` — the data-repo location.
The file is discovered from the installed package's code-repo checkout (the
directory containing ``pyproject.toml``), overridable by ``--config`` /
``LABBOOK_CONFIG``. The data root is overridable by ``--root`` / ``ELN_ROOT``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # 3.9 / 3.10
    import tomli as tomllib

CONFIG_FILENAME = "labbook.toml"
ENV_CONFIG = "LABBOOK_CONFIG"
ENV_ROOT = "ELN_ROOT"


@dataclass
class Config:
    """Resolved configuration. ``scan_roots`` paths are absolute."""

    data_root: Path
    scanner: dict = field(default_factory=dict)
    scan_roots: list = field(default_factory=list)  # [{"name": str, "path": Path}]


def find_config_path() -> Path:
    """Locate ``labbook.toml``.

    ``LABBOOK_CONFIG`` wins; otherwise derive the code-repo checkout from this
    package's location (the nearest parent holding ``pyproject.toml``).
    """
    env = os.environ.get(ENV_CONFIG)
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent / CONFIG_FILENAME
    raise FileNotFoundError(
        "Could not locate the code-repo root (no pyproject.toml above "
        f"{here}). Set {ENV_CONFIG} to the labbook.toml path."
    )


def load_config(config_path=None, *, root_override=None) -> Config:
    """Parse the unified config into a :class:`Config`.

    Root precedence: ``root_override`` (``--root``) > ``ELN_ROOT`` > the file's
    ``data_root``. Relative ``scan_roots`` paths resolve against ``data_root``.
    """
    path = Path(config_path) if config_path else find_config_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Config not found: {path}. Copy labbook.toml.example to {path}."
        )
    data = tomllib.loads(path.read_text(encoding="utf-8"))

    root = root_override or os.environ.get(ENV_ROOT) or data.get("data_root")
    if not root:
        raise ValueError(
            "No data_root: set --root, ELN_ROOT, or data_root in the config."
        )
    data_root = Path(root).expanduser().resolve()

    scan_roots = []
    for entry in data.get("scan_roots", []):
        p = Path(entry["path"]).expanduser()
        if not p.is_absolute():
            p = data_root / p
        scan_roots.append({"name": entry.get("name"), "path": p.resolve()})

    return Config(
        data_root=data_root,
        scanner=data.get("scanner", {}),
        scan_roots=scan_roots,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add eln/config.py tests/test_config.py
git commit -m "Add unified labbook.toml config loader (Roadmap step 7)"
```

---

## Task 2: Packaging, template, and gitignore

**Files:**
- Create: `labbook.toml.example`
- Modify: `pyproject.toml` (after the `[project.urls]` block)
- Modify: `.gitignore:12-13`
- Delete: `sdgl.toml.example`

- [ ] **Step 1: Create `labbook.toml.example`**

```toml
# labbook.toml — copy this to labbook.toml (gitignored) and edit for your machine.
# This single file replaces the old data-repo sdgl.toml and adds data_root.

# Absolute path to the data repo (holds experiments.sql, reports/, ...).
data_root = "/abs/path/to/data-repo"

[scanner]
run_on_startup = false
daily_scan = false

# Directories SDGL scans for raw/derived files. Relative paths resolve against
# data_root; absolute paths (e.g. external acquisition drives) are used as-is.
[[scan_roots]]
name = "data"
path = "data"
```

- [ ] **Step 2: Add the console-script to `pyproject.toml`**

Insert after the `[project.urls]` block (currently ending at line 28):

```toml
[project.scripts]
labbook = "eln.cli:main"
```

- [ ] **Step 3: Update `.gitignore`**

Replace lines 12-13:

```
# Local SDGL config (ship sdgl.toml.example; users copy it to sdgl.toml)
sdgl.toml
```

with:

```
# Local unified config (ship labbook.toml.example; users copy it to labbook.toml)
labbook.toml
```

- [ ] **Step 4: Delete the old template**

```bash
git rm sdgl.toml.example
```

- [ ] **Step 5: Reinstall so the script and (later) `eln.cli` are wired**

Run: `pip install -e . >/dev/null && which labbook`
Expected: prints a path ending in `/labbook`. (The command will error until Task 5 creates `eln/cli.py`; that's fine — this step only verifies the entry point is registered.)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore labbook.toml.example
git commit -m "Wire labbook console-script + unified config template (Roadmap step 7)"
```

---

## Task 3: `scan_roots` progress callback

**Files:**
- Modify: `eln/sdgl/engine.py` (`SDGL.scan_roots`, starts line 835)
- Test: `tests/sdgl/test_scan.py`

- [ ] **Step 1: Read the current `scan_roots` body**

Run: `sed -n '835,910p' eln/sdgl/engine.py`
Note where the method iterates `roots` (one dict per scan root) and where it builds the summary it returns. You will add a `progress=None` parameter and call it once per root and once at the end.

- [ ] **Step 2: Write the failing test**

Add to `tests/sdgl/test_scan.py` (the file already builds a data root with a CODE-NN tree; reuse its fixture — assume it exposes an `sdgl` SDGL instance and a `roots` list of `{"name","path"}` dicts; adapt names to the existing fixture):

```python
def test_scan_roots_reports_progress(sdgl_engine, scan_roots_arg):
    events = []
    result = sdgl_engine.scan_roots(scan_roots_arg, progress=events.append)
    # one event per scan root, plus a final summary event
    names = [e.get("root") for e in events if e.get("phase") == "root"]
    assert names  # at least one root reported
    assert any(e.get("phase") == "done" for e in events)
    # callback is optional — same return value as before
    assert "recognized" in result or "summary" in result
```

> If the existing fixture differs, mirror its setup: construct the `SDGL`, build the `roots` list the same way `test_scan.py` already does, and pass `progress=events.append`.

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/sdgl/test_scan.py -k progress -v`
Expected: FAIL — `scan_roots() got an unexpected keyword argument 'progress'`.

- [ ] **Step 4: Add the callback**

Change the signature:

```python
    def scan_roots(self, roots, list_paths=False, progress=None):
```

Inside the loop over `roots`, immediately before processing each root, emit:

```python
            if progress:
                progress({"phase": "root", "root": root.get("name"), "path": str(root.get("path"))})
```

Immediately before the `return` of the summary, emit:

```python
        if progress:
            progress({"phase": "done", "summary": result})
```

(Use whatever local variable currently holds the returned summary in place of `result`.)

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/sdgl/test_scan.py -v`
Expected: PASS (existing scan tests + the new one).

- [ ] **Step 6: Commit**

```bash
git add eln/sdgl/engine.py tests/sdgl/test_scan.py
git commit -m "Add optional progress callback to SDGL.scan_roots (Roadmap step 7)"
```

---

## Task 4: Repoint engine + server off in-repo `sdgl.toml`

**Files:**
- Modify: `eln/sdgl/engine.py` (the module-level scan helper near line 1535; the `scan_roots` fallback near line 832)
- Modify: `eln/server/app.py` (`create_app` line 66; scan route line 236; regenerate config read line 672)
- Modify: `tests/server/test_app.py:29-33`, `tests/sdgl/test_scan.py:62`, `tests/generators/test_generate.py:57`

- [ ] **Step 1: Inject scan config into `create_app`**

Change the signature (line 66) from:

```python
def create_app(root, *, eln_db_path=None, sdgl_db_path=None, assets_dir=None):
```

to add an injected config:

```python
def create_app(root, *, eln_db_path=None, sdgl_db_path=None, assets_dir=None, scan_roots=None):
```

Near the top of `create_app`, store the injected roots:

```python
    app.config["SCAN_ROOTS"] = scan_roots or []
```

- [ ] **Step 2: Use injected roots in the scan route**

Replace the scan route body (lines 232-240) that reads `parse_sdgl_toml(root / "sdgl.toml")`:

```python
    @app.route("/api/sdgl/scan", methods=["POST"])
    def sdgl_scan():
        data = request.json or {}
        roots = data.get("roots")
        if roots is None:
            roots = app.config["SCAN_ROOTS"]
        result = get_sdgl().scan_roots(roots)
        if not roots:
            result["message"] = "No scan roots configured"
        return jsonify(result)
```

- [ ] **Step 3: Fix the regenerate route's config read (line 672)**

Run: `sed -n '665,685p' eln/server/app.py`
If the `config = parse_sdgl_toml(root / "sdgl.toml")` at line 672 is only used to feed the generators (which read dates from the DB), delete the unused read. If it supplies a value the route needs, replace it with `app.config["SCAN_ROOTS"]` or the relevant injected value. Remove the now-unused `parse_sdgl_toml` import (line 33) if no references remain (`grep -n parse_sdgl_toml eln/server/app.py`).

- [ ] **Step 4: Repoint the engine's module-level scan helper (near line 1535)**

Run: `sed -n '1520,1560p' eln/sdgl/engine.py`
Replace its `config = parse_sdgl_toml(root / "sdgl.toml")` + `scan_roots` extraction with the unified loader:

```python
    from eln.config import load_config

    config = load_config(root_override=str(root))
    roots = config.scan_roots
    if not roots:
        print("No scan roots configured in labbook.toml", file=sys.stderr)
        return ...  # keep the existing early-return value
```

For the `scan_roots` fallback at line 832 (used when the engine is asked to scan with no explicit roots): keep `parse_sdgl_toml` **only** if other call sites still rely on it; otherwise have callers always pass `roots`. Prefer passing roots explicitly — the CLI and server both do. If line 832's fallback becomes dead, delete it.

- [ ] **Step 5: Migrate the test fixtures**

`tests/server/test_app.py` (lines 29-33): delete the `sdgl.toml` write; pass roots directly:

```python
    app = create_app(root, scan_roots=[{"name": "data", "path": root / "data"}])
```

`tests/sdgl/test_scan.py` (line 62) and `tests/generators/test_generate.py` (line 57): replace the `(root / "sdgl.toml").write_text(...)` calls. For `test_scan.py`, pass the roots list straight into `scan_roots(...)` (the engine no longer reads a file). For `test_generate.py`, if the generators don't actually consume scan config (they read `experiment_metadata.start_date` from the DB), simply delete the `sdgl.toml` write.

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: PASS. Investigate any failure that references `sdgl.toml` or `parse_sdgl_toml` and convert it to the injected-config form.

- [ ] **Step 7: Commit**

```bash
git add eln/sdgl/engine.py eln/server/app.py tests/
git commit -m "Repoint engine + server off in-repo sdgl.toml to unified config (Roadmap step 7)"
```

---

## Task 5: `eln/cli.py` dispatcher (admin, scan, regenerate, rebuild, backup)

**Files:**
- Create: `eln/cli.py`
- Delete: `eln/server/__main__.py`, `eln/generators/__main__.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli.py
import sqlite3
import pytest

from eln.cli import build_parser, _ensure_db, main
from eln.config import Config


def _make_db(path):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()


def test_bare_invocation_prints_help_and_exits_zero(capsys):
    rc = main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "admin" in out and "publish" in out


def test_parser_has_all_subcommands():
    parser = build_parser()
    # argparse stores subcommand names on the subparsers action choices
    sub = next(a for a in parser._actions if a.dest == "command")
    for name in ["admin", "scan", "regenerate", "rebuild", "publish", "backup"]:
        assert name in sub.choices


def test_ensure_db_builds_when_missing(tmp_path):
    sql = tmp_path / "experiments.sql"
    sql.write_text("CREATE TABLE t (id INTEGER);", encoding="utf-8")
    db = tmp_path / "experiments.db"
    cfg = Config(data_root=tmp_path)
    _ensure_db(cfg)
    assert db.exists()


def test_ensure_db_does_not_clobber_live_db(tmp_path):
    sql = tmp_path / "experiments.sql"
    sql.write_text("CREATE TABLE t (id INTEGER);", encoding="utf-8")
    db = tmp_path / "experiments.db"
    _make_db(db)
    # add an extra table so we can detect a clobber
    conn = sqlite3.connect(str(db)); conn.execute("CREATE TABLE live (x INTEGER)"); conn.commit(); conn.close()
    cfg = Config(data_root=tmp_path)
    _ensure_db(cfg)
    conn = sqlite3.connect(str(db))
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "live" in names  # untouched


def test_backup_is_a_stub(capsys):
    rc = main(["backup"])
    err = capsys.readouterr().err
    assert rc != 0
    assert "step 8" in err.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eln.cli'`.

- [ ] **Step 3: Write `eln/cli.py`**

```python
# eln/cli.py
"""The unified ``labbook`` command — the one entry point to every operation.

Installed via ``[project.scripts]`` (``pip install -e .`` puts ``labbook`` on
PATH). Subcommands call existing library functions; configuration comes from the
unified ``labbook.toml`` (see :mod:`eln.config`).
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

from eln.config import load_config
from eln.db import DEFAULT_DB_NAME, DEFAULT_SQL_NAME
from eln.db.rebuild_db import rebuild


def _load(args):
    """Resolve config from the global --config / --root flags."""
    return load_config(args.config, root_override=args.root)


def _ensure_db(config):
    """Ensure experiments.db exists, building from experiments.sql only if
    missing. Never clobbers a live working DB (``rebuild`` is a no-op when the
    binary already exists)."""
    db = config.data_root / DEFAULT_DB_NAME
    sql = config.data_root / DEFAULT_SQL_NAME
    rebuild(sql, db)  # force defaults False -> builds only when db is absent
    return db


# ---- subcommand handlers -------------------------------------------------

def cmd_admin(args):
    from eln.server import create_app

    config = _load(args)
    _ensure_db(config)
    app = create_app(config.data_root, scan_roots=config.scan_roots)
    url = f"http://localhost:{args.port}/"
    print("=" * 50)
    print(f"Lab Notebook (admin view): {url}")
    print("Local use only — unauthenticated.")
    print("=" * 50)
    if args.scan:
        app.start_background_scan()
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(debug=args.debug, port=args.port)
    return 0


def cmd_scan(args):
    from eln.sdgl import SDGL

    config = _load(args)
    sdgl = SDGL(config.data_root)

    def report(event):
        if event.get("phase") == "root":
            print(f"  scanning {event.get('root')} ({event.get('path')})")
        elif event.get("phase") == "done":
            s = event.get("summary", {})
            print(f"  done: {s}")

    sdgl.scan_roots(config.scan_roots, progress=report)
    return 0


def cmd_regenerate(args):
    from eln.generators import generate_all

    config = _load(args)
    written = generate_all(config.data_root, args.catalog_out)
    for name, path in written.items():
        print(f"  {name}: {path}")
    return 0


def cmd_rebuild(args):
    config = _load(args)
    db = config.data_root / DEFAULT_DB_NAME
    sql = config.data_root / DEFAULT_SQL_NAME
    if db.exists() and not args.force:
        if sql.exists() and sql.stat().st_mtime > db.stat().st_mtime:
            print(f"WARNING: {sql} is newer than {db}. Use --force to rebuild.")
        else:
            print(f"{db} already exists; left unchanged (use --force to rebuild).")
        return 0
    rebuild(sql, db, force=args.force)
    print(f"Rebuilt {db} <- {sql}")
    return 0


def cmd_publish(args):
    from eln.server.publish import publish

    config = _load(args)
    result = publish(config.data_root)
    if "error" in result:
        print(result["error"], file=sys.stderr)
        return 1
    print(result.get("message", "Published."))
    return 0


def cmd_backup(args):
    print("labbook backup: not yet implemented (Roadmap step 8).", file=sys.stderr)
    return 1


# ---- parser --------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(prog="labbook", description="Electronic lab notebook CLI.")
    parser.add_argument("--config", default=None, help="path to labbook.toml (overrides discovery)")
    parser.add_argument("--root", default=None, help="data-repo root (overrides ELN_ROOT and config)")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("admin", help="start the server and open the admin/authoring view")
    p.add_argument("--scan", action="store_true", help="run an SDGL scan on startup")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--debug", action="store_true")
    p.add_argument("--no-browser", action="store_true", help="do not open a browser")
    p.set_defaults(func=cmd_admin)

    p = sub.add_parser("scan", help="scan configured roots with live feedback")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("regenerate", help="DB -> catalog HTML")
    p.add_argument("--catalog-out", default=None)
    p.set_defaults(func=cmd_regenerate)

    p = sub.add_parser("rebuild", help="experiments.sql -> DB")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_rebuild)

    p = sub.add_parser("publish", help="DB -> experiments.sql -> commit + push")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("backup", help="back up identified data (Roadmap step 8)")
    p.set_defaults(func=cmd_backup)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Delete the old entry points**

```bash
git rm eln/server/__main__.py eln/generators/__main__.py
```

- [ ] **Step 5: Run the CLI tests**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (5 passed).

- [ ] **Step 6: Smoke-test the installed command**

Run: `labbook --help && labbook backup; echo "exit=$?"`
Expected: help text listing all six subcommands; `labbook backup` prints the step-8 message and `exit=1`.

- [ ] **Step 7: Commit**

```bash
git add eln/cli.py tests/test_cli.py
git commit -m "Add unified labbook CLI dispatcher; drop per-module __main__ (Roadmap step 7)"
```

---

## Task 6: Pre-publish >90 MB guardrail

**Files:**
- Modify: `eln/server/publish.py` (between the `git add` at line 50 and the commit at line 60)
- Test: `tests/server/test_publish.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/server/test_publish.py
import os
import subprocess
from pathlib import Path


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def test_publish_rejects_oversized_staged_file(tmp_path):
    from eln.db.init_db import init_db  # creates a schema-only experiments.db
    from eln.server.publish import publish

    root = tmp_path
    _git(["init"], root)
    _git(["config", "user.email", "t@t"], root)
    _git(["config", "user.name", "t"], root)

    # a real (schema-only) database so publish gets past the dump step
    init_db(root / "experiments.db")

    # a sparse 91 MB file that git will stage on publish (size without disk use)
    big = root / "reports" / "huge.bin"
    big.parent.mkdir(parents=True, exist_ok=True)
    with open(big, "wb") as fh:
        fh.truncate(91 * 1024 * 1024)

    result = publish(root, push=False)
    assert "error" in result
    assert "huge.bin" in result["error"]
    # nothing was committed
    assert _git(["rev-parse", "--verify", "HEAD"], root).returncode != 0
```

> `init_db(path)` is the verified function name in `eln/db/init_db.py`. The point is a schema-valid `experiments.db` so `dump()` succeeds.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_publish.py -k oversized -v`
Expected: FAIL — publish currently commits regardless of file size, so HEAD exists / no error.

- [ ] **Step 3: Add the guardrail to `publish.py`**

Add a constant near the top (after `PUBLISH_PATHS`):

```python
MAX_STAGED_BYTES = 90 * 1024 * 1024  # reject any single staged file above 90 MB
```

Add a helper above `publish`:

```python
def _oversized_staged(root):
    """Return [(path, size)] for staged files larger than MAX_STAGED_BYTES."""
    out = _git(["diff", "--cached", "--name-only"], cwd=root)
    offenders = []
    for name in out.stdout.split("\n"):
        name = name.strip()
        if not name:
            continue
        f = Path(root) / name
        if f.exists() and f.stat().st_size > MAX_STAGED_BYTES:
            offenders.append((name, f.stat().st_size))
    return offenders


def _repo_size_bytes(root):
    out = _git(["count-objects", "-v"], cwd=root)
    for line in out.stdout.splitlines():
        if line.startswith("size-pack:"):
            return int(line.split()[1]) * 1024  # KiB -> bytes
    return 0
```

Insert the guardrail in `publish` immediately after the `git add` success check (after line 52, before the "nothing staged" check):

```python
    # 3b. Guardrail: refuse to commit oversized blobs into git history.
    offenders = _oversized_staged(root)
    if offenders:
        listed = ", ".join(f"{n} ({s // (1024*1024)} MB)" for n, s in offenders)
        repo_mb = _repo_size_bytes(root) // (1024 * 1024)
        # un-stage so the working tree is left clean
        _git(["reset"], cwd=root)
        return {
            "error": (
                f"Publish blocked: staged file(s) exceed 90 MB: {listed}. "
                f"Move large media out of git (repo pack size ~{repo_mb} MB)."
            )
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/server/test_publish.py -v`
Expected: PASS (existing publish tests + the new guardrail test).

- [ ] **Step 5: Commit**

```bash
git add eln/server/publish.py tests/server/test_publish.py
git commit -m "Reject staged files >90 MB before publish (Roadmap step 7)"
```

---

## Task 7: Final verification

- [ ] **Step 1: Full suite**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 2: Confirm the old entry points are gone and the new one works**

Run: `python -m eln.server 2>&1 | head -1; labbook --help | head -5`
Expected: `python -m eln.server` errors (no `__main__`); `labbook --help` prints usage.

- [ ] **Step 3: Confirm no lingering in-repo `sdgl.toml` references**

Run: `grep -rn "sdgl.toml\|parse_sdgl_toml" eln/ tests/`
Expected: no results (or only an intentional, documented one). Convert any stragglers.

- [ ] **Step 4: Commit any cleanup**

```bash
git add -A && git commit -m "Finish labbook CLI + config unification (Roadmap step 7)" || echo "nothing to commit"
```

---

## Self-Review Notes

- **Spec coverage:** config unification (T1/T2/T4), discovery + precedence (T1), `labbook` entry point + removed `__main__` (T2/T5), all six subcommands (T5/T6), scan live feedback (T3/T5), ensure-DB-no-clobber (T5), rebuild newer-than warning (T5), publish guardrail (T6), fixture migration (T4). All spec sections map to a task.
- **Type consistency:** `Config(data_root, scanner, scan_roots)` and `scan_roots` entries `{"name", "path": Path}` are used consistently across `eln/config.py`, `create_app(scan_roots=...)`, and the CLI handlers. `rebuild(sql, db, force=False)` matches `eln/db/rebuild_db.py`. `publish(root, push=...)` and its `{"error"/"message"}` result dict match `eln/server/publish.py`.
- **Open verification points flagged inline** (do not skip): exact body of `scan_roots` (T3 S1), the regenerate route's use of the old config read (T4 S3), the `init_db` function name (T6 S1), and the existing scan-test fixture shape (T3 S2).
```
