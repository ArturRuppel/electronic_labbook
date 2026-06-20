# TODO

## ✅ 1. Exported presentations render black (all slides missing) — DONE

**Fixed** (`eln/share.py`): presentation decks are now copied **wholesale**. A
reference that lands inside `presentations/<name>/` pulls the entire deck
directory in one shot (`_copy_tree`, `_PRES_DECK`), so every slide reaches the
bundle regardless of how it's referenced. `export_item`'s presentation branch
copies the whole deck dir directly. Secondary hardening: `_REF` now also matches
single-quoted attrs, reveal.js `data-background*`, and CSS `url(...)`. Tests in
`tests/test_share.py` exercise data-background, single-quote, and unreferenced
assets. (CDN-loaded reveal.js/CSS under `file://` is still untested — revisit
with a real deck.)

<details><summary>original analysis</summary>

## 1. Exported presentations render black (all slides missing)

**Symptom:** in a static bundle produced by `export_all` / `export_item`, every
presentation deck opens as a black page.

**Root cause:** the export copies a deck's assets by regex-scraping its
`index.html` for references, but the regex only matches **double-quoted
`src=`/`href=` attributes**:

- `eln/share.py:21` — `_REF = re.compile(r'(?:src|href)="([^"]+)"')`
- `_collect_assets` (`eln/share.py:66`) copies only what `_local_refs` returns.

Slide decks (reveal.js-style) reference their slide images through attributes
this regex does **not** capture, so the images are never copied and the deck
falls back to the theme's black background. Verified the gap:

| reference form | copied? |
|---|---|
| `<img src="slides/1.png">` | ✅ |
| `<section data-background-image="slides/1.png">` | ❌ |
| `<section data-background="slides/2.png">` | ❌ |
| `<img src='slides/3.png'>` (single quotes) | ❌ |
| CSS `url(slides/x.png)` in `<style>`/`.css` | ❌ |

(The test fixture only uses `<img src="...">`, so the suite passes while real
decks break — `tests/test_share.py:58`.)

Contrast with the live server, which serves the whole deck directory verbatim via
the presentations static mount (`eln/server/app.py:171-183`,
`eln/plugins/presentations.py:29`), so *every* file is reachable regardless of how
it's referenced — which is why decks work live but not in the export.

**Fix direction:** for presentations, stop walking references and instead copy the
entire deck directory wholesale (decks are already self-contained dirs under
`presentations/<name>/`). Both `export_all` (which reaches decks transitively via
`presentations.html` links) and `export_item`'s `presentation` branch
(`eln/share.py:166-178`) need this. Secondary hardening: broaden `_REF` to also
catch `data-background*`, single-quoted attrs, and CSS `url(...)`.

Also note: if decks load reveal.js/CSS from a CDN (`http(s)://`), those are
dropped as external (`_EXTERNAL`, `eln/share.py:20`) and won't load under
`file://` offline — worth confirming once a real deck is available.

</details>

## ✅ 2. SDGL page absent from export — DONE (option a)

**Decision (user):** pre-render a static SDGL snapshot.

**Done.** `export_all` now writes the SDGL graph as the bundle's front door:
- `eln/share.py:_write_sdgl_snapshot` dumps `SDGL.tree()` +
  `list_findings("unmatched")` to `sdgl_data.json` (same shape the live
  `/api/sdgl/tree` + `/scan/unmatched` return), copies the code-repo
  `catalog/sdgl.html` into the bundle via `_staticize_sdgl` (drops `auth.js`,
  injects `window.SDGL_STATIC = true`, repoints its own Data Graph link), and
  redirects the bundle root `index.html` to `sdgl.html`.
- `catalog/sdgl.html` gained a `STATIC` branch: in static mode it loads
  `sdgl_data.json` instead of fetching the API and hides every mutating control
  (selection checkboxes, the Backup button, the Open-in-OS buttons).
- `_staticize` now **repoints** the Data Graph nav link/home card to `sdgl.html`
  (instead of dropping them), so the graph is reachable from every page in the
  bundle. `sdgl.html`/`sdgl_data.json` are treated as known generated siblings so
  those links don't get flagged missing.
- Tests: `test_export_all_writes_static_sdgl_snapshot` + updated staticize/layout
  assertions in `tests/test_share.py`.

<details><summary>original analysis</summary>

## 2. Homepage retired in favor of SDGL page, but SDGL page is absent from export

**Current behavior:**
- The live server serves `sdgl.html` at `/` (`eln/server/app.py:135-137`); the
  generated `index.html` home page is effectively retired (only reachable by
  explicit URL).
- `export_all` only runs the generators (`generate_all`, `eln/share.py:124`),
  which emit `index.html` (old home), `experiments/protocols/reports.html`, and
  the presentations page. **`sdgl.html` is never produced or copied** — it's a
  static *code-repo* asset served from `ASSETS_DIR` (`eln/server/app.py:49`),
  outside the generator set.
- So the bundle's landing page is the retired home page, and the SDGL page the app
  now uses as its front door is missing entirely.

**Complication — SDGL is not trivially static-exportable:** `catalog/sdgl.html`
is fully API-driven. It fetches live endpoints at load time and throughout:
`/api/sdgl/tree`, `/api/sdgl/scan/unmatched`, `/api/sdgl/open`,
`/api/sdgl/backup/*` (`catalog/sdgl.html:161,204-205,561,578,...`). None of these
exist in a `file://` / GitHub Pages bundle, so copying the file verbatim yields a
non-functional page. The export's `_staticize` even deliberately strips the
"Data Graph" nav link/home card (`<a href="/">`) precisely because `/` is this
dynamic page (`eln/share.py:24-25,42-48`).

**Fix direction (needs a decision):**
- (a) Pre-render a *static snapshot* of the graph at export time: dump
  `SDGL.tree()` (and any other needed reads) to a JSON file in the bundle and add
  a static-mode branch in `sdgl.html` that loads the JSON instead of `fetch`-ing
  the API (hiding mutating controls: scan, open, backup). Then make the bundle
  root redirect to / be the SDGL page to match the live app.
- (b) Cheaper interim: keep `index.html` as the bundle landing page, but make it
  reflect the current app and explicitly document that the interactive SDGL view
  is live-only.

Recommend confirming desired scope before implementing (a vs b).

</details>

## ✅ 3. Auto-generate a per-series report — DONE

**Decisions (resolved by user):** committed markdown stubs, marker-delimited
generated block.

**Done.** New `generate_series_reports(root)` in `eln/generators/reports.py`
scaffolds/refreshes one auto report per series under `reports/auto/<CODE>.md`.
Each stub carries a marker-delimited block (`<!-- AUTO:START -->` …
`<!-- AUTO:END -->`) containing `**Series:** CODE`, an optional `**Date:**`
(earliest file-derived date, same source as the overview table), and
`{{experiments}}`. Because it declares `**Series:** CODE`, the existing
`generate_reports` `{{experiments}}` path renders it and the SDGL
`_sync_reports` scanner indexes it — zero extra wiring. Dedup: a series already
covered by a hand-authored report (declared *outside* `reports/auto/`) is skipped
(exactly one report per series), and the auto stub never counts as claiming its
own series. Regeneration rewrites only the marked block (refreshing the date),
preserving prose a human adds around it. Exposed as
`python -m eln.generators.reports <root> --scaffold-series`. It is a deliberate
scaffolding step (writes into the data repo's `reports/`), **not** part of the
read-only `generate_all` catalog build. Tests:
`tests/generators/test_series_reports.py`.

Note: this scaffolds stubs for series lacking a report; it does **not**
auto-rewrite existing hand-authored reports in place ("migrate existing reports").
Those already render the same `{{experiments}}` block via their own
`**Series:**` line, so no migration is required for them to work — wrapping their
generated bits in `AUTO` markers (so the scaffolder could refresh their date too)
is left as optional follow-up.

<details><summary>original notes</summary>

## 3. Auto-generate a per-series report; migrate existing reports to it

**Goal:** every experiment series should automatically get a report whose title is
the series ID + title and which contains the summary block reports already render.
Existing hand-written reports should be migrated onto that structure. Reports that
have no experiment link (e.g. the Bluesky thread) keep existing standalone.

**Done:** report card titles now match the experiment. A report that declares
`**Series:** CODE` shows `CODE — <experiment_codes title>` in its header (the
markdown H1 is ignored for the header, still rendered in the body); standalone
reports keep their H1 (`eln/generators/reports.py:lookup_series_title` +
title logic in `generate_reports`; test in `tests/test_share.py`). **Still to do:**
the *auto-generation* of a report per series (below).

**Current state (already in place):**
- Reports are hand-authored markdown under `reports/**/*.md`
  (`eln/generators/reports.py:605`). There are no auto-generated reports.
- The "summary block" the request refers to is the series overview: an author
  writes `**Series:** CODE` plus a `{{experiments}}` token, and
  `build_experiments_block()` (`reports.py:426`) renders the header (series code +
  title), a table of active repetitions (IDs, file-derived dates, cell types,
  microscope, channels, tags), and the deduplicated protocols used.
- **Standalone reports already work**: a report with no `{{experiments}}` token is
  passed through as plain markdown (`reports.py:645`), so the Bluesky-thread case
  needs no change.
- Series are the rows of the `experiment_codes` table (title ↔ code,
  `eln/db/schema.sql:61`).
- Report↔experiment linkage already exists and is first-class in the DB and graph:
  the SDGL scanner's `_sync_reports()` (`eln/sdgl/engine.py:568`) reads each
  report's `**Series:** CODE` line and populates the `reports` table, a
  `report:<id>` graph node (metadata `{file_path, title, series}`), and a
  `has_report` edge from every active `experiment:CODE-NN` to the report. Reports
  with no `**Series:**` get no edges (the Bluesky case). The `reports.html`
  generator and the scanner both key off the *same* `**Series:** CODE` regex.

**What to build:**
1. **Auto report per series.** Iterate `experiment_codes`; for each series emit a
   report titled `CODE — <title>` containing `build_experiments_block(code)`. Its
   date can reuse the series' earliest file-derived date (same source the overview
   table uses).
2. **Migrate existing reports.** Convert current hand-written series reports to the
   auto form. Since authors will still want narrative prose, the auto block should
   be the *skeleton* and human notes layered on top — not duplicated. A series that
   already has a hand-authored `**Series:** CODE` report must not also get a
   separate auto report (dedup by series code).
3. **Standalone reports stay as-is** (no series link), already supported.

**Resolved — linking model:** keep `**Series:** CODE` in the report markdown as the
single source of truth. No new linking mechanism is needed: the linkage is already
first-class in both the DB (`reports` table) and the graph (`report:` nodes +
`has_report` edges), all auto-derived from that one declaration by the SDGL scanner
(`eln/sdgl/engine.py:568`). An auto-generated per-series report therefore only has
to carry a `**Series:** CODE` line and it is indexed by the existing scanner with
zero extra wiring — and rendered by the existing `{{experiments}}` path. Concretely:
- Do **not** build the feature on the `experiment_reports` junction table. It is
  dead: declared in the schema and pruned in `_sync_reports`, but **never inserted
  in production** (only `tests/db/test_dump_rebuild.py:31` populates it). The actual
  experiment↔report link lives in `has_report` edges. Leave it untouched here;
  dropping it is a separate cleanup.

**Decisions still to resolve before implementing:**
- **Storage:** generate markdown stub files into `reports/` (committable, editable,
  exportable, integrates with existing pipeline) **vs.** synthesize the cards
  virtually at build time (no files, but not user-editable and needs export
  wiring). The committed-stub approach fits the rest of the system better — and it
  means the auto reports flow through `_sync_reports` for free (see resolved point).
- **Authoring overlay:** how a human adds prose to an auto report without it being
  overwritten on regeneration (e.g. a generated block delimited by markers, with a
  free-text section the generator never touches).

</details>

## ✅ 4. Add a per-protocol export button (mirror reports & presentations) — DONE

**Done.** Implemented as planned:
1. `generate_protocol_catalog` gained `only=<protocol id>` + `output_name=`
   (filters to the group whose latest-version id matches).
2. `export_item` has a `"protocol"` branch: renders that one protocol flat as
   `index.html`, nav stripped, assets walked; unknown id → `ValueError`.
3. `/api/export/preview` and `/api/export/start` accept `"protocol"`.
4. `edit-overlay.js` adds an **Export** button per `.protocol-group` header
   (`runExport('protocol', id, 'protocol')`, with `stopPropagation`).
5. Tests added in `tests/test_share.py` (only-one render, flat-no-nav export,
   not-found). Fixture gained a second protocol to prove filtering.

<details><summary>original plan</summary>

## 4. Add a per-protocol export button (mirror reports & presentations)

**Goal:** each protocol on `protocols.html` should get an **Export** button, the
same way reports and presentations already do.

**Current state:**
- Reports and presentations have per-item Export buttons wired in the edit
  overlay (`catalog/edit-overlay.js:174-186` for `.report-card[data-report-src]`,
  `:191-203` for `tr[data-pres-dir]`); both call
  `runExport(mode, id, label)` → `/api/export/preview` + `/api/export/start`.
- Protocols only get an **Edit** button, no Export (`edit-overlay.js:142-156`).
  Protocol groups already carry the needed identifier: `id="{protocol id}"`
  (`eln/generators/protocols.py:415`).
- The backend `export_item` (`eln/share.py:147`) handles only `kind` `"report"`
  and `"presentation"`; the API routes whitelist the same two modes
  (`eln/server/app.py:404-408,425-429`).
- Unlike reports, the protocol generator has no single-item rendering path:
  `generate_protocol_catalog` (`eln/generators/protocols.py:351`) has no
  `only=` / `output_name=` params (reports gained these for export —
  `generate_reports`).

**What to build:**
1. **Generator:** add single-protocol rendering to `generate_protocol_catalog`
   (an `only=<protocol id>` + `output_name=` path, mirroring `generate_reports`),
   rendered flat as `index.html`, nav stripped.
2. **Backend:** add a `"protocol"` branch to `export_item` that renders that one
   protocol and walks its assets (protocols may embed images via `file_path` /
   markdown — confirm and copy them like the report branch does).
3. **API:** add `"protocol"` to the accepted-mode tuples in
   `/api/export/preview` and `/api/export/start` (`app.py:404-408,425-429`).
4. **Overlay:** in the `protocols.html` branch, add an Export button per
   `.protocol-group` that calls `runExport('protocol', group.id, 'protocol')`
   (and `stopPropagation` like the Edit button).
5. **Tests:** mirror the report/presentation export tests in `tests/test_share.py`.

</details>

## ✅ 5. Build the notebooks feature — DONE

**Done.** New file-driven generator `eln/generators/notebooks.py` scans
`ROOT/notebooks/*.ipynb`, classifies each stem to an experiment ID via the SDGL
grammar (session/series/unmatched), renders markdown+code cells from the `.ipynb`
JSON with the stdlib (no nbconvert; outputs ignored, with a warning if present),
and lists produced artifacts from `sdgl.db` `generates` edges (with
`verify_provenance` status). Wired into nav (after Protocols), `generate_all`, the
server's `CORE_GENERATED_PAGES`, and `share._CATALOG_PAGES`. Sample notebook +
full unit tests added. The design spec and implementation plan
(`docs/superpowers/{specs,plans}/2026-06-20-notebooks*.md`) were executed and
removed from the working tree (kept in git history, per the plan's final step).

## 6. No interface to commit (stamp) artifacts

**Confirmed gap:** there is currently **no interface to commit/record an
artifact's provenance**. Stamping is library-only:

- `stamp(...)` lives in `eln/analysis/provenance.py:67` and is exported from
  `eln.analysis` — it is meant to be called *programmatically from notebook code*
  (`from eln.analysis import stamp`). The sample notebook
  (`sample_data/notebooks/SORVI-01.ipynb`) shows this as the intended usage.
- There is **no CLI subcommand**: `eln/cli.py` exposes `admin`, `scan`, `verify`,
  `timestamp`, `regenerate`, `rebuild`, `publish`, `backup`, `export` — no
  `labbook stamp`.
- There is **no server route / admin-UI control**: only the *verify* side is
  exposed (`verify_provenance()` via `/api/sdgl/provenance/verify`, plus
  `/api/timestamp/verify`). Recording a stamp has no endpoint and no button.

So an artifact only becomes a `dataset` node with a `generates` edge if a human
runs `stamp()` inside Python; nothing in the CLI, server, or notebooks page lets a
user *commit* an artifact through an interface.

**What to build (needs design):** an interface to stamp/commit artifacts. Options
to weigh — a `labbook stamp <path> [--kind derived|curated] [...]` CLI subcommand
(fits the existing CLI, scriptable); and/or a server route + a control on the
notebooks/SDGL page to stamp a produced file. The notebooks provenance panel
(item 5) already *reads* `generates` edges, so a "commit/stamp this artifact"
affordance there is a natural home. Decide CLI vs. UI (or both) and the curated
vs. derived entry path before implementing.
