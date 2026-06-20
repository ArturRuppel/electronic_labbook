# `eln.analysis` — analysis library + provenance

Reusable analysis code (importable from experiment notebooks) plus
`provenance.py`, which records **in SDGL** how a derived file or curated artifact
was produced.

## The rule

> If it produces an artifact, it gets committed. No third place.

A derived file is only traceable if the code that made it is recoverable. SDGL
*witnesses* files on disk; it can't recover a deleted one. So the recipe lives in
git, and SDGL stores a **graph link** from the file to that recipe — commit
hashes, function name, parameter values, input fingerprints. **Never source code,
never anything executable.** The files themselves are never touched; provenance
is a graph relationship, not file metadata.

## Three artifact categories

| Category | Storage | Provenance |
|---|---|---|
| **Raw data** | filesystem + backup | SDGL content hash (witness only) |
| **Curated artifacts** (hand-drawn segmentations, manual ROIs — irreproducible but mutable) | **data repo** under `notebooks/<CODE>/curated/` | git commit + tool/method (`stamp(kind="curated")`) |
| **Derived data** (regenerable from code + inputs) | filesystem | SDGL graph link: commit + function + params + input hashes (`stamp()`) |

## Data-repo layout

Committed analysis code and curated artifacts live in the data repo:

```
<data_root>/
├── notebooks/
│   └── <CODE>/                 # e.g. notebooks/SORVI/
│       ├── 01_compute.ipynb    # committed analysis notebooks/scripts
│       └── curated/            # committed curated artifacts (segmentations, ROIs)
└── <CODE>-NN/                  # per-experiment data folders (raw/, derived/, ...)
```

## Usage

```python
from eln.analysis import stamp

# Derived file: records the library + notebook commits, function, params,
# and input content hashes. Commits auto-resolve from git; the producing
# experiment is inferred from the CODE-NN in the path.
stamp(
    "SORVI-01/derived/tractions.npy",
    function="eln.analysis.tfm.compute_traction_field",
    params={"pixel_size": 0.65},
    inputs=["SORVI-01/raw/beadstack.tif"],
    notebook="notebooks/SORVI/01_compute_tractions.ipynb",
)

# Curated artifact: irreproducible, so record the tool + method and the
# data-repo commit of the file itself.
stamp(
    "notebooks/SORVI/curated/01_segmentation.tif",
    kind="curated",
    tool="napari",
    method="manual segmentation",
    produced_by="experiment:SORVI-01",
)
```

`stamp()` finds the data root via `labbook.toml` (override with `root=`), and git
commits resolve automatically (override with `library_commit=` / `data_commit=`).
The workflow is **commit, then stamp**: the recorded content hash is the
artifact's committed state.

## Verification

`verify_provenance(root=None)` re-hashes every stamped artifact and returns those
that have drifted from their stamped (committed) state — `{"node_id", "path",
"status"}` with `status` `"modified"` or `"missing"`. The same check is exposed
read-only at `GET /api/sdgl/provenance/verify`.

## Notes

- Content hashing is an inline `sha256` (`eln.hashing.sha256_file`); it can swap
  cleanly to the scan-integrated content hashing when that path is preferred.
- Stamping is an explicit call from a notebook — the scanner does not auto-stamp.
