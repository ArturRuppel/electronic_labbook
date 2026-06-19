# Plan — Analysis library + provenance stamps (Roadmap step 10b)

**Status:** proposed · **Size:** M · **Date:** 2026-06-19

Stand up `eln/analysis/` as the reusable analysis library and add
`eln/analysis/provenance.py` with a `stamp()` utility that records, **in SDGL**,
how a derived file (or curated artifact) was produced. Provenance is a graph
relationship — the files themselves are never touched.

## Goal & guiding rule

> If it produces an artifact, it gets committed. No third place.

A derived file is only traceable if the code that produced it is recoverable.
SDGL *witnesses* files; it can't recover a deleted one. So the recipe lives in
git (library repo + data repo), and SDGL stores a **graph link** from the file to
that recipe: commit hashes, function name, parameter values, and input-file
content hashes — never source code, never anything executable.

## Decisions (locked)

1. **Storage = node + edge metadata** (not a new table). Each derived/curated
   file becomes (or reuses) an SDGL **`dataset` node**; the recipe rides as JSON
   metadata on a **`generates` edge** from the producing node to the file node.
   This matches the roadmap's "provenance is a graph relationship" framing and
   surfaces in the existing graph explorer with no extra wiring. Both
   `dataset` (`CORE_NODE_TYPES`) and `generates` (`CORE_RELATION_TYPES`) already
   exist — **no schema migration required**.
2. **Git commits auto-resolved, override allowed.** `stamp()` resolves the
   library-repo commit (`git rev-parse HEAD` on this package's checkout) and the
   data-repo commit (`git rev-parse HEAD` on the data root) by default; explicit
   `library_commit=` / `data_commit=` args override (this is what tests use). A
   dirty working tree is recorded (`dirty: true`) and warned about, not blocked.
3. **Full step**: scaffold + `stamp()` (derived + curated) + inline `sha256` +
   `notebooks/` layout convention + the SDGL verification/divergence check.

## Background (verified against the code)

- SDGL lives at `<data_root>/sdgl.db`; `eln/sdgl/engine.py` exposes
  `SDGL(root)`, `upsert_node(id, type, ...)`, `upsert_edge(src, tgt, relation,
  metadata)`, `get_node`, `list_edges`, plus helpers `utcnow()`,
  `stable_hash(*parts)` (sha1[:16]), `json_dumps/loads`. Node/edge writers accept
  an optional `conn` for batching.
- Node ids are typed string keys, e.g. `experiment:SORVI-01`, `report:<id>`.
  Experiment folders match `ID_FOLDER_RE` = `^(?P<code>[A-Z0-9]{5})-(?P<excl>X?)
  (?P<rep>\d+)$` — reuse this to infer the producing experiment from a file path.
- `eln/sdgl/backup.py` already streams a `sha256` over a file in 1 MB chunks —
  factor that into a shared helper rather than re-implementing.
- `_git(...)` subprocess patterns exist in `eln/server/publish.py` and
  `eln/db/reconstruct_history.py` — mirror them (`subprocess.run`, `cwd=`,
  capture, returncode check).
- `eln/config.py` `load_config().data_root` gives the data repo when `stamp()`
  isn't passed an explicit `root`.

## Graph shape produced by one `stamp()`

```
node    dataset:<rel_path>                      # the derived/curated file
        metadata = {path, rel_path, content_hash, kind}   # kind: derived|curated
edge    <producer_node>  --generates-->  dataset:<rel_path>
        metadata = {                              # the recipe (derived)
          library:  {repo, commit, function, dirty},
          notebook: {repo, commit, path, dirty},
          params:   {...},
          inputs:   {<rel_path>: "sha256:..."},
          stamped_at
        }
        metadata = {                              # the recipe (curated)
          tool, method,
          notebook: {repo, commit, path, dirty},
          stamped_at
        }
```

`<producer_node>` defaults to the experiment node inferred from the file path
(`experiment:CODE-NN`); overridable via `produced_by=`. Inputs that are
themselves known `dataset` nodes additionally get best-effort `derived_from`
edges (file → input) so lineage is walkable; unknown inputs live only in the
`inputs` map (path + hash).

## Public API (`eln/analysis/provenance.py`)

```python
def stamp(
    path,                      # derived/curated file (abs or rel to data root)
    *, function=None,          # dotted name, e.g. "eln.analysis.tfm.compute"
    params=None,               # JSON-serializable dict
    inputs=None,               # iterable of input file paths
    kind="derived",            # "derived" | "curated"
    tool=None, method=None,    # curated-only descriptors
    produced_by=None,          # explicit producer node id; else inferred
    root=None,                 # data root; else load_config().data_root
    library_commit=None,       # override auto-resolution
    data_commit=None,
) -> dict:                     # returns the stored provenance record

def verify_provenance(root=None) -> list[dict]:
    """Re-hash every stamped file on disk; return divergences:
    [{node_id, path, status}] where status in {ok-omitted, modified, missing}."""
```

- `kind="curated"` requires `tool`/`method`, records the data-repo commit of the
  curated file, and skips library/inputs (irreproducible by definition).
- Content hash is `sha256` of the file at stamp time, recorded as the
  "last committed" baseline (workflow: commit → stamp). `verify_provenance()`
  re-hashes the working copy and flags `modified` on mismatch, `missing` when the
  file is gone.

## Phases

### Phase 1 — Shared hashing helper
- [ ] Add `sha256_file(path, chunk=1<<20) -> str` (returns `"sha256:<hex>"`)
      to `eln/analysis/hashing.py`; refactor `eln/sdgl/backup.py` to use it
      (keeps one implementation). _Tests: hashing of a known byte string._

### Phase 2 — Library scaffold
- [ ] `eln/analysis/__init__.py` exporting `stamp`, `verify_provenance`. Module
      docstring states the "if it produces an artifact, it gets committed" rule
      and that nothing executable is ever stored in the graph.

### Phase 3 — Git resolution
- [ ] `eln/analysis/gitref.py`: `head_commit(repo_dir) -> (commit, dirty)` via
      `git rev-parse HEAD` + `git status --porcelain`; `repo_root(path)` via
      `git rev-parse --show-toplevel`; `remote_url(repo_dir)` best-effort.
      Returns `(None, False)` outside a repo (warn, don't raise).
      _Tests: a tmp git repo (init, commit) → commit resolves, dirty flips._

### Phase 4 — `stamp()`
- [ ] Implement node + `generates` edge writing through `SDGL(root)`; infer the
      producer experiment node from the path via `ID_FOLDER_RE`; compute content
      hash + input hashes; auto-resolve commits (override-able); best-effort
      `derived_from` edges to known input dataset nodes.
      _Tests: derived stamp writes node+edge with expected metadata; curated
      stamp records tool/method + data commit; explicit commit overrides win;
      inferred producer matches `experiment:CODE-NN`._

### Phase 5 — Verification check
- [ ] `verify_provenance()` walks `dataset` nodes carrying `content_hash`,
      re-hashes the on-disk file, returns divergences. Expose it on the SDGL
      explorer as `GET /api/sdgl/provenance/verify` (read-only) for parity with
      the other SDGL endpoints.
      _Tests: unchanged file → no divergence; mutated file → `modified`; deleted
      file → `missing`. Endpoint returns the same list as the function._

### Phase 6 — Layout + docs
- [ ] Document the `notebooks/` data-repo convention: `notebooks/<CODE>/` for
      committed analysis notebooks/scripts, `notebooks/<CODE>/curated/` for
      curated artifacts. Add to the data-repo layout docs (README / generators
      README) and `eln/analysis/README.md` with a stamp() usage example.
- [ ] Update `docs/ROADMAP.md`: mark step 10b done; refresh the status summary.

## Acceptance criteria

- `stamp()` on a derived file under `…/SORVI-01/…` creates `dataset:<rel_path>`
  and a `generates` edge from `experiment:SORVI-01` carrying library+notebook
  commits, params, and input hashes — with the file on disk byte-unchanged.
- A curated stamp records tool/method + data-repo commit and no library/inputs.
- `verify_provenance()` flags a file modified after stamping and a deleted file;
  reports nothing for an untouched file.
- Commit auto-resolution works in a real checkout and is override-able in tests
  (no network, no reliance on a specific commit).
- Full `pytest` suite stays green; no SDGL schema migration introduced.

## Out of scope (later steps)

- Real content-hash-on-scan + dedup (step 11 / step 8) — `stamp()` uses inline
  `sha256` until then, behind the `sha256_file` helper so it swaps cleanly.
- Graph-explorer UI for browsing provenance beyond the verify endpoint.
- Auto-stamping from the scanner; stamping stays an explicit notebook call.
```
