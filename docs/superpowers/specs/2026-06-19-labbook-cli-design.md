# Spec: Unified `labbook` CLI + config unification (Roadmap step 7)

**Date:** 2026-06-19
**Roadmap:** Phase C, step 7 — *CLI tools — unified `labbook` command*
**Status:** Approved (design); pending implementation plan

## Goal

Replace the raw `python -m eln.*` invocations with one discoverable `labbook`
entry point installed via `[project.scripts]`, and unify configuration into a
single `labbook.toml` that carries both the data-repo location and the SDGL scan
configuration. After `pip install -e .`, `labbook` is on `PATH` and is the one
true door to every operation: launch the authoring server, scan, regenerate,
rebuild, publish, and (later) back up.

## Background / current state

Operations are invoked today as separate module entry points, each taking the
data-repo `root` as a required positional argument:

| Concern | Current invocation |
|---|---|
| serve | `python -m eln.server ROOT [--port] [--debug] [--no-scan]` |
| regenerate | `python -m eln.generators ROOT [--catalog-out]` |
| rebuild | `python -m eln.db.rebuild_db [SQL] [DB] [--force]` |
| publish | `eln.server.publish.publish()` (HTTP route only; no CLI) |
| scan | `/api/sdgl/scan` route + server startup `start_background_scan` |

Configuration lives in `sdgl.toml` **inside the data repo** (`<root>/sdgl.toml`),
read at three call sites via `parse_sdgl_toml(root / "sdgl.toml")` (engine ×2,
server ×1) plus an in-server use in the regenerate route. Its surface today:

```toml
[scanner]
run_on_startup = false
daily_scan = false

[[scan_roots]]
name = "reports"
path = "reports"   # relative paths resolve against the data-repo root
```

Because `sdgl.toml` lives inside the data repo, it cannot also record where that
repo *is* — the root pointer must live outside any specific data repo.

## Decisions

1. **Unify config into one `labbook.toml` that lives in the code repo.** It
   replaces `sdgl.toml` and additionally carries a `data_root` key. The real file
   is **gitignored** (machine-specific absolute paths); a committed
   `labbook.toml.example` is the template. The code repo therefore stays free of
   hardcoded absolute paths in git (consistent with Roadmap step 1).
2. **`sdgl.toml` is removed from the data repo.** All readers repoint to the
   unified config.
3. **Config is discovered by deriving the code-repo checkout from the installed
   package location** (the directory containing `pyproject.toml`, found via the
   package's `__file__`), then reading `<code-repo>/labbook.toml`. Overridable by
   `--config PATH` or the `LABBOOK_CONFIG` env var. This works from any working
   directory with an editable install.
4. **One argparse dispatcher in `eln/cli.py`**, registered as
   `[project.scripts] labbook = "eln.cli:main"`. The per-module `__main__.py`
   entry points (`eln/server`, `eln/generators`) are removed; their `main()`
   logic moves into thin subcommand handlers calling the existing library
   functions.
5. **Root precedence:** `--root` > `ELN_ROOT` env > `config.data_root`. `ELN_ROOT`
   is retained as a free per-call/CI override even though the config now carries
   `data_root`.
6. **Bare `labbook` prints help.** Launching the server is the explicit
   `labbook admin` subcommand.
7. **Scan live feedback:** per-root progress + a final summary, implemented by
   adding an optional `progress` callback to `scan_roots`; the engine stays batch
   internally.
8. **Publish guardrail:** reject (hard fail) on any staged file >90 MB; report
   total repo size.

## Architecture

### `eln/config.py` (new)

- `find_config_path() -> Path` — resolve `<code-repo>/labbook.toml` from the
  package location; honor `--config` / `LABBOOK_CONFIG` overrides.
- `load_config(config_path=None, root_override=None) -> Config` — parse the TOML
  into a small `Config` object exposing:
  - `data_root: Path` — `root_override` (from `--root`/`ELN_ROOT`) if given, else
    the file's `data_root`.
  - `scanner: dict` — `run_on_startup`, `daily_scan`.
  - `scan_roots: list` — `name`/`path`; relative `path`s resolve against
    `data_root` (unchanged semantics).

Reuses the existing TOML parsing approach (`tomllib`/`tomli`).

### `eln/cli.py` (new)

A single `main(argv=None)` builds an argparse parser with global `--config` and
`--root` options and one subparser per command. Each handler loads the config
once, resolves `data_root`, and calls into the existing library:

- `admin` → `create_app(...)` + `app.run()` + `webbrowser.open`
- `scan` → `SDGL(...).scan_roots(roots, progress=...)`
- `regenerate` → `eln.generators.generate_all`
- `rebuild` → `eln.db.rebuild_db.rebuild`
- `publish` → `eln.server.publish.publish` (+ guardrail)
- `backup` → stub

### Refactors to existing modules

- `eln/sdgl/engine.py`: `scan_roots(roots, list_paths=False, progress=None)` —
  invoke `progress(event)` per scan root and on completion; existing return value
  unchanged. The two internal `parse_sdgl_toml(root / "sdgl.toml")` call sites
  read from the unified config instead.
- `eln/server/app.py`: `create_app` and its scan/regenerate routes obtain
  scan-config from `load_config` rather than `parse_sdgl_toml(root / "sdgl.toml")`.
- `eln/server/publish.py`: unchanged transform; the guardrail lives in the CLI
  `publish` handler (or a small helper) so the publish library stays focused.
- Remove `eln/server/__main__.py` and `eln/generators/__main__.py`.

## Subcommands

### `labbook admin [--scan] [--port N] [--debug] [--no-browser]`

The old single-word `labbook`. **Ensure** the DB exists — build from
`experiments.sql` only if `experiments.db` is missing; **never** clobber a live
working DB. Start Flask and auto-open `http://localhost:PORT/` — the SDGL graph
with the edit overlay + `admin.js` injected (the authoring/admin view). Flags:

- `--scan` — opt into a startup SDGL scan (default **off**; inverts today's
  `--no-scan`).
- `--port N` — default 5000.
- `--debug` — Flask debug mode.
- `--no-browser` — suppress the browser open (headless/CI).

### `labbook scan`

Run `scan_roots` against the configured scan roots with **live feedback**: print
each scan root as it is processed, then the final summary (items found / added /
updated / errors). No browser scan button equivalent. Uses the new `progress`
callback.

### `labbook regenerate`

DB → catalog HTML via `generate_all`. Optional `--catalog-out DIR` retained.

### `labbook rebuild [--force]`

`experiments.sql` → `experiments.db`. Without `--force`: no-op if the DB already
exists, but **warn** when `experiments.sql` is newer than the DB (rather than
silently leaving a stale DB or auto-overwriting). `--force` rebuilds
unconditionally (atomic temp-file swap, as today).

### `labbook publish`

Materialize derived identifiers → dump `experiments.sql` → commit → **push** to
the private GitHub data remote. Gated by a **pre-publish guardrail**: inspect
staged files and **reject (hard fail)** if any staged file exceeds 90 MB, naming
the offending file(s); report total repo size. The guardrail runs before the
commit so nothing oversized is recorded.

### `labbook backup`

Stub for Roadmap step 8. Registered so it appears in help and is discoverable;
prints `not yet implemented (Roadmap step 8)` and exits non-zero.

## The three transforms stay distinct

`rebuild` (sql→DB), `regenerate` (DB→HTML), and `publish` (DB→sql→push) run in
opposite directions and remain separate commands. `admin` startup only *ensures*
the DB exists; it never rebuilds over a live working DB.

## Error handling

- Missing/invalid config, or no resolvable `data_root`: a clear error naming the
  expected config path and the `--root`/`ELN_ROOT`/`--config` overrides.
- `rebuild` with a missing `experiments.sql`: clear error.
- `publish` guardrail trip: non-zero exit, the offending path(s), and the repo
  size; no commit is made.
- `backup`: non-zero exit with the "step 8" message.

## Testing

- `tests/test_config.py` — `find_config_path` derivation, `load_config` parsing,
  root precedence (`--root` > `ELN_ROOT` > `config.data_root`), and relative
  scan-root resolution against `data_root`.
- `tests/test_cli.py` — argparse dispatch for each subcommand, bare `labbook`
  prints help, and `admin`'s ensure-DB-but-don't-clobber logic (missing DB →
  built; existing DB → left untouched).
- Publish guardrail test — a staged >90 MB file causes a hard fail with no
  commit.
- Migrate existing server/generator test fixtures from an in-root `sdgl.toml` to
  the unified `labbook.toml` config.

## Out of scope

- The backup flow itself (Roadmap step 8) — only the discoverable stub here.
- Any change to the publish transform's git semantics beyond adding the size
  guardrail.
- Static-bundle / sharing concerns (Roadmap step 12).
