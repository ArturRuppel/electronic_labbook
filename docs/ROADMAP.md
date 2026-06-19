# Roadmap

_Last updated: 2026-06-19_

This roadmap is the single source of truth for where the personal electronic lab
notebook is going and the order we get there. It folds in what used to live in
`TODO.md`. It records the strategic decisions, the **clean-rebuild** refactor
that turns this into an open-source tool, and the feature backlog — sequenced.
Each numbered step below gets its own design spec → implementation plan →
implementation cycle; this document is the map, not the specs.

## Vision

Turn this ELN into an open-source tool whose differentiator is **SDGL** —
**tamper-evident provenance over the data you already have on disk**. The major
notebooks (eLabFTW, Benchling, RSpace) are *notebook-centric*: authoritative for
the text you type into them. We are *filesystem-centric*: we index the real data
tree, link it into a graph, and make that lineage verifiable. That is the gap
worth open-sourcing.

## Key decision: do NOT adopt eLabFTW

eLabFTW is excellent but the wrong base for us:

- **License:** AGPLv3 (copyleft + network clause). We cannot lift its code into
  our project without relicensing the whole thing.
- **Stack:** PHP + MySQL monolith. We are Python/Flask + SQLite. There is no
  "use parts of it" across that boundary — only run-it-as-a-service.
- **Model mismatch:** it is notebook-centric and has no equivalent to SDGL's
  filesystem graph. Adopting it would *replace the part we value* to gain a
  property we can add ourselves.

**What we borrow is open *standards and ideas*, not code:** RFC 3161 trusted
timestamping and the `.eln` export/interchange format. Both are implementable
natively in Python.

## The differentiator: SDGL (Scientific Data Graph Layer)

`sdgl.py` + `sdgl.db` — a graph index (`nodes`, `edges`, `file_locations`,
`scan_findings`) layered over the ELN. Per the
[SDGL design](docs/superpowers/specs/2026-06-18-sdgl-design.md):

- The **ELN** is authoritative for experiment metadata.
- The **filesystem** is authoritative for raw/derived data.
- **SDGL** is authoritative for relationships, filesystem sightings, and graph
  navigation.

It scans configured roots, recognizes a naming grammar (`AA00_raw`,
`AA00_analysis_tfm`, `AA00+AB01_aggregate_analysis_…`), and links experiments →
protocols → analyses → reports → actual files (tracking size/mtime/existence).
No major ELN does this.

## Compliance layer (the value-add that motivates open-sourcing)

The driver for all of this is **tamper-evidence**. We add it to our own stack,
anchored in SDGL's `file_locations` (which already records every filesystem
sighting). Three layers, smallest-to-largest — and this gives us something
eLabFTW cannot: integrity over the real data files, not just notebook text.

1. **Content hashing** — `sha256` per artifact, stored on scan. Detects any
   change/corruption to raw data. Stdlib only, low risk, immediately useful.
2. **Hash-chained audit log** — append-only history where each record embeds the
   previous record's hash. Tamper-*evident* graph history. No dependencies.
3. **RFC 3161 trusted timestamps** — send a node/report hash to a free Time
   Stamping Authority, store the signed token. Cryptographic proof-of-existence;
   this is eLabFTW's headline compliance feature. (`rfc3161ng` + public TSA.)

This layer is a goal, not a prerequisite for the refactor — but it is *why* the
project is worth opening up, so it lives here as the north star.

---

# Strategy: clean rebuild, not in-place refactor

We stand up **two new sibling repos** beside the current project and **port only
what's needed, in the right order** — rather than untangling the existing
~428 MB repo in place. A greenfield rebuild makes most of the cleanup problems
*never happen* instead of fixing them after the fact:

- never commit a binary `.db` → no history bloat, no `git rm --cached` dance;
- data/code separation is the **starting layout**, not risky in-place surgery;
- "clean publishable history / no PII / no committed password hash" is the
  starting condition, not a final extraction step;
- the plugin boundary is defined correctly the first time, not disentangled.

The cost is **regression risk**: the old repo's debugged behavior must be ported
as behavior, not re-derived. The [port inventory](#port-inventory--regression-checklist)
below is the acceptance checklist that guards against that.

## Target architecture

| | `electronic_labbook` | `electronic_labbook_database` |
|---|---|---|
| **Host** | GitHub, **public** | GitHub, **private** |
| **Contents** | code only | data only |
| Schema/migrations, `dump_db.py`/`rebuild_db.py` | ✅ | — |
| Generators, Flask server, SDGL engine, plugin API, overlay/admin | ✅ | — |
| Synthetic sample dataset (runs out-of-the-box) | ✅ | — |
| `sdgl.toml` | template (placeholder paths) | real (absolute paths) |
| LICENSE, README | ✅ | — |
| `experiments.sql` (diffable dump, reconstructed history) | — | ✅ |
| `reports/`, `protocols/`, presentation slides | — | ✅ |
| `*.db` binaries (`experiments.db`, `sdgl.db`) | gitignored | gitignored |
| Static catalog (`catalog/`) | curated public subset → **GitHub Pages** | full static bundle written to the **Gaia share** (`file://`) |

Both repos are created as folders **next to** the current project directory.

## Build & deploy flow

- `experiments.db` and `sdgl.db` are **build artifacts**, never committed in
  either repo. `experiments.sql` is the versioned, line-diffable form.
- **Local publish:** materialize dates → `dump_db.py` writes `experiments.sql` →
  commit `experiments.sql` to the **data** repo → push to **private GitHub**
  (gated by a pre-publish guardrail: reject/warn on staged files >90 MB).
- **Sharing is two static-bundle tiers** (see step 7); Gaia is storage-only, so
  no server runs for viewers:
  - **Internal (Gaia share):** the full self-contained catalog + media is written
    to a configured Gaia path; lab members open `index.html` from the mounted
    drive (`file://`). No CI, no server.
  - **Public (GitHub Pages):** the same builder emits a curated subset of
    explicitly-marked items (movies transcoded to mp4), deployed to GitHub Pages
    on demand. Only the scrubbed subset is published; the private data tree never
    leaves the data repo.

## History reconstruction (one-time)

We **rebuild a diffable history** in the data repo from the old binaries instead
of carrying 428 MB of blobs forward:

- walk the current repo's git history; for each commit that changed
  `data/experiments.db`, dump that binary → `experiments.sql`;
- replay each as a commit in the new data repo (preserving author/date/message),
  producing clean, line-level history equivalent to the binary history;
- `sdgl.db` history is **discarded** (build artifact).

This is a standalone migration script run once during Phase A.

---

# Development sequence

Subsystem dependency order is preserved (skeleton → diffable DB → SDGL →
generators → server → CLI → backup → plugin → features → compliance → sharing).
Each step is its own
spec/plan/impl cycle.

## Phase A — Stand up the two clean repos  ·  foundation

### 1. Repo skeletons + boundaries  ·  S–M
Create both sibling repos. Code repo: `LICENSE`, `README` (rewritten around the
provenance value-prop), `.gitignore` (`*.db`), `sdgl.toml` **template** with
config-driven (placeholder) paths — **no hardcoded absolute paths**. Data repo:
real `sdgl.toml`, content dirs. *(absorbs old OSS-packaging cleanup + path
de-hardcoding, done up front for free)*

### 2. Schema + diffable DB plumbing  ·  M  ·  _was Plan G_
Schema/migrations as source of truth; `dump_db.py` (deterministic `.iterdump()`,
tables in name order, rows in rowid order) and `rebuild_db.py` (idempotent
`experiments.sql` → `experiments.db`). DB is a build artifact from commit #1.
See [plans/plan-G-db-versioning.md](plans/plan-G-db-versioning.md) for the
dump/rebuild internals (the "untrack the binaries" half of Plan G evaporates —
they're never tracked here).

### 3. History reconstruction script  ·  M
The one-time migration above: replay binary `experiments.db` history into
diffable `experiments.sql` commits in the data repo.

## Phase B — Port the engine & generation  ·  _regression checklist applies_

### 4. SDGL engine  ·  M  ·  _was Plan G Phase 1 (date half)_
Port `sdgl.py` (scan, naming grammar, `file_locations`) **with** materialized
`experiment_metadata.start_date` (earliest raw-file mtime) so dates ride inside
`experiments.sql` and generators never need `sdgl.db`. Carry the already-debugged
refinements (hidden-folder exclusion, raw-only date derivation) — see checklist.

### 5. Generators  ·  M  ·  _includes Plan F_
`generate_catalog.py` (reads `experiment_metadata.start_date`),
`generate_reports.py` **with the DB-generated report overview built in from the
start** (Plan F: `**Series:** CODE` + `{{experiments}}` → injected series
header, active-rep experiment table with derived dates, deduplicated linked
protocols; also fixes the `# NESFM` title / `Vimentin-Ko` casing / broken
`../../../Data/SORVI/report.md` parent-link regressions), `generate_home.py`,
protocols.
Spec: [docs/superpowers/specs/2026-06-19-report-db-overview-design.md](docs/superpowers/specs/2026-06-19-report-db-overview-design.md) ·
Plan: [plans/plan-F-report-db-overview.md](plans/plan-F-report-db-overview.md)

### 6. Flask server + overlay/admin + publish  ·  M
Port API routes, overlay injection, `admin.js` (incl. the done title↔ID
synchronization), and a publish flow that commits `experiments.sql` to the
**data** repo (not the code repo).

## Phase C — Make it usable & safe

### 7. CLI tools — unified `labbook` command  ·  M
Replace raw `python -m eln.*` invocations with one discoverable entry point,
installed via `[project.scripts]` (`pip install -e .` puts `labbook` on PATH). It
resolves the data-repo root from `ELN_ROOT` (or a small config), overridable per
call. Subcommands:
- `labbook serve [--scan] [--port]` — **ensure the DB exists (build from
  `experiments.sql` only if missing — never clobber unpublished edits)**, start
  Flask, open the browser. (old `labbook`)
- `labbook scan` — filesystem scan with **live feedback** (items found / updated /
  added / errors); the `update_labbook` equivalent, no browser scan button.
- `labbook regenerate` — DB → catalog HTML.
- `labbook rebuild [--force]` — `experiments.sql` → DB (explicit reset; warn when
  `experiments.sql` is newer than the DB rather than auto-overwriting).
- `labbook publish` — DB → `experiments.sql` → commit + **push to the private
  GitHub data remote**, gated by a **pre-publish guardrail** (reject/warn on any
  staged file >90 MB; report repo size) so committing media to git stays
  sustainable.
- `labbook backup` — launch the backup flow (step 8).

The three transforms stay **distinct** (they run in opposite directions):
**rebuild** (sql→DB), **regenerate** (DB→HTML), **publish** (DB→sql). Startup only
*ensures* the DB exists; it never rebuilds over a live working DB.

### 8. Backup tool — selectable data copy  ·  M–L  ·  _was deferred; now scheduled_
Backs up the **identified data** — raw **and** processed/derived, i.e. everything
in SDGL's `file_locations` — *not* the notebook text (already redundant on private
GitHub). UI = **the SDGL tree/graph with a checkbox per item** plus a **Backup**
button that prompts for a destination folder and copies all files of the checked
items there.
- **Destination picker:** server-side **native folder dialog** (tkinter — the
  server is local); typed path as fallback.
- **Layout:** organize the copy by experiment **CODE** (navigable), over mirroring
  raw source paths.
- **Pre-copy preview + guard:** show total file count and **size** before copying
  (can be huge); confirm before proceeding.
- **Duplicate sightings:** the same logical file may be recorded at multiple
  paths. **Dedup by content — hash the copies; if identical, copy one silently; if
  they differ, surface the conflict for the user to pick.** (Reuses the compliance
  layer's content hash once it lands; a lightweight on-the-fly hash until then.)
- **Robustness:** skip + report SDGL-recorded files that no longer exist on disk;
  live progress like the scan.

Distinct from **sharing** (step 12): backup is for *durability/recovery* of the
real data files; sharing is for *read-only views*. Distinct from **publish**:
publish snapshots the notebook to git/GitHub; backup copies the bulk data off to a
location you choose.

## Phase D — Plugin + features on the clean base

### 9. Presentations as the first plugin  ·  M  ·  _OSS plugin template_
Bring presentations in **as** a plugin against clean extension points (nav
registration, generator hook, scan-root contribution, serving route) — defined
correctly the first time rather than coupled-then-extracted. Becomes the
template for future plugins and reinforces the open-source story.

### 10. Feature / polish backlog  ·  port/build once, here
- **B — Catalog visual polish** (M): experiment-overview layout (clipping, full
  width, responsive columns); protocols page styled to match the reports page.
- **D — Field history + channel fungibility** (M–L): datalist autocomplete from
  new distinct-value endpoints; treat fungible channels as equivalent
  (e.g. "GFP" = "488" = "FITC" when configured).

*(Frozen on the old repo to avoid double-porting; built once on the clean base.)*

## Phase E — North star

### 11. Compliance layer
Content hashing (additive to scan — can begin once the SDGL engine lands) →
hash-chained audit log → RFC 3161 trusted timestamps, per the
[Compliance layer](#compliance-layer-the-value-add-that-motivates-open-sourcing).
Content hashing also feeds step 8's duplicate-dedup.

## Phase F — Sharing  ·  _last, per decision_

### 12. Sharing via static bundles: internal (Gaia share) + selective public (GitHub Pages)  ·  M–L
**Gaia is storage-only — a mounted network drive, no compute** — so neither tier
runs a server for viewers. Both are built on **one core: a self-contained
static-catalog bundle builder** that assembles the generated pages + only the
referenced reports/presentations/media into a `file://`-openable tree (relative
links, a **static** landing page — *not* the API-driven `sdgl.html`). This
supersedes the dropped "private GitLab Pages behind a password" plan.

**12a — Internal: write the full bundle onto the Gaia share.** Generate/sync the
complete static catalog + media to a configured Gaia path; lab members open
`index.html` straight from the mounted drive. No server, no auth infra — access =
whoever can mount the share. The live SDGL graph and the edit overlay/admin are
owner-only authoring tools (served by the local `eln.server`) and are simply
absent from the static bundle.

**12b — Public: the same builder, filtered + scrubbed, to GitHub Pages.** Build a
bundle of only **public-marked** items + their media (movies **transcoded to
H.264 mp4** for browser playback) and deploy to **GitHub Pages** on demand.
Public = world-readable: this is the sensitivity/PII gate — only the curated
bundle is published, the private data tree never leaves the data repo.

**Gaia reality (confirmed):** Gaia is auto-mounted at `/gaia` and the lab already
uses it — the shared raw microscopy data lives there (scan roots `gaia-*`:
`/gaia/PCMC_Microscopie/…`, `/gaia/PCMC_PBI/…`), while `reports/` and
`presentations/` live in the data repo. So the internal bundle stays small:
catalog HTML + `reports`/`presentations`/`thumbnails` (they embed their own
figures/movies), written to a **lab-visible `/gaia` folder**. Raw trees stay in
place and are **not** bundled.

**Open questions (scope before building):** which shared `/gaia` folder is the
publish target (lab-visible, not the per-person `…/Artur Ruppel` dirs); bundle
on-disk layout for relative-link / `file://` integrity; movie transcode now
matters for **both** tiers (ffmpeg at build time); Pages target (a **dedicated
public repo** is cleaner than a dir of the code repo); selection UX (persistent
`public` flag vs pick-at-publish-time).

---

## Port inventory / regression checklist

Behavior already debugged in the old repo. Porting must **preserve these as
acceptance criteria**, not re-derive them:

- **Experiment date model** — date is the **earliest raw-file mtime** (the
  start), `qualifier='raw'` only; no ranges/warnings; "-" if no raw files;
  materialized into `experiment_metadata.start_date`.
- **Report dates** — auto-extracted from "Related Experiments" links, falling
  back to directory/filename patterns (`2026-02_NestinKO` → `2026-02`), then file
  mtime; single date or range display.
- **Hidden-folder exclusion** — dot-prefixed dirs/files pruned at scan time
  (both `os.walk` loops + reports glob); prune step removes already-recorded
  hidden paths so a re-scan self-heals.
- **Title ↔ ID synchronization** — `codesByTitle` + inverse `titlesByCode`;
  known code fills its title and vice versa; never clobbers an already-known
  title (clashes left for save-time validation).
- **No timestamp churn** — static footers, date-only "Last updated"; regenerating
  twice produces byte-identical pages.
- **No dead `Date *` field** — removed end-to-end (form, flatpickr, payload,
  refs).
- **CLI scan** — `update_labbook` CLI command with real-time feedback (items
  found / updated / added / errors); no browser scan button.
- **SDGL qualifier display** — per-repetition qualifiers (tags, channels, cell
  types, microscope, live/fixed, comments); summary at the group level.

## Resolved decisions

- **Data-repo host** — **private GitHub** (not GitLab). Both repos live on
  GitHub: code public, data private. `publish` = commit + push there; this is the
  notebook's off-machine redundancy.
- **Media in git** — movies/figures **stay committed in the data repo**, kept
  sustainable by discipline (small files, one version per movie) + a **pre-publish
  guardrail** (reject/warn on staged files >90 MB — GitHub's hard limit is 100 MB
  — and report repo size). No Git-LFS / out-of-git media split needed.
- **Sharing comes last** (Phase F) and is **static-bundle based** (Gaia share +
  selective GitHub Pages); the earlier "GitLab CI renders private Pages for the
  whole catalog behind a password" plan is **dropped** (weak auth, standing infra,
  movies fight Pages/LFS).
- **CLI shape** — one unified `labbook <subcommand>` (over separate scripts);
  installed via `[project.scripts]`, root from `ELN_ROOT`.
- **DB build timing** — startup *ensures* the DB exists (build from
  `experiments.sql` only if missing); rebuild (sql→DB), regenerate (DB→HTML), and
  publish (DB→sql) stay distinct and are never merged.
- **Transition** — **run the old in-place app in parallel** until the clean
  rebuild reaches feature parity, then cut over. New feature work is **frozen on
  the old repo** to avoid double-porting; backlog features are built once on the
  clean base.

## Deferred / won't do

- **Rename conflict resolution** (was Plan A Part 2) — dropped as a browser
  feature. Only needed when correcting an existing database (rare, admin-only),
  and current behavior already fails safe (a free code cascades silently across a
  title's repetitions; a clashing code is a hard error). A transactional cascade
  + confirm dialog is too much permanent UI for a handful-of-times-ever op and
  puts a destructive rename one click away in the normal edit form. If a bulk
  rename is ever genuinely needed, do it as a deliberate CLI script (cf.
  `migrate_remove_date.py`), not in the edit overlay.

## Known cleanup / risks

- **History bloat** (~428 MB `.git`) — resolved structurally: the clean repos
  never commit binaries, and history is reconstructed diffably (Phase A).
- **Regression during port** — mitigated by the port inventory above.
- **Single-user, no auth** — acceptable for a v0 open-source release aimed at
  developer-scientists who self-host; revisit only if real demand appears.
- **Hardcoded naming grammar** — document and make configurable enough not to
  crash on a foreign tree; full configurability is post-v0. (Paths are
  de-hardcoded in step 1.)

## Validate before investing heavily

Before climbing past "open-source as-is," talk to 3–5 other labs (especially
imaging/microscopy groups with large on-disk datasets) to confirm the
*solution shape* fits their pain. Days of conversations can save months of
building the wrong thing.

## Next step

Phases A–B are **done** (steps 1–6: repos, diffable DB, history reconstruction,
SDGL engine, generators, Flask server + publish). Begin **Phase C, step 7** — the
unified `labbook` CLI (serve/scan/regenerate/rebuild/publish/backup) — then step 8
the backup tool. Sharing (Phase F) is intentionally last.
