# Presentations as the First Plugin (Roadmap Step 9) Implementation Plan

> **For agentic workers:** Implement task-by-task with TDD. Steps use checkbox (`- [ ]`) syntax. The parent session runs all Python/test steps (subagents cannot run Python). Use the canonical miniconda `pytest`, not the repo `.venv`.

**Goal:** Define clean plugin extension points — **nav registration, generator hook, scan-root contribution, serving route** — and re-implement presentations *as* the first plugin against them, so it becomes the reusable OSS plugin template rather than coupled-then-extracted core.

**Discovery mechanism (decided):** A `Plugin` dataclass interface + a registry that merges an in-tree `BUILTIN_PLUGINS` list with third-party `importlib.metadata` entry points (group `eln.plugins`), deduped by `name`. Presentations ships in-tree (BUILTIN); third parties `pip install` a package that exposes a `plugin` object via the entry-point group.

**Tech Stack:** Python 3 (stdlib: `dataclasses`, `importlib.metadata`, `pathlib`), Flask, pytest.

---

## Background: what exists today (the four couplings to undo)

1. **Generator hook** — `eln/generators/__init__.py::generate_all` hardcodes `generate_presentations`.
2. **Nav registration** — every generated page embeds a literal `.nav` block listing `presentations.html`; `catalog.py`, `reports.py`, `protocols.py` use a `<div class="nav">` bar, while `home.py` fills `catalog/home_template.html` whose nav is card-style (`__TOTAL_PRESENTATIONS__` count + a presentations card).
3. **Serving route** — `eln/server/app.py` hardcodes `/presentations/<path:filepath>` and lists `presentations.html` in `GENERATED_PAGES`.
4. **Scan-root contribution** — `config.scan_roots` feeds SDGL; today plugins cannot add roots. (Presentations doesn't need one, but the interface must support it.)

## Plugin interface (the contract)

`eln/plugins/__init__.py`:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

@dataclass(frozen=True)
class NavLink:
    label: str
    href: str            # "presentations.html" (relative) — also the generated page filename

@dataclass(frozen=True)
class StaticMount:
    url_prefix: str                      # "presentations" -> /presentations/<path>
    source: Callable[[Path], Path]       # root -> directory to serve from

@dataclass(frozen=True)
class Plugin:
    name: str
    nav: NavLink | None = None                                   # nav registration
    generate: Callable[[Path, Any], Path] | None = None         # generator hook: (root, catalog_out) -> Path
    static_mount: StaticMount | None = None                     # serving route
    scan_roots: Callable[[Path], list[Path]] | None = None       # scan-root contribution
    register_routes: Callable[[Any, Path], None] | None = None   # optional extra Flask routes
    home_count: Callable[[Path], int] | None = None              # optional home-page stat
```

Registry:

```python
BUILTIN_PLUGINS: list[Plugin] = [presentations.plugin]

def discover_plugins() -> list[Plugin]:
    seen, out = set(), []
    for p in [*BUILTIN_PLUGINS, *_entry_point_plugins()]:
        if p.name not in seen:
            seen.add(p.name); out.append(p)
    return out
```

`_entry_point_plugins()` reads `importlib.metadata.entry_points(group="eln.plugins")` and `.load()`s each (tolerating a missing/empty group on older corpora).

---

### Task 1: Plugin interface + registry

**Files:** Create `eln/plugins/__init__.py`, `tests/plugins/__init__.py`, `tests/plugins/test_registry.py`.

- [ ] **Step 1 (red):** Test `discover_plugins()` returns a plugin named `presentations`; test that a fake entry point is merged; test dedup (a BUILTIN name from an entry point is not duplicated).
- [ ] **Step 2:** Run `pytest tests/plugins/test_registry.py -v` → fails (no module).
- [ ] **Step 3 (green):** Implement `NavLink`, `StaticMount`, `Plugin`, `BUILTIN_PLUGINS`, `_entry_point_plugins`, `discover_plugins`. (Import the presentations plugin lazily inside the module to avoid a cycle if needed.)
- [ ] **Step 4:** Run tests → pass.
- [ ] **Step 5:** Commit `feat(plugins): Plugin interface + builtin/entry-point registry`.

### Task 2: Presentations plugin module

**Files:** Create `eln/plugins/presentations.py`; modify `eln/plugins/__init__.py` (BUILTIN), `eln/generators/presentations.py`.

Move the scanning/HTML logic into `eln/plugins/presentations.py` and expose a module-level `plugin = Plugin(name="presentations", nav=NavLink("Presentations", "presentations.html"), generate=generate_presentations, static_mount=StaticMount("presentations", lambda root: Path(root) / "presentations"), home_count=count_presentations)`. Keep `eln/generators/presentations.py` as a thin re-export (`from eln.plugins.presentations import generate_presentations`) so existing imports/tests keep working, OR update those imports — choose the smaller diff.

- [ ] **Step 1 (red):** Test `from eln.plugins.presentations import plugin` has `plugin.name == "presentations"`, `plugin.nav.href == "presentations.html"`, and `plugin.generate(root, None)` writes `presentations.html`.
- [ ] **Step 2–4:** Implement, run, green. Confirm `generate_presentations` output is byte-identical to before (no template churn) by keeping the HTML string identical for now (nav still inline at this point — Task 3 swaps it).
- [ ] **Step 5:** Commit `feat(plugins): presentations plugin (generator + nav + static mount)`.

### Task 3: Registry-driven nav helper + adopt in bar-style generators

**Files:** Create `eln/generators/nav.py`; modify `eln/generators/catalog.py`, `reports.py`, `protocols.py`, and the presentations plugin's HTML; test `tests/generators/test_nav.py`.

`render_nav(active_href, plugins) -> str` returns `<div class="nav">…</div>` from `CORE_NAV` (Data Graph `/`, Experiments, Protocols, Reports) plus each `plugin.nav`. Each bar-style generator gains a `plugins=None` kwarg (defaulting to `discover_plugins()`) and replaces its literal nav block with `render_nav(<own href>, plugins)`.

- [ ] **Step 1 (red):** `render_nav("experiments.html", discover_plugins())` contains `Experiments` and `Presentations`; the active link is marked.
- [ ] **Step 2–4:** Implement `nav.py`; refactor the three bar generators + the presentations HTML to call it. Run.
- [ ] **Step 5:** Commit `refactor(generators): registry-driven nav bar`.

### Task 4: Home page — plugin-driven cards + counts

**Files:** Modify `catalog/home_template.html`, `eln/generators/home.py`.

Replace the hardcoded presentations card and `__TOTAL_PRESENTATIONS__` in the template with a `__PLUGIN_CARDS__` placeholder. In `home.py`, render one card per `plugin.nav` (label + `plugin.home_count(root)` when present) and substitute. Core cards (experiments/protocols/reports/data graph) stay in the template.

- [ ] **Step 1 (red):** With the presentations plugin present, generated `index.html` contains a Presentations card and its count; `__PLUGIN_CARDS__` is fully substituted.
- [ ] **Step 2–4:** Implement, run.
- [ ] **Step 5:** Commit `refactor(generators): plugin-driven home cards + counts`.

### Task 5: `generate_all` iterates plugins

**Files:** Modify `eln/generators/__init__.py`; update `tests/generators/test_generate.py` if needed.

`generate_all(root, catalog_out)` runs the core generators (experiments, protocols, reports, home) then, for each `p in discover_plugins()` with a `generate`, calls it and adds `{p.name: path}`. The returned dict still contains `"presentations"`. Keep `test_generate_all_writes_all_pages`'s expected set valid; keep byte-identical regeneration.

- [ ] **Step 1–4:** Implement; run `pytest tests/generators/ -v` → green (update expectations only where the plugin path legitimately changes them).
- [ ] **Step 5:** Commit `refactor(generators): generate_all drives plugin generators`.

### Task 6: Server — plugin static mounts, routes, generated-page set

**Files:** Modify `eln/server/app.py`; test `tests/server/test_app.py`.

In `create_app`, after core routes: `plugins = discover_plugins()`; for each `static_mount`, register `/<prefix>/<path:filepath>` serving from `mount.source(root)`; for each `register_routes`, call `fn(app, root)`. Remove the hardcoded `/presentations/` route. Compute `GENERATED_PAGES` as the core set plus `{p.nav.href for p in plugins if p.nav}`.

- [ ] **Step 1 (red):** A request to `/presentations/<file>` is served; `presentations.html` is served as a generated page — both still pass with the hardcoded route removed.
- [ ] **Step 2–4:** Implement, run `pytest tests/server/test_app.py -v`.
- [ ] **Step 5:** Commit `refactor(server): plugin-driven static mounts + routes`.

### Task 7: Scan-root contribution wiring

**Files:** Modify `eln/cli.py` (`cmd_scan`) and `eln/server/app.py` (`start_background_scan`).

Where `config.scan_roots` is passed to `SDGL.scan_roots`, append `r for p in discover_plugins() if p.scan_roots for r in p.scan_roots(root)`. Presentations contributes none (no behavior change), but the capability is exercised by a unit test using a throwaway plugin.

- [ ] **Step 1 (red):** A test plugin whose `scan_roots` returns one dir causes that dir to appear in the effective scan-root list (test the small helper that assembles roots, not a full scan).
- [ ] **Step 2–4:** Extract a `effective_scan_roots(config_roots, root, plugins)` helper; implement; run.
- [ ] **Step 5:** Commit `feat(plugins): scan-root contribution extension point`.

### Task 8: Packaging, docs, full suite, roadmap

**Files:** Modify `pyproject.toml`, `eln/generators/README.md` (or a new `eln/plugins/README.md`), `docs/ROADMAP.md`.

- [ ] **Step 1:** Ensure `eln.plugins` is packaged (setuptools find-packages already covers `eln.*`; verify). Document the third-party recipe: a plugin package adds `[project.entry-points."eln.plugins"]` `name = "module:plugin"`.
- [ ] **Step 2:** Write `eln/plugins/README.md` describing the four extension points and a minimal example plugin (the OSS template).
- [ ] **Step 3:** Run the full suite `pytest -q` → all green.
- [ ] **Step 4:** Mark step 9 `_done_` in `docs/ROADMAP.md` and update the "Next step" section to point at step 9b (one-time data migration).
- [ ] **Step 5:** Commit `docs: plugin extension-point guide + mark Roadmap step 9 done`.

---

## Self-Review (spec coverage)

- **Nav registration** → `NavLink` + `render_nav` (Task 3) + home cards (Task 4). ✅
- **Generator hook** → `Plugin.generate` driven by `generate_all` (Tasks 2, 5). ✅
- **Serving route** → `StaticMount` + `register_routes` in `create_app` (Task 6). ✅
- **Scan-root contribution** → `Plugin.scan_roots` + `effective_scan_roots` (Task 7). ✅
- **OSS template / discovery** → builtin list + entry-point merge, deduped (Task 1); third-party recipe + README (Task 8). ✅
- **Presentations is the first plugin, defined right (not extracted)** → presentations is removed from core wiring and re-expressed entirely as `eln/plugins/presentations.py::plugin` (Tasks 2–6). ✅
- **No regression** → byte-identical regeneration preserved; existing generator/server/cli tests kept green (Tasks 3–7). ✅
