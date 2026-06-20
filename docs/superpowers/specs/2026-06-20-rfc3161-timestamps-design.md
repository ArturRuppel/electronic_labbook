# RFC 3161 Trusted Timestamps — Design (Roadmap Step 11, Compliance Layer 3)

_Date: 2026-06-20_

## Summary

Add cryptographic **proof-of-existence-at-a-time** to the lab notebook by
anchoring each `publish` to an [RFC 3161](https://www.rfc-editor.org/rfc/rfc3161)
trusted timestamp. At publish time we hash the published snapshot and send that
digest to an independent Time Stamping Authority (TSA), which returns a token
signed with its own key attesting the digest existed at a given UTC instant. The
token is committed to the data repo alongside the content it covers.

This is the compliance-headline feature (eLabFTW's marquee property) and the one
guarantee plain git + GitHub **cannot** provide.

## Why this layer — and why not layer 2

The roadmap originally sequenced a hash-chained **audit log** (layer 2) before
timestamps. During design we concluded the audit log is **largely redundant with
git** and dropped it:

- A git commit's SHA hashes its tree **plus its parent commit's hash** — git
  history is already an append-only, hash-chained, tamper-evident Merkle DAG over
  all committed content (`experiments.sql` and the rest of the data repo), with an
  off-machine second copy on private GitHub.
- A bespoke `audit.jsonl` over the same committed notebook edits reimplements git
  inside a git-tracked file. Its only non-redundant slice (manual `sdgl.db` graph
  edits, which are gitignored; sub-publish granularity) is minor and not the
  compliance story.

**What git still cannot do — the gap this layer fills:**

- **Git timestamps are self-asserted and forgeable.** The commit date is a field
  the client sets (`GIT_COMMITTER_DATE`). Git cannot prove a record existed *no
  later than* a date — the core property for priority/IP/regulatory claims.
- **GitHub's server-side push time is transient operational metadata**, not durable
  signed proof: `pushed_at` is overwritten on the next push and Events-API entries
  expire. There is no lasting, per-commit, exportable record binding hash → time.
- **Everything local is rewritable by the owner.** In a single-user notebook the
  only plausible tamperer holds push access; git history and any local log can be
  rewritten and force-pushed.

RFC 3161 breaks this: the token is signed by an **external key the owner does not
hold**, so a past snapshot cannot be backdated or re-anchored. It is
**self-contained** (verifiable offline against the TSA cert, without git or
GitHub) and **independent** (attested by a party the verifier need not trust the
owner about).

### Honest scope

This proves *"these exact file contents existed by this UTC time, attestable to an
independent TSA."* It does **not** prevent tampering and does **not** store
content — git remains the durable content store and the source of diffs. Its
real-world value is realized when a verifier who is **not the owner** needs
convincing (regulator, patent dispute, journal fraud inquiry, collaborator); for
purely personal use, git + GitHub is already sufficient. It is included as the
compliance differentiator and open-source selling point.

## Decisions

| Decision | Choice |
|---|---|
| Event/anchor unit | **Per-publish snapshot** (one timestamp per publish covers the whole tree) |
| What is hashed | **Content manifest digest** (not the git commit SHA — self-contained verification, no SHA-1 inheritance, no chicken/egg) |
| Trigger | **Automatic in `publish`, best-effort** — TSA unreachable never blocks publishing |
| Dependency | **`rfc3161ng`** (first runtime third-party dep in the compliance stack; layers 1–2 were stdlib-only) |
| Token storage | `timestamps/` directory in the data repo, committed + pushed |
| Default TSA | **DigiCert** (`http://timestamp.digicert.com`) — free, no auth, **RSA-signed** |
| TSA cert | **Bundled DigiCert Trusted Root G4** as trust anchor; the per-token signer cert is embedded in the token and verified against the root |

> **Implementation note (supersedes the original freeTSA choice):** freeTSA was
> the spec's first pick, but it migrated to an **EC** signing key that
> `rfc3161ng` 2.1.3 (the latest release) cannot verify
> (`ECPublicKey.verify()` arity mismatch). The implementation therefore defaults
> to **DigiCert's RSA** timestamping service, which `rfc3161ng` verifies, and
> verifies the signature against the **signer certificate embedded in the token**
> (robust to TSA cert rotation), confirming that signer chains to the bundled
> self-signed **DigiCert Trusted Root G4**. Any RFC 3161 TSA whose signer chains
> to a bundled root works via the `[timestamp]` config.

## What gets timestamped — the snapshot digest

At publish, after `experiments.sql` is dumped and the publishable paths are
staged, compute:

- `manifest_text` = sorted lines `"<relpath>\t<sha256>"` over every file under
  `PUBLISH_PATHS` (`experiments.sql`, `reports`, `presentations`, `thumbnails`).
- `snapshot_digest = sha256(manifest_text)`.

`snapshot_digest` is the RFC 3161 message imprint. Rationale for a manifest digest
over the raw git commit SHA:

- **Self-contained verification** — recompute the manifest from the files and check
  the token; no git plumbing required and no dependence on git's (historically
  SHA-1) object hash.
- **No chicken/egg** — committing the token changes the tree, so it cannot be the
  thing a commit-SHA timestamp covers; a content digest computed *before* commit
  lets the token ride the same commit as the content it attests.

Cost is bounded: the data repo is kept small by the existing 90 MB publish guard,
and raw data trees are referenced by SDGL, not committed.

Git still provides **historical content retrieval** (recover a past snapshot's
files via `git show <commit>:<path>`); the token provides **independent proof of
time** over that content's digest. Clean separation: git = durable content store,
RFC 3161 = independent time proof.

## Storage layout (data repo, committed + pushed)

New `timestamps/` directory, added to `PUBLISH_PATHS`:

- `timestamps/<UTC-datetime>-<short-digest>.tsr` — DER timestamp token (the proof).
- `timestamps/<id>.manifest` — the `manifest_text` for that snapshot, so verify can
  recompute `snapshot_digest` and know which files were covered.
- `timestamps/index.jsonl` — append-only index, one line per publish:
  `{id, created_at, snapshot_digest, tsa_url, status: "ok"|"pending", gen_time}`.

## Publish integration (best-effort)

In `eln/server/publish.py`, after dump + `git add` of the publishable paths but
**before commit**:

1. Compute `snapshot_digest` over the staged content.
2. Request a token from the configured TSA via `rfc3161ng`.
3. **Success** → write `.tsr` + `.manifest` + an `index.jsonl` entry
   (`status: "ok"`, with `gen_time` from the token); `git add timestamps/`; commit
   everything **together** (the token rides the same commit as the content it
   covers); push.
4. **TSA unreachable / error** → write a `status: "pending"` `index.jsonl` entry
   (digest + manifest, no token); commit anyway; push. **Publishing never blocks on
   the network.** The publish result message notes the pending timestamp.

## Retry + manual command

`labbook timestamp [--retry]`:

- `--retry` re-requests tokens for any `pending` index entries using their
  **stored** `snapshot_digest`. The proof still pertains to that snapshot; its
  `gen_time` is honestly the retry time (a later, still-valid upper bound on
  existence).
- Without `--retry`, anchors the current published state on demand.

## Verification

- `eln/timestamp.py: verify_token(token, digest, cert_bytes) -> {valid, gen_time, reason}`
  — verifies the signature against the signer cert **embedded in the token**,
  checks the token's `messageImprint` equals `snapshot_digest`, confirms the
  signer chains to a bundled trusted root in `cert_bytes`, and extracts
  `gen_time`.
- **`labbook verify`** gains a *timestamps* section beside the existing
  file-hash report (layer 1):
  - verify each `ok` token (signature + imprint + cert chain);
  - recompute the **latest** snapshot's digest from the current files and confirm
    it matches the latest `ok` token (the live state is anchored);
  - list any `pending` entries.
- **`GET /api/timestamp/verify`** endpoint, mirroring `/api/sdgl/verify-hashes` and
  `/api/sdgl/provenance/verify`.

Deeper historical verification (re-hash a past snapshot's files via git and check
against its stored manifest) is available conceptually but **not** run by default —
`labbook verify` checks token validity and the live snapshot only.

## Configuration

New `[timestamp]` section in `labbook.toml`:

```toml
[timestamp]
enabled = true                            # default true
tsa_url = "http://timestamp.digicert.com" # default free public RSA TSA
tsa_cert = ""                             # path to trusted root(s) PEM; empty -> bundled DigiCert Root G4
```

The bundled DigiCert Trusted Root G4 ships in the code repo so verification
works out-of-the-box; `tsa_cert` overrides the trust anchor for a different TSA.

## Dependency

Add `rfc3161ng` to `pyproject.toml` — the **first runtime third-party dependency**
in the compliance stack. RFC 3161 requires ASN.1 (`TimeStampReq`/`Resp`,
`TSTInfo`) and CMS signature verification, which the standard library cannot do;
`rfc3161ng` builds the request, POSTs to the TSA, parses the token, and verifies it
against the TSA cert. Pulls in `pyasn1`/`cryptography`/`requests` transitively.

## Files

- **New** `eln/timestamp.py`: `snapshot_digest(root, paths)`,
  `request_timestamp(digest, cfg)`, `verify_token(token, digest, tsa_cert)`,
  `retry_pending(root, cfg)`, and `index.jsonl` read/append helpers.
- **New** `tests/test_timestamp.py` (parent runs pytest per the canonical-env note):
  - `snapshot_digest` determinism (stable ordering, stable bytes);
  - `request_timestamp` with the **TSA HTTP mocked** (no live network in tests);
  - `verify_token` against a recorded good-token fixture;
  - tamper case — alter a file → digest mismatch → `verify_token` fails;
  - pending → `retry_pending` completes the entry.
- **Edits:**
  - `eln/server/publish.py` — the best-effort timestamp step above.
  - `eln/cli.py` — `timestamp` subcommand (`--retry`); extend `cmd_verify` with the
    timestamps section.
  - `eln/config.py` — load the `[timestamp]` section.
  - `eln/server/app.py` — `GET /api/timestamp/verify` route.
  - `pyproject.toml` — add `rfc3161ng`.
  - Bundled freeTSA cert chain (new asset in the code repo).

## Edge cases

- **Offline at publish** → `pending` entry, publish still succeeds; `--retry` later.
- **TSA returns an error / malformed token** → treated as unreachable: `pending`.
- **Empty publish (nothing staged)** → no timestamp (consistent with the existing
  "nothing to publish" short-circuit).
- **`verify` with no tokens yet** → reports zero timestamps, ok.
- **Cert mismatch / expired TSA cert** → `verify_token` returns `valid: false` with
  a `reason`; surfaced by `labbook verify` and the endpoint.

## Out of scope (YAGNI)

- Per-artifact timestamps (git's Merkle tree already extends one snapshot
  timestamp to every file).
- A timestamps viewer UI.
- Multiple-TSA redundancy.
- Automatic historical re-verification of every past snapshot in `labbook verify`.
