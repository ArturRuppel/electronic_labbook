# Electronic Lab Notebook

**A filesystem-centric, tamper-evident electronic lab notebook for the data you
already have on disk.**

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
![Status: pre-alpha](https://img.shields.io/badge/status-pre--alpha-orange.svg)

> The feature set described below is implemented; the project is in a
> testing-and-polishing phase rather than feature work. It is built primarily for
> my own lab, but it is meant to be reusable — if the model below fits how your
> data is laid out, it should work for you too.

## The idea

The established electronic lab notebooks — eLabFTW, Benchling, RSpace — are
**notebook-centric**. They are authoritative for the text you type *into* them,
and your actual data lives somewhere else: microscopy stacks, analysis outputs,
figures, sitting on a file server and linked back to the notebook loosely, by
hand, if at all. The notebook and the data drift apart, and nothing notices.

This project inverts that. It is **filesystem-centric**: the data tree you
already maintain is the source of truth, and the notebook is an index *over* it.
It reads your existing folder structure, links it into a graph — experiment →
protocol → analysis → report → the real files on disk — and keeps that lineage
**verifiable**.

Three things are authoritative, each for what it is actually good at:

| Concern | Source of truth |
|---|---|
| Experiment metadata (titles, notes, parameters) | the notebook (`experiments.db`) |
| Raw and derived data | the filesystem |
| Relationships, file sightings, graph navigation | **SDGL** |

Nothing is copied into a walled garden. Your data stays where it is, in the
layout you already use.

## What the notebook tracks: four kinds of content

Not everything on disk deserves the same treatment. The project distinguishes
four kinds of content, each handled according to how it came to exist and how
replaceable it is:

| Kind | Treatment | Why |
|---|---|---|
| **Raw data** | **Immutable** — never modified | Irreplaceable measurements; the ground truth everything else derives from. Too large for git, so it lives on the filesystem, is indexed in place by SDGL, and is backed up off-machine. |
| **Code / notebooks** | **Versioned in git** (in the data repo) | The recipes that turn raw data into results. Every change is committed and versioned, so any result can be traced to the exact code that produced it. |
| **Curated derived data** | **Versioned in git**, like code | Hand-made, human-judgment outputs — manual segmentations, ROIs, curated tracking. Irreproducible but revisable, so they are committed for history and recoverability — but *not* frozen, because people legitimately revise them. |
| **Automatic derived data** | **Disposable** | Anything a notebook can regenerate deterministically from raw data plus code. Not committed and not backed up: cheaper to recompute than to store. |

The dividing line for derived data is *who made the decisions in it*. If a result
falls out of code automatically, it is disposable — the code and the raw data are
its only durable form. If a human made irreversible judgment calls (drawing a
mask, correcting a track), that judgment is itself a primary artifact and is
versioned like code.

**Notebooks are the link.** A notebook reads immutable raw data and writes derived
data, and committing it records the recipe that connects the two. Experiment
notebooks and analysis code live in the **data repo**, alongside the curated
artifacts they produce; only the *reusable* analysis library ships with this
public code repo (`eln/analysis/`). That library carries a `stamp()` /
`verify_provenance()` pair for recording and checking that connection.

### Stamping derived data

Calling `stamp(path, ...)` on a derived artifact records its provenance **as a
graph relationship in SDGL, never as file metadata** — the artifact on disk is
left byte-for-byte untouched. The artifact becomes a `dataset` node, and the
recipe is attached as metadata on a `generates` edge from the producing
experiment (inferred from the `CODE-NN` folder in the path, or passed
explicitly). A stamp distinguishes two kinds:

- **`kind="derived"`** (automatic outputs) records the full reproduction recipe:
  the library repo, commit, and function that produced it; the data-repo commit
  and notebook path; the call parameters; and the SHA-256 content hashes of every
  input file. Inputs that are themselves stamped get a `derived_from` edge, so the
  lineage is walkable in the graph.
- **`kind="curated"`** (human-made artifacts) records the `tool` and `method`
  instead of a code recipe, plus the data-repo commit of the file itself.

Every stamp also stores the artifact's own content hash and a UTC timestamp.
Because the recipe is *references only* (commits, dotted function names, parameter
values, input fingerprints) and never source code, the recipe itself stays in
git, where it can be diffed and recovered.

`verify_provenance()` checks every stamped artifact against its recorded hash and
flags any that has drifted — `modified` (content differs) or `missing` (no copy
found). Curated artifacts live in the data repo and are re-hashed in place;
derived artifacts live on the filesystem and are keyed by their experiment-relative
path (`<CODE-NN>/…`, machine-independent) and resolved — and hash-checked — through
the scan index. It is also exposed by the server at `/api/sdgl/provenance/verify`.

> The classification and the provenance machinery are in place; `stamp()` is a
> library call invoked from notebooks (there is no `labbook stamp` CLI yet), and
> the notebook *authoring* workflow on top of it is still being built out.

## SDGL — the Scientific Data Graph Layer

SDGL is the graph index that makes the filesystem-centric model work. It scans
the roots you configure and recognizes a small naming grammar that ties folders
on disk to experiments:

- A folder named **exactly `CODE-NN`** is one session of an experiment. `CODE` is
  a five-character experiment-series identifier (letters and/or digits); `NN` is
  the repetition number, zero-padded. An `X` before the number marks a session
  that was run but excluded — e.g. `SORVI-01`, `SORVI-02`, `COV2D-X03`.
- A folder named **just `CODE`** (no `-NN`) holds aggregate analyses that span the
  whole series.
- Everything downstream lives in the **nesting beneath** a recognized folder, not
  in its name — e.g. `SORVI-01/raw`, `SORVI-01/analysis`.

For every recognized folder, SDGL records each filesystem *sighting* of every
artifact: its path, size, and modification time, and whether it still exists.
That record of what was on disk, and when, is the foundation the provenance layer
is built on. No notebook-centric ELN has an equivalent.

## Tamper-evident provenance

The reason this is worth open-sourcing is integrity over the **real data files**,
not just notebook text. It is built on SDGL's file sightings in three additive
layers, smallest to largest:

1. **Content hashing** — a SHA-256 per artifact, stored on scan. Detects any
   change or corruption to raw data. A file is only re-hashed when its size or
   modification time changes, so repeated scans stay cheap.
2. **Hash-chained audit log** — an append-only history in which each record
   embeds the previous record's hash, making the graph's history tamper-evident.
3. **RFC 3161 trusted timestamps** — on publish, a digest of the snapshot is
   anchored to a signed token from a public Time Stamping Authority and committed
   alongside the data. This is cryptographic proof that the data existed in that
   form at that time — something git alone cannot provide.

Layers 1 and 3 are opt-in via configuration (see `labbook.toml.example`);
`labbook verify` re-checks both hashes and timestamps and flags any drift.

## Install and configure

Requires Python 3.9+.

```bash
pip install -e .
```

Then create your configuration by copying the template and pointing it at your
data:

```bash
cp labbook.toml.example labbook.toml   # labbook.toml is gitignored
```

Edit `labbook.toml` to set `data_root` (the directory holding your notebook data)
and the `scan_roots` SDGL should index. The template documents every option —
content hashing, channel aliases, timestamping, and export — inline.

Start the authoring view and server:

```bash
labbook admin          # opens the admin/authoring UI in your browser
labbook admin --scan   # ...and run an SDGL scan on startup
```

## Commands

Everything is driven by the `labbook` CLI:

| Command | What it does |
|---|---|
| `labbook admin` | Start the server and open the authoring/admin view |
| `labbook scan [--hash]` | Scan configured roots; `--hash` forces content hashing for the run |
| `labbook verify` | Recompute file hashes and verify timestamps; report drift |
| `labbook timestamp --retry` | Retry any RFC 3161 timestamps left pending by a TSA outage |
| `labbook regenerate` | Rebuild the static catalog HTML from the database |
| `labbook rebuild` | Reconstruct the binary database from `experiments.sql` |
| `labbook publish` | Dump the DB to `experiments.sql`, commit, and push (with timestamping) |
| `labbook backup` | Launch the data backup flow |
| `labbook export --all \| --report PATH \| --presentation DIR --dest OUT` | Write a self-contained static HTML bundle |

`labbook export` produces a relative-linked bundle that opens over `file://` with
no server — suitable for a shared drive or static hosting.

## How the project is organized

```
electronic_labbook/
├── eln/                     # the Python package
│   ├── db/                  # schema, migrations, dump/rebuild
│   ├── sdgl/                # the scan engine + naming grammar
│   ├── analysis/            # reusable analysis library + provenance stamps
│   ├── generators/          # catalog / report / home / protocol page generators
│   ├── server/              # Flask API, authoring overlay, publish flow
│   ├── plugins/             # plugin API and extension points
│   ├── hashing.py           # content hashing
│   ├── timestamp.py         # RFC 3161 timestamping
│   └── share.py             # static-bundle export
├── catalog/                 # static frontend assets; HTML is generated
├── sample_data/             # synthetic dataset (no real research data, no PII)
└── labbook.toml.example     # configuration template
```

### Two repositories: public code, private data

The project is split across two sibling repos so that **code is public and data
stays private**, and so that **no binary database is ever committed**.

| | `electronic_labbook` (this repo) | `electronic_labbook_database` |
|---|---|---|
| Host | GitHub, public | GitLab, private |
| Contents | code only | data only |
| Holds | engine, server, generators, schema, the reusable analysis library, sample data | `experiments.sql`, reports, protocols, slides, experiment notebooks + analysis code, curated artifacts |

`experiments.db` and `sdgl.db` are treated as build artifacts and are never
committed. The versioned, line-diffable form is `experiments.sql`, a
deterministic dump that `labbook rebuild` reconstructs the binary from. This
keeps git history small and human-reviewable.

## License

[GNU AGPL-3.0-or-later](LICENSE), chosen deliberately. The network clause (§13)
ensures that anyone who runs a modified version as a hosted service must offer
their users the source — keeping derivatives of an integrity-focused tool open.
