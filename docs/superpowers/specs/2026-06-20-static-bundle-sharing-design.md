# Static-Bundle Sharing — Design (Roadmap Step 12)

_Date: 2026-06-20_

## Summary

Add an **export** that turns the lab notebook into a self-contained static HTML
bundle — a folder of relative-linked pages plus only the media those pages
reference. Where the bundle goes is just a destination choice: drop it on the
Gaia share for lab members to open via `file://`, or point GitHub Pages at it to
host publicly. **Same artifact either way** — there is no separate "internal" vs
"public" builder.

Selection has exactly three granularities:

1. **Export everything** — the whole catalog as static HTML.
2. **Export a single progress report.**
3. **Export a single presentation.**

This collapses the roadmap's original two-tier framing (internal Gaia bundle +
public-flag/scrub-gate GitHub Pages bundle) into one builder. There is **no
per-experiment `public` flag and no catalog-wide scrub gate**: selection *is*
"everything / this one report / this one presentation."

## Why this shape

The live server already serves catalog pages **flat at the URL root**
(`/experiments.html`, `/reports.html`, …) with media under root-relative
`reports/…`, `presentations/…`, `thumbnails/…`, and the generators emit
root-relative media links to match. So a **flat bundle** — the catalog HTML at
the bundle root alongside the referenced `reports/`, `presentations/`,
`thumbnails/` subtrees — preserves every relative link untouched under both
`file://` and GitHub Pages. **No media-link rewriting is required.**

The generated catalog pages are already free of authoring chrome: the
edit-overlay and admin scripts are injected **at serve time** by
`eln/server/app.py` (`serve_html_with_overlay`), not baked into the generated
files. The only server-only elements a static page carries are:

- the **Data Graph** nav link / home-page card (`href="/"`, the API-driven graph
  view — dead without a server), and
- the `auth.js` script tag (the live server already strips this locally).

Both are neutralized by rendering in a **static mode** (see below), not by
post-hoc string surgery.

## Decisions

| Decision | Choice |
|---|---|
| Tiers | **One export**, destination-agnostic (Gaia folder *or* a folder hosted on Pages). Not two builders. |
| Selection granularity | **everything / single report / single presentation** — only these three |
| Public/scrub model | **None.** No per-item `public` flag, no PII/scrub gate. |
| Trigger | **UI buttons + a CLI engine.** `labbook export` is the engine; the authoring server adds an "Export catalog" control plus a per-item "Export" button on each report/presentation. |
| Single-item output | **Standalone, self-contained** — just that one page (no nav bar) + its media; a folder you can drop anywhere or zip and send. |
| Export endpoint | **Produce the folder only.** No git/network, no Pages-deploy automation — putting the bundle on Gaia or on Pages is a manual follow-on step. |
| Bundle layout | **Flat**, mirroring the served URL space — preserves relative links with zero rewriting. |
| Asset selection | **Reference-walk**: copy only files the emitted HTML links. Auto-drops source/build cruft. |
| Movie transcode | **None** — the corpus is already `.mp4`. Out of scope. |
| Architecture | **Reuse the generators in a `static=True` mode** + an asset-walk orchestrator (`eln/share.py`). Not a post-hoc rewrite, not a separate static-site generator. |

## Components & boundaries

- **`eln/share.py`** — the bundle builder (the "one core"). Public surface:
  - `export_all(root, dest)` → writes the full static catalog bundle to `dest`.
  - `export_item(root, dest, kind, ident)` → writes a standalone single
    `report` or `presentation` bundle.
  - `_collect_assets(html, root, dest)` (internal) → walks the HTML for local
    `src`/`href`, copies each referenced file from `root` into `dest` preserving
    its relative subpath, and returns `(count, total_bytes, missing[])` for the
    preview and the skip-report.
- **`static=True` flag** threaded into `eln/generators` (`generate_all`,
  `render_nav`, `generate_home`) — the single place that knows the Data Graph
  view and `auth.js` are server-only. In static mode they are omitted. This is
  the **only generator change**.
- **CLI** — `labbook export` (engine): `--all` | `--report ID` |
  `--presentation ID`, with `--dest PATH`.
- **Server** — a `POST /api/export` endpoint + buttons in the authoring overlay
  (an "Export catalog" control and a per-item "Export" button on each
  report/presentation), reusing the backup tool's destination picker.

Each unit has one purpose and a narrow interface: the generators render pages
(now optionally server-link-free); `eln/share.py` orchestrates render + asset
copy; the CLI/endpoint are thin entry points over `eln/share.py`.

## Bundle layout & data flow

**Full export** (`export_all`) → flat tree mirroring the served URL space:

```
dest/
  index.html          (home, static mode — Data Graph card dropped)
  experiments.html
  protocols.html
  reports.html
  presentations.html  (+ any plugin pages)
  reports/…           only figures/movies the pages reference
  presentations/…     only referenced assets
  thumbnails/…
```

Open `dest/index.html` directly (`file://`) or point GitHub Pages at `dest/`.

**Single-item export** (`export_item`) → standalone, nav-less:

```
dest/
  index.html          the one report/presentation, no nav bar, written as index.html
  reports/<sub>/…      (or presentations/<sub>/…) — only this item's referenced assets
```

**Shared flow:** render page(s) in static mode → for each emitted HTML, walk
local `src`/`href` → copy each referenced file from `root` into `dest` at its
relative subpath → tally count + bytes. External links (`http(s)://`), the
dropped `/` graph link, and `auth.js` are skipped, so only real, referenced,
in-tree assets are copied (this is what drops `.sh`/`.zip`/build cruft sitting
in the source dirs).

**Single-report subtlety:** the combined `reports.html` renders *all* reports.
For a single-report export the builder renders only that one `.md` (the
generator already iterates per-file, so it is a filtered render), strips the
nav, and writes it as `index.html`. Single-presentation export is the analogous
filtered render of the presentations generator.

## Destination, preview & guard

- **Destination picker** — reuse the backup tool's mechanism: server-side native
  folder dialog (`eln/sdgl/folder_dialog.py`), typed-path fallback. From the CLI
  it is `--dest PATH`.
- **Containment** — the builder never writes outside `dest` and **refuses a
  `dest` inside the data-repo tree**, so an export can't accidentally land in
  `reports/` and get published.
- **Pre-export preview + guard** — like backup, before copying show **file count
  + total size** (the asset walk only stats referenced files, so this is cheap)
  and confirm. Catches a report that embeds a large movie.
- **Overwrite** — if `dest` is non-empty, warn and require confirmation; the
  export writes a fresh tree rather than merging into arbitrary existing content.

## Error handling & edge cases

- **Missing referenced asset** (HTML links a file no longer on disk) → **skip +
  report** in the result (don't abort), mirroring the SDGL/backup
  "skip + report missing" convention. The bundle stays usable; the gap is
  surfaced.
- **Unknown item id** for a single export → clear error, no partial write.
- **No DB / nothing to render** → the same short-circuit messaging as the other
  CLI commands.
- **No transcode** — movies are already `.mp4`; media is copied verbatim. A
  non-web movie format appearing later is a future addition, explicitly out of
  scope here.
- **Determinism** — reuses the generators' existing no-timestamp-churn property,
  so re-exporting unchanged content is byte-identical.

## Files

- **New** `eln/share.py`: `export_all`, `export_item`, `_collect_assets`, and the
  preview/guard helpers (count + size + missing list, containment check).
- **New** `tests/test_share.py` (parent runs pytest per the canonical-env note):
  - `export_all` from a small fixture data-repo → asserts the flat layout, the
    expected pages exist, and the Data Graph link/card + `auth.js` are absent;
  - asset-walk copies **only referenced** files — a stray `build.sh`/`.zip` in
    `reports/` is not in the bundle; a referenced `.png`/`.mp4` is, at the right
    subpath;
  - `export_item` (report + presentation) → standalone `index.html`, no nav,
    only that item's assets;
  - missing referenced asset → skipped + reported, export still succeeds;
  - relative-link integrity → every local `src`/`href` in an emitted page
    resolves to a file present in the bundle;
  - determinism → exporting twice is byte-identical.
- **Edits:**
  - `eln/generators/nav.py` — `render_nav(plugins, static=False)`; static mode
    drops the Data Graph `NavLink`.
  - `eln/generators/home.py` — static mode drops the Data Graph card.
  - `eln/generators/__init__.py` — `generate_all(..., static=False)` threads the
    flag to the core generators.
  - `eln/cli.py` — `export` subcommand (`--all` / `--report` / `--presentation`,
    `--dest`).
  - `eln/server/app.py` — `POST /api/export` route + the overlay buttons it
    serves.
  - `labbook.toml.example` — document export (no required config; destination is
    chosen per call).

## Out of scope (YAGNI)

- GitHub Pages deploy automation / git remotes — export stops at the folder.
- Per-experiment `public` flag and any catalog-wide PII/scrub gate — selection
  *is* everything / one report / one presentation.
- ffmpeg transcode — movies are already `.mp4`.
- Exporting the live SDGL graph / admin / edit overlay — authoring-only,
  server-driven, absent from any static bundle.
- A bundle viewer or in-browser preview beyond opening `index.html`.
