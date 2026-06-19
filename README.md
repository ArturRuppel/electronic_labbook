# Electronic Lab Notebook

**A filesystem-centric, tamper-evident electronic lab notebook for the data you already have on disk.**

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

> ⚠️ **Status: clean rebuild in progress.** This repository is being stood up
> from scratch as the public, code-only home of the project. See
> [`docs/ROADMAP.md`](docs/ROADMAP.md) for the full plan and sequencing.

## Why this exists

The major electronic lab notebooks (eLabFTW, Benchling, RSpace) are
**notebook-centric**: they are authoritative for the text you type *into* them.
Your real data — the microscopy stacks, the analysis outputs, the figures —
lives somewhere else, on a file server, loosely linked at best.

This project is **filesystem-centric**. It indexes the actual data tree you
already have, links it into a graph (experiment → protocol → analysis → report
→ the real files), and makes that lineage **verifiable**.

### The differentiator: SDGL (Scientific Data Graph Layer)

`SDGL` is a graph index layered over the notebook. It scans configured roots and
recognizes a naming grammar where a folder named exactly `CODE-NN` ties data to an
experiment: the 5-character `CODE` identifies the experiment series and `NN` is
the repetition, with an `X` before the number marking an excluded session — e.g.
`SORVI-01`, `COV2D-X03`. A bare `CODE` folder (no `-NN`) holds aggregate analyses
spanning the whole series. Downstream structure lives in the nesting *beneath* a
recognized folder, not in its name — e.g. `SORVI-01/raw`, `SORVI-01/analysis`.
For every recognized folder it records every filesystem sighting (size, mtime,
existence) of every artifact.

- The **notebook** (`experiments.db`) is authoritative for experiment metadata.
- The **filesystem** is authoritative for raw/derived data.
- **SDGL** is authoritative for relationships, filesystem sightings, and graph
  navigation.

### The north star: tamper-evident provenance

Built on SDGL's filesystem sightings, in three additive layers:

1. **Content hashing** — `sha256` per artifact, stored on scan. Detects any
   change or corruption to raw data.
2. **Hash-chained audit log** — append-only history where each record embeds the
   previous record's hash.
3. **RFC 3161 trusted timestamps** — cryptographic proof-of-existence anchored to
   a public Time Stamping Authority.

This gives integrity over the *real data files*, not just notebook text — the gap
worth open-sourcing.

## Architecture: two repositories

This project is split across two sibling repos so that **code is public and data
stays private**, and so that **no binary database is ever committed**.

| | `electronic_labbook` (this repo) | `electronic_labbook_database` |
|---|---|---|
| **Host** | GitHub, **public** | GitLab, **private** |
| **Contents** | code only | data only |
| Schema/migrations, `dump_db.py` / `rebuild_db.py` | ✅ | — |
| Generators, Flask server, SDGL engine, plugin API, overlay/admin | ✅ | — |
| Synthetic sample dataset (runs out-of-the-box) | ✅ | — |
| `sdgl.toml` | `sdgl.toml.example` (placeholder paths) | real (absolute paths) |
| LICENSE, README | ✅ | — |
| `experiments.sql` (diffable DB dump) | — | ✅ |
| `reports/`, `protocols/`, presentation slides | — | ✅ |
| `*.db` binaries | gitignored | gitignored |
| Static export (`catalog/`) | — | built & served via GitLab Pages |

### Why the database is never committed

`experiments.db` and `sdgl.db` are **build artifacts**. The versioned, line-
diffable form is `experiments.sql` (a deterministic `.iterdump()`), which lives in
the data repo. `rebuild_db.py` reconstructs the binary from it. This keeps git
history small and human-reviewable.

## Repository layout

```
electronic_labbook/
├── LICENSE                  # AGPL-3.0
├── README.md
├── pyproject.toml
├── requirements.txt
├── sdgl.toml.example        # config template — copy to sdgl.toml (gitignored) and edit
├── eln/                     # the Python package
│   ├── db/                  # schema, migrations, dump_db.py / rebuild_db.py
│   ├── sdgl/                # the SDGL scan engine + naming grammar
│   ├── generators/          # catalog / reports / home / protocol page generators
│   ├── server/              # Flask API, overlay/admin injection, publish flow
│   └── plugins/             # plugin API + extension points
├── catalog/                 # static frontend assets (overlay, admin, css); HTML is generated
├── sample_data/             # synthetic dataset so the app runs out of the box
└── docs/
    └── ROADMAP.md           # the plan: vision, strategy, sequenced steps
```

Most subdirectories are scaffolding right now — see `docs/ROADMAP.md` for which
step fills each in.

## License

[GNU AGPL-3.0](LICENSE). Chosen deliberately for **maximum open-sourceness**: the
network clause (§13) ensures that anyone who runs a modified version as a hosted
service must offer their users the source.
