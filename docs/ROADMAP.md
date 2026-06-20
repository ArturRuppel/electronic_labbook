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
| `eln/analysis/` (reusable analysis library + `provenance.py`) | ✅ | — |
| `notebooks/` (committed experiment-specific analysis code) | — | ✅ |

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
generators → server → CLI → backup → plugin → data migration → features →
compliance → sharing).
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

### 8. Backup tool — selectable data copy  ·  M–L  ·  _done_
Backs up **raw data only** — the irreplaceable, too-large-for-git files on the
filesystem. **Curated artifacts** (hand-drawn segmentations, manual ROIs, curated
tracking) and **notebooks** are already in the remote git data repo; they are not
backup targets. This simplifies the backup tool: it handles only the raw data that
cannot live in git. UI = **the SDGL tree/graph with a checkbox per raw-data item**
plus a **Backup** button that prompts for a destination folder and copies all
checked files there.
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

### 9. Presentations as the first plugin  ·  M  ·  _done · OSS plugin template_
Bring presentations in **as** a plugin against clean extension points (nav
registration, generator hook, scan-root contribution, serving route) — defined
correctly the first time rather than coupled-then-extracted. Becomes the
template for future plugins and reinforces the open-source story.

### 9b. One-time data migration (concentrated move)  ·  M  ·  _done_
A single concentrated data move once the presentation plugin (step 9) is in place,
so the whole corpus lands in one pass against final layout/extension points rather
than being dribbled in. **Notebook text (`experiments.db`) is already migrated in
step 3** — this is the binary/source-file corpus that lives in the data repo:
- **reports/** — copy report source (`.md` + figures) into the new data-repo layout.
- **presentations/** — copy slide sources in (depends on step 9's scan-root /
  serving layout being settled).
- **thumbnails / movie posters — regenerated, not copied** (run the generators
  against the migrated corpus; ffmpeg transcode at build time per step 5).
- raw/derived data files — referenced in place by SDGL; not copied here (durability
  is step 8's job).
- **Verify after move:** re-scan + regenerate produces byte-identical pages (no
  timestamp churn) and no broken relative / `file://` links.

### 10. Feature / polish backlog  ·  port/build once, here
- **B — Catalog visual polish** (M) — _done_: experiment-overview layout
  (chip wrapping fixes the clipping; column widths rebalanced to 100%; wider
  1760px container + `min-width` table that scrolls instead of crushing on
  narrow viewports); protocols page restyled as individual cards in a 1000px
  container to match the reports page.
- **D — Field history + channel fungibility** (M–L) — _done_: datalist
  autocomplete from a new distinct-value endpoint (`/api/field-values`) so
  suggestions reflect the whole database, not just loaded rows (now also covers
  channel targets); fungible channel markers collapse to a canonical label when
  configured via `[channels].aliases` in `labbook.toml`
  (e.g. "GFP" = "488" = "FITC").

*(Frozen on the old repo to avoid double-porting; built once on the clean base.)*

### 10b. Analysis library + provenance stamps  ·  M  ·  _done_
Implemented as `eln/analysis/` (`stamp()` / `verify_provenance()`): a derived or
curated artifact becomes a `dataset` node and its recipe rides as metadata on a
`generates` edge from the producing experiment node — no SDGL schema change, and
it surfaces in the graph explorer. Git commits auto-resolve (override-able);
content hashing is an inline `sha256` (`eln.hashing.sha256_file`) until step 11.
`verify_provenance()` (also `GET /api/sdgl/provenance/verify`) flags artifacts
that drift from their stamped/committed state. See `eln/analysis/README.md`.

<details><summary>Original spec</summary>

Stand up `eln/analysis/` in the public repo as the reusable analysis library
(importable from notebooks). Add `eln/analysis/provenance.py`: a `stamp()`
utility that records a provenance entry **in SDGL** linking a derived file
(by content hash + path) to the code that produced it (public-repo commit +
function name, data-repo commit + notebook path, parameter values, `sha256`
hashes of input files). For **curated artifacts** (hand-drawn segmentations,
manual ROIs — irreproducible but mutable human-judgment outputs), `stamp()`
records the tool, method, and data-repo commit of the curated file itself;
these artifacts are committed to the data repo (like notebooks) so git
provides version history and recoverability without making them immutable.
**Files themselves are untouched — provenance is a graph relationship, not
file metadata.** Content hashing from step 11 feeds the input hashes; a
lightweight inline `sha256` is used until then. Add a `notebooks/` directory
to the data-repo layout for committed experiment-specific analysis
notebooks/scripts and curated artifacts. SDGL gains a **verification check**:
flag when a sighted notebook or curated artifact's content hash diverges
from its last committed version.

</details>

## Phase E — North star

### 11. Compliance layer
Content hashing (additive to scan — can begin once the SDGL engine lands) →
~~hash-chained audit log~~ → RFC 3161 trusted timestamps, per the
[Compliance layer](#compliance-layer-the-value-add-that-motivates-open-sourcing).
Content hashing also feeds step 8's duplicate-dedup.

- **Layer 1 — content hashing** · _done_ (see step 11 above).
- **Layer 2 — hash-chained audit log** · **dropped as redundant with git**. Git
  commits are already an append-only, hash-chained, tamper-evident Merkle DAG over
  everything committed (`experiments.sql` + the data repo), pushed off-machine to
  private GitHub; a bespoke `audit.jsonl` over the same notebook edits only
  reimplements that. See the layer-3 design spec's "Why this layer — and why not
  layer 2" section.
- **Layer 3 — RFC 3161 trusted timestamps** · _done_: each `publish` anchors a
  `sha256` digest of the published snapshot (a sorted file manifest) to a signed
  TSA token committed under `timestamps/`, best-effort (TSA failure → `pending`,
  retried by `labbook timestamp --retry`). `labbook verify` and
  `GET /api/timestamp/verify` verify each token (signature against the embedded
  signer cert, chained to the bundled DigiCert Trusted Root G4) and that the live
  snapshot is still anchored. Default TSA is DigiCert (RSA) — freeTSA's EC key is
  unverifiable by `rfc3161ng`. Spec:
  [docs/superpowers/specs/2026-06-20-rfc3161-timestamps-design.md](superpowers/specs/2026-06-20-rfc3161-timestamps-design.md).

## Analysis code provenance

A derived file is only traceable if the code that produced it is recoverable.
SDGL sights files on the filesystem and detects modification or deletion — but
it cannot recover a deleted file. **Detection is not preservation.** Code that
generates research artifacts needs the same durability guarantee as the data
itself: a remote git repository.

**Rule: if it produces an artifact, it gets committed.** No third place.

### Three artifact categories

| Category | Characteristics | Storage | Provenance |
|---|---|---|---|
| **Raw data** | Immutable, irreplaceable, too large for git | filesystem + backup | SDGL content hash (witness only) |
| **Curated artifacts** | Irreproducible but mutable (hand-drawn segmentations, manual ROIs, curated tracking) | **data repo** (`notebooks/CODE/` or `curated/`) | git commit + tool/method |
| **Derived data** | Regenerable from code + inputs | filesystem only | SDGL graph link (commit + function + params + input hashes) |

The general rule: **if it can't be regenerated from code + inputs, it gets
committed.** Curated artifacts are not sacred like raw data — they can be
refined, discarded, and redone — but they can't be regenerated, so they need
version control, not just backup.

**Provenance is a graph relationship, not file metadata.** Files themselves are
untouched. `stamp()` records provenance entries in SDGL linking a file (by
content hash + path) to what produced it — commit hashes, function names,
parameter values, and input file hashes. Never source code, never anything
executable. The graph says *"who made me and how to find the recipe"*; the
recipe itself lives in version control where it can be audited, diffed, and
recovered.

```json
{
  "derived_file": {
    "library": {
      "repo": "github.com/ArturRuppel/electronic_labbook",
      "commit": "a1b2c3d",
      "function": "eln.analysis.tfm.compute_traction_field"
    },
    "notebook": {
      "repo": "gitlab.com/.../electronic_labbook_database",
      "commit": "f4e5d6a",
      "path": "notebooks/SORVI/01_compute_tractions.ipynb"
    },
    "params": {"pixel_size": 0.65},
    "inputs": {
      "SORVI-01/raw/beadstack.tif": "sha256:9f86d08..."
    }
  },
  "curated_artifact": {
    "tool": "napari manual segmentation",
    "data_repo_commit": "f4e5d6a",
    "path": "notebooks/SORVI/curated/01_segmentation.tif"
  }
}
```

SDGL's role for committed code shifts from sole integrity layer to live
verification: it confirms the working copy on disk still matches the committed
version. The repo is the vault; SDGL is the guard.

**Workflow:** write the notebook on the filesystem inside `CODE-NN/analysis/`
(where you naturally work) → when the analysis is done, commit it to the data
repo → `stamp()` records the provenance entry in SDGL → SDGL sights the
filesystem copy and can verify it matches what was committed.

## Phase F — Sharing  ·  _last, per decision_

### 12. Sharing via static bundles: internal (Gaia share) + selective public (GitHub Pages)  ·  M–L  ·  _done_

**Built as one destination-agnostic `labbook export`** (collapsing the two-tier
framing): it writes a self-contained, relative-linked static HTML bundle that
mirrors the served flat-at-root URL space, so the same artifact opens over
`file://` from a Gaia folder or hosts on GitHub Pages. Three granularities —
the whole catalog (`--all`), a single progress report (`--report`), or a single
presentation (`--presentation`) — to a `--dest` folder; the authoring overlay
adds an "Export catalog" button plus per-item Export buttons (choose-folder →
preview/size + overwrite warning → write). The builder (`eln/share.py`) reuses
the generators unchanged, post-processes each page to drop the three server-only
literals (Data Graph nav link + home card, `auth.js`), and transitively copies
**only referenced** assets (auto-dropping source/build cruft). No movie
transcode (the corpus is already mp4); export stops at the folder (no git/Pages
automation — a manual follow-on). The original two-tier design is below.
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
- **Analysis code must be committed** — SDGL is a witness (detects change), not
  a vault (cannot recover). Code that produces derived artifacts must live in a
  remote git repo: reusable library → public repo (`eln/analysis/`),
  experiment-specific notebooks → private data repo (`notebooks/CODE/`). The
  filesystem copy is the working copy; the repo is the durable copy; SDGL
  verifies they match.
- **Provenance stamps carry references, not code** — derived files embed commit
  hashes, function names, parameters, and input hashes. Never source code, never
  anything executable. Embedding code normalizes the expectation that data files
  contain code and invites tooling that eventually evaluates it.
- **Three artifact categories** — raw data (immutable, filesystem + backup,
  too large for git), curated artifacts (irreproducible but mutable — hand-drawn
  segmentations, manual ROIs, curated tracking; committed to the data repo like
  notebooks; git provides history, recoverability, and guilt-free deletion), and
  derived data (regenerable, disposable, filesystem only, provenance in SDGL).
  The general rule: **if it can't be regenerated from code + inputs, it gets
  committed.** Curated artifacts are not sacred like raw data — they can be
  refined, discarded, and redone — but they can't be regenerated, so they need
  version control, not just backup.

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
SDGL engine, generators, Flask server + publish). **Step 7** — the unified
`labbook` CLI (serve/scan/regenerate/rebuild/publish/backup) is done, and
**step 8** — the backup tool (selectable data copy) — is done: `labbook backup`
launches the explorer with per-row checkboxes, a content-hash-deduped preview,
conflict resolution, and live progress. **Step 9** — presentations as the first
plugin — is done: an `eln.plugins` API with four extension points (nav,
generator, serving route, scan-root), discovered from a built-in list plus
third-party entry points, with presentations re-expressed entirely as a plugin.
**Step 9b** — the one-time data migration against the settled plugin layout — is
done, as are the feature-backlog items **10B** (catalog visual polish), **10D**
(field-history autocomplete + channel fungibility), and **10b** (the analysis
library + provenance stamps). **Step 11, layer 1** — content hashing on scan — is
done: an opt-in `[scanner].content_hashing` flag stores a `sha256:` per file in
the SDGL `file_locations` table, recomputed only when size/mtime drift; `labbook
scan --hash` forces it for one run and `labbook verify` (and `POST
/api/sdgl/verify-hashes`) recomputes hashes to flag corruption or tampering.
**Step 11, layer 2** (hash-chained audit log) was **dropped as redundant with
git** (git commits are already a hash-chained, tamper-evident, off-machine
Merkle history of everything published). **Step 11, layer 3 — RFC 3161 trusted
timestamps — is done:** `labbook publish` best-effort anchors a `sha256` digest
of the published snapshot to a signed DigiCert TSA token committed under
`timestamps/` (TSA failure → `pending`, retried via `labbook timestamp
--retry`); `labbook verify` and `GET /api/timestamp/verify` verify each token
(signature against the embedded signer cert, chained to the bundled DigiCert
Trusted Root G4) and that the live snapshot is still anchored. With the
compliance layer complete, **Sharing (Phase F, step 12) is also done**:
`labbook export` (and authoring-overlay buttons) writes a self-contained,
relative-linked static HTML bundle — the whole catalog, a single report, or a
single presentation — droppable on the Gaia share (`file://`) or hostable on
GitHub Pages. That closes the roadmap: every numbered step (1–12) is complete.
