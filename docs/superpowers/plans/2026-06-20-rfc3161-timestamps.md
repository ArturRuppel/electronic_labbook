# RFC 3161 Trusted Timestamps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **The parent session runs pytest in the canonical miniconda env (not the repo `.venv`); subagents cannot run Python — the parent executes all test/commit steps.**

**Goal:** Anchor each `publish` to an RFC 3161 trusted timestamp over a content-manifest digest of the published snapshot, committed to the data repo, with best-effort acquisition, retry, and verification.

**Architecture:** A self-contained `eln/timestamp.py` computes a `sha256` digest over a sorted file manifest of the publishable paths, requests a signed token from a TSA via `rfc3161ng`, and records token + manifest + an append index under `timestamps/`. `publish()` calls it best-effort (network failure → `pending`, never blocks). `labbook timestamp [--retry]`, an extended `labbook verify`, and `GET /api/timestamp/verify` expose acquisition and verification.

**Tech Stack:** Python 3.9+, `rfc3161ng` (new dependency; pulls `pyasn1`/`cryptography`/`requests`), `hashlib` (stdlib), Flask, pytest.

**Spec:** `docs/superpowers/specs/2026-06-20-rfc3161-timestamps-design.md`

---

## File Structure

- **Create** `eln/timestamp.py` — all timestamp logic: manifest/digest, TSA request, token verify, index I/O, orchestration (`create_timestamp`, `retry_pending`, `verify_all`).
- **Create** `eln/certs/freetsa_cacert.pem` — bundled freeTSA CA cert chain for out-of-the-box verification.
- **Create** `tests/test_timestamp.py` — unit + integration tests (TSA seam mocked; no live network).
- **Modify** `eln/config.py` — load `[timestamp]` + `resolve_timestamp_config()`.
- **Modify** `eln/server/publish.py` — best-effort timestamp between dump and commit; add `timestamps` to `PUBLISH_PATHS`.
- **Modify** `eln/cli.py` — `timestamp` subcommand; extend `cmd_verify`.
- **Modify** `eln/server/app.py` — `GET /api/timestamp/verify`; thread `timestamp` config into `create_app`.
- **Modify** `pyproject.toml` — add `rfc3161ng`; include `eln/certs/*.pem` as package data.
- **Modify** `docs/ROADMAP.md` — mark step 11 layer 3 done; record layer-2 drop.

## Module API (defined once; later tasks must match these signatures)

```python
# eln/timestamp.py
DEFAULT_TSA_URL  = "https://freetsa.org/tsr"
DEFAULT_TSA_CERT = Path(__file__).parent / "certs" / "freetsa_cacert.pem"
TIMESTAMPS_DIR   = "timestamps"

build_manifest(root, paths) -> str                       # sorted "<relpath>\t<sha256hex>\n" lines
snapshot_digest(root, paths) -> tuple[str, str]          # (digest_hex, manifest_text)
make_timestamp_id(digest_hex, when=None) -> str          # "<UTCstamp>-<digest[:12]>"
request_timestamp(digest_hex, *, tsa_url, cert_bytes, timeout=10) -> bytes   # DER token; raises on failure
verify_token(token, digest_hex, cert_bytes) -> dict      # {"valid","gen_time","reason"}
read_index(root) -> list[dict]
append_index(root, entry) -> None
update_index(root, ts_id, **changes) -> None
create_timestamp(root, paths, cfg) -> dict               # entry dict; status "ok"|"pending"
retry_pending(root, cfg) -> list[dict]                   # updated entries
verify_all(root, cfg) -> dict                            # {"timestamps","ok","invalid","pending","live_anchored"}
```

`cfg` is the normalized dict from `resolve_timestamp_config`: `{"enabled","tsa_url","cert_bytes","paths"}`.

---

## Task 0: Add the dependency and bundled cert

**Files:**
- Modify: `pyproject.toml`
- Create: `eln/certs/freetsa_cacert.pem`

- [ ] **Step 1: Fetch the freeTSA CA cert chain**

Run:
```bash
mkdir -p eln/certs
curl -fsSL https://freetsa.org/files/cacert.pem -o eln/certs/freetsa_cacert.pem
head -1 eln/certs/freetsa_cacert.pem
```
Expected: prints `-----BEGIN CERTIFICATE-----`. (If freeTSA is unreachable, fetch `https://freetsa.org/files/tsa.crt` instead and concatenate; the file must contain the TSA signing cert + its CA.)

- [ ] **Step 2: Add the runtime dependency and package the cert**

In `pyproject.toml`, add to `dependencies` (after the `tomli` line):
```toml
    "rfc3161ng>=2.1.3",
```
And add package-data inclusion under `[tool.setuptools]` (create the table if absent, after `[tool.setuptools.packages.find]`):
```toml
[tool.setuptools.package-data]
eln = ["certs/*.pem"]
```

- [ ] **Step 3: Install into the canonical env**

Run: `python -m pip install 'rfc3161ng>=2.1.3'`
Expected: installs `rfc3161ng` (+ `pyasn1`, `cryptography`). Verify: `python -c "import rfc3161ng; print('ok')"` → `ok`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml eln/certs/freetsa_cacert.pem
git commit -m "build(timestamp): add rfc3161ng dep + bundled freeTSA cert"
```

---

## Task 1: Manifest + snapshot digest (pure, deterministic)

**Files:**
- Create: `eln/timestamp.py`
- Test: `tests/test_timestamp.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_timestamp.py
import hashlib
from eln import timestamp


def _write(root, rel, data):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def test_build_manifest_is_sorted_and_hashed(tmp_path):
    _write(tmp_path, "experiments.sql", b"CREATE TABLE x;")
    _write(tmp_path, "reports/b.md", b"bbb")
    _write(tmp_path, "reports/a.md", b"aaa")

    manifest = timestamp.build_manifest(tmp_path, ["experiments.sql", "reports"])

    sql_h = hashlib.sha256(b"CREATE TABLE x;").hexdigest()
    a_h = hashlib.sha256(b"aaa").hexdigest()
    b_h = hashlib.sha256(b"bbb").hexdigest()
    assert manifest == (
        f"experiments.sql\t{sql_h}\n"
        f"reports/a.md\t{a_h}\n"
        f"reports/b.md\t{b_h}\n"
    )


def test_snapshot_digest_matches_manifest_hash(tmp_path):
    _write(tmp_path, "experiments.sql", b"data")
    digest_hex, manifest = timestamp.snapshot_digest(tmp_path, ["experiments.sql"])
    assert digest_hex == hashlib.sha256(manifest.encode("utf-8")).hexdigest()


def test_snapshot_digest_ignores_missing_paths(tmp_path):
    _write(tmp_path, "experiments.sql", b"data")
    # "reports" absent -> skipped, not an error.
    digest_hex, manifest = timestamp.snapshot_digest(
        tmp_path, ["experiments.sql", "reports"])
    assert "reports" not in manifest
    assert digest_hex  # non-empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_timestamp.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'eln.timestamp'` (or attribute errors).

- [ ] **Step 3: Write minimal implementation**

```python
# eln/timestamp.py
"""RFC 3161 trusted timestamps (Roadmap step 11, compliance layer 3).

Anchors a publish to a signed proof-of-existence-at-a-time over a content
manifest digest of the published snapshot. Self-contained: verification needs
only the token, the recomputed digest, and the TSA cert -- not git or GitHub.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from eln.hashing import sha256_hex

DEFAULT_TSA_URL = "https://freetsa.org/tsr"
DEFAULT_TSA_CERT = Path(__file__).parent / "certs" / "freetsa_cacert.pem"
TIMESTAMPS_DIR = "timestamps"


def _iter_files(root, paths):
    """Yield (relpath_posix, abspath) for every file under each path, sorted."""
    root = Path(root)
    collected = []
    for rel_base in paths:
        base = root / rel_base
        if base.is_file():
            collected.append((base.relative_to(root).as_posix(), base))
        elif base.is_dir():
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames.sort()
                for name in sorted(filenames):
                    ab = Path(dirpath) / name
                    collected.append((ab.relative_to(root).as_posix(), ab))
    collected.sort(key=lambda t: t[0])
    return collected


def build_manifest(root, paths):
    """Return the canonical manifest: sorted ``<relpath>\\t<sha256hex>`` lines."""
    return "".join(f"{rel}\t{sha256_hex(ab)}\n" for rel, ab in _iter_files(root, paths))


def snapshot_digest(root, paths):
    """Return ``(digest_hex, manifest_text)`` where digest = sha256(manifest)."""
    manifest = build_manifest(root, paths)
    digest_hex = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
    return digest_hex, manifest
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_timestamp.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add eln/timestamp.py tests/test_timestamp.py
git commit -m "feat(timestamp): snapshot manifest digest"
```

---

## Task 2: Timestamp id + index I/O

**Files:**
- Modify: `eln/timestamp.py`
- Test: `tests/test_timestamp.py`

- [ ] **Step 1: Write the failing test**

```python
def test_make_timestamp_id_format():
    from datetime import datetime, timezone
    when = datetime(2026, 6, 20, 14, 32, 1, tzinfo=timezone.utc)
    ts_id = timestamp.make_timestamp_id("9f86d081abc123", when=when)
    assert ts_id == "20260620T143201Z-9f86d081abc1"


def test_index_append_read_update(tmp_path):
    timestamp.append_index(tmp_path, {"id": "A", "status": "pending"})
    timestamp.append_index(tmp_path, {"id": "B", "status": "ok"})
    assert [e["id"] for e in timestamp.read_index(tmp_path)] == ["A", "B"]

    timestamp.update_index(tmp_path, "A", status="ok", gen_time="t")
    rows = {e["id"]: e for e in timestamp.read_index(tmp_path)}
    assert rows["A"]["status"] == "ok"
    assert rows["A"]["gen_time"] == "t"
    assert rows["B"]["status"] == "ok"  # untouched


def test_read_index_missing_is_empty(tmp_path):
    assert timestamp.read_index(tmp_path) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_timestamp.py -q`
Expected: FAIL — `AttributeError: module 'eln.timestamp' has no attribute 'make_timestamp_id'`.

- [ ] **Step 3: Write minimal implementation**

Append to `eln/timestamp.py`:
```python
def make_timestamp_id(digest_hex, when=None):
    when = when or datetime.now(timezone.utc)
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{digest_hex[:12]}"


def _index_path(root):
    return Path(root) / TIMESTAMPS_DIR / "index.jsonl"


def read_index(root):
    path = _index_path(root)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_index(root, entry):
    path = _index_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def update_index(root, ts_id, **changes):
    rows = read_index(root)
    for entry in rows:
        if entry.get("id") == ts_id:
            entry.update(changes)
    path = _index_path(root)
    path.write_text(
        "".join(json.dumps(e, sort_keys=True) + "\n" for e in rows), encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_timestamp.py -q`
Expected: PASS (6 tests total).

- [ ] **Step 5: Commit**

```bash
git add eln/timestamp.py tests/test_timestamp.py
git commit -m "feat(timestamp): timestamp id + append index I/O"
```

---

## Task 3: TSA request + token verify wrappers

**Files:**
- Modify: `eln/timestamp.py`
- Test: `tests/test_timestamp.py`

These wrap `rfc3161ng` thinly. Tests monkeypatch `rfc3161ng` so no network/crypto is exercised — they assert our argument translation and error handling.

- [ ] **Step 1: Write the failing test**

```python
def test_request_timestamp_passes_digest_and_returns_token(monkeypatch):
    calls = {}

    class FakeStamper:
        def __init__(self, url, certificate=None, hashname=None):
            calls["url"] = url
            calls["hashname"] = hashname
        def __call__(self, digest=None, return_tsr=False):
            calls["digest"] = digest
            return b"TOKEN-BYTES"

    monkeypatch.setattr(timestamp.rfc3161ng, "RemoteTimestamper", FakeStamper)
    token = timestamp.request_timestamp(
        "9f86d0", tsa_url="https://tsa.example/tsr", cert_bytes=b"CERT")
    assert token == b"TOKEN-BYTES"
    assert calls["url"] == "https://tsa.example/tsr"
    assert calls["hashname"] == "sha256"
    assert calls["digest"] == bytes.fromhex("9f86d0")


def test_verify_token_valid(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(timestamp.rfc3161ng, "check_timestamp", lambda *a, **k: True)
    monkeypatch.setattr(
        timestamp.rfc3161ng, "get_timestamp",
        lambda token: datetime(2026, 6, 20, tzinfo=timezone.utc))
    out = timestamp.verify_token(b"TOK", "9f86d0", b"CERT")
    assert out["valid"] is True
    assert out["gen_time"].startswith("2026-06-20")
    assert out["reason"] is None


def test_verify_token_invalid_on_exception(monkeypatch):
    def boom(*a, **k):
        raise ValueError("bad signature")
    monkeypatch.setattr(timestamp.rfc3161ng, "check_timestamp", boom)
    out = timestamp.verify_token(b"TOK", "9f86d0", b"CERT")
    assert out["valid"] is False
    assert "bad signature" in out["reason"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_timestamp.py -q`
Expected: FAIL — `module 'eln.timestamp' has no attribute 'rfc3161ng'` / `request_timestamp`.

- [ ] **Step 3: Write minimal implementation**

At the top of `eln/timestamp.py` add the import (after the `from eln.hashing` line):
```python
import rfc3161ng
```
Append the wrappers:
```python
def request_timestamp(digest_hex, *, tsa_url, cert_bytes, timeout=10):
    """Request a DER timestamp token for ``digest_hex`` from the TSA.

    Raises on any network/TSA failure (caller decides best-effort handling).
    """
    stamper = rfc3161ng.RemoteTimestamper(
        tsa_url, certificate=cert_bytes, hashname="sha256")
    return stamper(digest=bytes.fromhex(digest_hex), return_tsr=False)


def verify_token(token, digest_hex, cert_bytes):
    """Verify a token's signature and that it covers ``digest_hex``.

    Returns ``{"valid", "gen_time" (ISO str|None), "reason" (str|None)}``.
    """
    try:
        ok = rfc3161ng.check_timestamp(
            token, certificate=cert_bytes,
            digest=bytes.fromhex(digest_hex), hashname="sha256")
        gen = rfc3161ng.get_timestamp(token)
        gen_time = gen.isoformat() if gen is not None else None
        return {"valid": bool(ok), "gen_time": gen_time, "reason": None}
    except Exception as exc:  # noqa: BLE001 - any failure means "not verifiable"
        return {"valid": False, "gen_time": None, "reason": str(exc)}
```

Note: in `test_verify_token_valid` the assertion uses `.startswith` against the ISO string — `gen_time` is a string here. Adjust the test's `out["gen_time"].startswith` is correct since we return `.isoformat()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_timestamp.py -q`
Expected: PASS (9 tests total).

- [ ] **Step 5: Commit**

```bash
git add eln/timestamp.py tests/test_timestamp.py
git commit -m "feat(timestamp): TSA request + token verify wrappers"
```

---

## Task 4: Orchestration — create_timestamp + retry_pending

**Files:**
- Modify: `eln/timestamp.py`
- Test: `tests/test_timestamp.py`

Tests monkeypatch our own `request_timestamp` seam (not `rfc3161ng`) to drive success/failure deterministically.

- [ ] **Step 1: Write the failing test**

```python
def _cfg(tmp_path, **over):
    base = {"enabled": True, "tsa_url": "https://tsa.example/tsr",
            "cert_bytes": b"CERT", "paths": ["experiments.sql"]}
    base.update(over)
    return base


def test_create_timestamp_success_writes_token_and_index(tmp_path, monkeypatch):
    _write(tmp_path, "experiments.sql", b"data")
    monkeypatch.setattr(timestamp, "request_timestamp", lambda d, **k: b"TOKEN")
    monkeypatch.setattr(timestamp, "verify_token",
                        lambda *a, **k: {"valid": True, "gen_time": "2026-06-20T00:00:00+00:00", "reason": None})

    entry = timestamp.create_timestamp(tmp_path, ["experiments.sql"], _cfg(tmp_path))

    assert entry["status"] == "ok"
    tdir = tmp_path / "timestamps"
    assert (tdir / f"{entry['id']}.tsr").read_bytes() == b"TOKEN"
    assert (tdir / f"{entry['id']}.manifest").exists()
    assert timestamp.read_index(tmp_path)[0]["id"] == entry["id"]
    assert entry["gen_time"] == "2026-06-20T00:00:00+00:00"


def test_create_timestamp_pending_on_tsa_failure(tmp_path, monkeypatch):
    _write(tmp_path, "experiments.sql", b"data")
    def boom(d, **k):
        raise OSError("network down")
    monkeypatch.setattr(timestamp, "request_timestamp", boom)

    entry = timestamp.create_timestamp(tmp_path, ["experiments.sql"], _cfg(tmp_path))

    assert entry["status"] == "pending"
    tdir = tmp_path / "timestamps"
    assert not (tdir / f"{entry['id']}.tsr").exists()
    assert (tdir / f"{entry['id']}.manifest").exists()  # manifest persisted for retry
    assert timestamp.read_index(tmp_path)[0]["status"] == "pending"


def test_retry_pending_completes_entry(tmp_path, monkeypatch):
    _write(tmp_path, "experiments.sql", b"data")
    monkeypatch.setattr(timestamp, "request_timestamp", lambda d, **k: (_ for _ in ()).throw(OSError()))
    pending = timestamp.create_timestamp(tmp_path, ["experiments.sql"], _cfg(tmp_path))

    # TSA recovers; retry uses the STORED digest.
    seen = {}
    monkeypatch.setattr(timestamp, "request_timestamp",
                        lambda d, **k: seen.setdefault("digest", d) or b"TOKEN")
    monkeypatch.setattr(timestamp, "verify_token",
                        lambda *a, **k: {"valid": True, "gen_time": "T", "reason": None})

    updated = timestamp.retry_pending(tmp_path, _cfg(tmp_path))

    assert len(updated) == 1 and updated[0]["status"] == "ok"
    assert seen["digest"] == pending["snapshot_digest"]
    assert (tmp_path / "timestamps" / f"{pending['id']}.tsr").read_bytes() == b"TOKEN"
    assert timestamp.read_index(tmp_path)[0]["status"] == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_timestamp.py -q`
Expected: FAIL — `module 'eln.timestamp' has no attribute 'create_timestamp'`.

- [ ] **Step 3: Write minimal implementation**

Append to `eln/timestamp.py`:
```python
def _timestamps_dir(root):
    d = Path(root) / TIMESTAMPS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_timestamp(root, paths, cfg):
    """Compute the snapshot digest, request a token, and record the result.

    Returns the index entry. On TSA failure the entry is ``status="pending"``
    (manifest persisted so a later retry can re-request over the same digest).
    """
    digest_hex, manifest = snapshot_digest(root, paths)
    ts_id = make_timestamp_id(digest_hex)
    tdir = _timestamps_dir(root)
    (tdir / f"{ts_id}.manifest").write_text(manifest, encoding="utf-8")

    entry = {
        "id": ts_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_digest": digest_hex,
        "tsa_url": cfg["tsa_url"],
        "status": "pending",
        "gen_time": None,
    }
    try:
        token = request_timestamp(
            digest_hex, tsa_url=cfg["tsa_url"], cert_bytes=cfg["cert_bytes"])
        (tdir / f"{ts_id}.tsr").write_bytes(token)
        result = verify_token(token, digest_hex, cfg["cert_bytes"])
        entry["status"] = "ok"
        entry["gen_time"] = result.get("gen_time")
    except Exception:  # noqa: BLE001 - best-effort: stay pending on any failure
        pass
    append_index(root, entry)
    return entry


def retry_pending(root, cfg):
    """Re-request tokens for pending entries using their stored digest."""
    updated = []
    for entry in read_index(root):
        if entry.get("status") != "pending":
            continue
        digest_hex = entry["snapshot_digest"]
        try:
            token = request_timestamp(
                digest_hex, tsa_url=cfg["tsa_url"], cert_bytes=cfg["cert_bytes"])
        except Exception:  # noqa: BLE001 - still unreachable: leave pending
            continue
        (_timestamps_dir(root) / f"{entry['id']}.tsr").write_bytes(token)
        result = verify_token(token, digest_hex, cfg["cert_bytes"])
        update_index(root, entry["id"], status="ok", gen_time=result.get("gen_time"))
        entry = {**entry, "status": "ok", "gen_time": result.get("gen_time")}
        updated.append(entry)
    return updated
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_timestamp.py -q`
Expected: PASS (12 tests total).

- [ ] **Step 5: Commit**

```bash
git add eln/timestamp.py tests/test_timestamp.py
git commit -m "feat(timestamp): create_timestamp + retry_pending orchestration"
```

---

## Task 5: verify_all summary

**Files:**
- Modify: `eln/timestamp.py`
- Test: `tests/test_timestamp.py`

- [ ] **Step 1: Write the failing test**

```python
def test_verify_all_reports_ok_invalid_pending_and_live_anchor(tmp_path, monkeypatch):
    _write(tmp_path, "experiments.sql", b"data")
    # One ok token whose digest equals the CURRENT snapshot -> live_anchored True.
    monkeypatch.setattr(timestamp, "request_timestamp", lambda d, **k: b"TOKEN")
    monkeypatch.setattr(timestamp, "verify_token",
                        lambda *a, **k: {"valid": True, "gen_time": "T", "reason": None})
    timestamp.create_timestamp(tmp_path, ["experiments.sql"], _cfg(tmp_path))

    summary = timestamp.verify_all(tmp_path, _cfg(tmp_path))
    assert summary["timestamps"] == 1
    assert summary["ok"] == 1
    assert summary["invalid"] == []
    assert summary["pending"] == []
    assert summary["live_anchored"] is True


def test_verify_all_flags_invalid_token(tmp_path, monkeypatch):
    _write(tmp_path, "experiments.sql", b"data")
    monkeypatch.setattr(timestamp, "request_timestamp", lambda d, **k: b"TOKEN")
    monkeypatch.setattr(timestamp, "verify_token",
                        lambda *a, **k: {"valid": True, "gen_time": "T", "reason": None})
    timestamp.create_timestamp(tmp_path, ["experiments.sql"], _cfg(tmp_path))

    # Now verification reports invalid (e.g. tampered token).
    monkeypatch.setattr(timestamp, "verify_token",
                        lambda *a, **k: {"valid": False, "gen_time": None, "reason": "bad"})
    summary = timestamp.verify_all(tmp_path, _cfg(tmp_path))
    assert summary["ok"] == 0
    assert len(summary["invalid"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_timestamp.py -q`
Expected: FAIL — no attribute `verify_all`.

- [ ] **Step 3: Write minimal implementation**

Append to `eln/timestamp.py`:
```python
def verify_all(root, cfg):
    """Verify every recorded ``ok`` token and check the live snapshot is anchored.

    Returns ``{"timestamps","ok","invalid":[...],"pending":[...],"live_anchored"}``.
    ``invalid`` entries carry their id + reason; ``live_anchored`` is True when the
    current snapshot digest matches the most recent ``ok`` token.
    """
    rows = read_index(root)
    summary = {"timestamps": len(rows), "ok": 0, "invalid": [], "pending": [],
               "live_anchored": False}
    latest_ok_digest = None
    for entry in rows:
        if entry.get("status") == "pending":
            summary["pending"].append(entry["id"])
            continue
        token_path = Path(root) / TIMESTAMPS_DIR / f"{entry['id']}.tsr"
        if not token_path.exists():
            summary["invalid"].append({"id": entry["id"], "reason": "token file missing"})
            continue
        result = verify_token(token_path.read_bytes(), entry["snapshot_digest"], cfg["cert_bytes"])
        if result["valid"]:
            summary["ok"] += 1
            latest_ok_digest = entry["snapshot_digest"]
        else:
            summary["invalid"].append({"id": entry["id"], "reason": result["reason"]})

    if latest_ok_digest is not None:
        current_digest, _ = snapshot_digest(root, cfg["paths"])
        summary["live_anchored"] = (current_digest == latest_ok_digest)
    return summary
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_timestamp.py -q`
Expected: PASS (14 tests total).

- [ ] **Step 5: Commit**

```bash
git add eln/timestamp.py tests/test_timestamp.py
git commit -m "feat(timestamp): verify_all summary"
```

---

## Task 6: Config `[timestamp]` section

**Files:**
- Modify: `eln/config.py`
- Modify: `eln/timestamp.py` (add `resolve_timestamp_config`)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:
```python
def test_timestamp_config_defaults_and_override(tmp_path, monkeypatch):
    from eln.config import load_config
    cfg_path = tmp_path / "labbook.toml"
    cfg_path.write_text(
        'data_root = "%s"\n[timestamp]\nenabled = false\ntsa_url = "https://t.example/tsr"\n'
        % tmp_path.as_posix())
    monkeypatch.delenv("ELN_ROOT", raising=False)
    config = load_config(cfg_path)
    assert config.timestamp["enabled"] is False
    assert config.timestamp["tsa_url"] == "https://t.example/tsr"


def test_timestamp_config_absent_is_empty(tmp_path, monkeypatch):
    from eln.config import load_config
    cfg_path = tmp_path / "labbook.toml"
    cfg_path.write_text('data_root = "%s"\n' % tmp_path.as_posix())
    monkeypatch.delenv("ELN_ROOT", raising=False)
    assert load_config(cfg_path).timestamp == {}


def test_resolve_timestamp_config_fills_defaults():
    from eln.timestamp import resolve_timestamp_config, DEFAULT_TSA_URL
    cfg = resolve_timestamp_config({})
    assert cfg["enabled"] is True
    assert cfg["tsa_url"] == DEFAULT_TSA_URL
    assert isinstance(cfg["cert_bytes"], bytes) and cfg["cert_bytes"]
    assert "experiments.sql" in cfg["paths"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -q`
Expected: FAIL — `Config` has no field `timestamp` / no `resolve_timestamp_config`.

- [ ] **Step 3: Write minimal implementation**

In `eln/config.py`, add a field to the `Config` dataclass (after `channel_aliases`):
```python
    timestamp: dict = field(default_factory=dict)
```
And in `load_config`, pass it through in the returned `Config(...)`:
```python
        channel_aliases=channel_aliases,
        timestamp=data.get("timestamp", {}),
    )
```

In `eln/timestamp.py`, append:
```python
# Paths whose contents a snapshot covers (mirrors publish.PUBLISH_PATHS minus
# the timestamps dir itself, which holds prior tokens).
SNAPSHOT_PATHS = ["experiments.sql", "reports", "presentations", "thumbnails",
                  TIMESTAMPS_DIR]


def resolve_timestamp_config(raw):
    """Normalize the ``[timestamp]`` table into the cfg dict the API expects."""
    raw = raw or {}
    cert_path = raw.get("tsa_cert") or DEFAULT_TSA_CERT
    cert_bytes = Path(cert_path).read_bytes()
    return {
        "enabled": raw.get("enabled", True),
        "tsa_url": raw.get("tsa_url", DEFAULT_TSA_URL),
        "cert_bytes": cert_bytes,
        "paths": list(raw.get("paths", SNAPSHOT_PATHS)),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py tests/test_timestamp.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add eln/config.py eln/timestamp.py tests/test_config.py
git commit -m "feat(timestamp): [timestamp] config + resolve defaults"
```

---

## Task 7: Publish integration (best-effort)

**Files:**
- Modify: `eln/server/publish.py`
- Test: `tests/server/test_publish.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/server/test_publish.py`:
```python
def test_publish_creates_timestamp_when_cfg_enabled(data_repo, monkeypatch):
    from eln import timestamp
    monkeypatch.setattr(timestamp, "request_timestamp", lambda d, **k: b"TOKEN")
    monkeypatch.setattr(timestamp, "verify_token",
                        lambda *a, **k: {"valid": True, "gen_time": "T", "reason": None})
    cfg = {"enabled": True, "tsa_url": "https://t.example/tsr",
           "cert_bytes": b"CERT",
           "paths": ["experiments.sql", "reports", "timestamps"]}

    result = publish(data_repo, push=False, timestamp_cfg=cfg)
    assert result["success"] is True

    idx = timestamp.read_index(data_repo)
    assert len(idx) == 1 and idx[0]["status"] == "ok"
    tracked = subprocess.run(["git", "ls-files"], cwd=str(data_repo),
                             capture_output=True, text=True).stdout
    assert "timestamps/index.jsonl" in tracked  # token artifacts committed


def test_publish_timestamp_pending_does_not_block(data_repo, monkeypatch):
    from eln import timestamp
    def boom(d, **k):
        raise OSError("offline")
    monkeypatch.setattr(timestamp, "request_timestamp", boom)
    cfg = {"enabled": True, "tsa_url": "https://t.example/tsr",
           "cert_bytes": b"CERT", "paths": ["experiments.sql", "timestamps"]}

    result = publish(data_repo, push=False, timestamp_cfg=cfg)
    assert result["success"] is True  # publish still succeeds
    assert timestamp.read_index(data_repo)[0]["status"] == "pending"


def test_publish_without_timestamp_cfg_is_unchanged(data_repo):
    result = publish(data_repo, push=False)  # no timestamp_cfg -> no timestamping
    assert result["success"] is True
    assert (data_repo / "timestamps").exists() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/server/test_publish.py -q`
Expected: FAIL — `publish() got an unexpected keyword argument 'timestamp_cfg'`.

- [ ] **Step 3: Write minimal implementation**

In `eln/server/publish.py`:

Add `timestamps` to `PUBLISH_PATHS`:
```python
PUBLISH_PATHS = ["experiments.sql", "reports", "presentations", "thumbnails", "timestamps"]
```

Extend the signature:
```python
def publish(root, eln_db_path=None, *, push=True, remote="origin", branch="main",
            timestamp_cfg=None):
```

Insert the timestamp step between the dump (step 2) and the stage (step 3), i.e. right after `dump(db_path, root / "experiments.sql")`:
```python
    # 2b. Best-effort trusted timestamp over the snapshot (Roadmap step 11, layer 3).
    #     A TSA failure records a "pending" entry but never blocks the publish.
    if timestamp_cfg and timestamp_cfg.get("enabled", True):
        from eln import timestamp as _ts
        _ts.create_timestamp(root, timestamp_cfg["paths"], timestamp_cfg)
```

(The token/manifest/index land under `timestamps/`, which is in `PUBLISH_PATHS`, so the existing `git add` stages and commits them with the rest.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/server/test_publish.py -q`
Expected: PASS (existing 4 + new 3).

- [ ] **Step 5: Commit**

```bash
git add eln/server/publish.py tests/server/test_publish.py
git commit -m "feat(timestamp): best-effort timestamp in publish flow"
```

---

## Task 8: CLI — `timestamp` subcommand + `verify` extension

**Files:**
- Modify: `eln/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py` (follow the existing `_load`/config monkeypatch pattern in that file; the snippet below stubs config + the timestamp module):
```python
def test_cli_timestamp_retry(monkeypatch, tmp_path, capsys):
    from eln import cli, timestamp
    from eln.config import Config
    cfg = Config(data_root=tmp_path, timestamp={})
    monkeypatch.setattr(cli, "_load", lambda args: cfg)
    monkeypatch.setattr(timestamp, "resolve_timestamp_config",
                        lambda raw: {"enabled": True, "tsa_url": "u", "cert_bytes": b"C",
                                     "paths": ["experiments.sql"]})
    monkeypatch.setattr(timestamp, "retry_pending",
                        lambda root, c: [{"id": "X", "status": "ok"}])

    rc = cli.main(["timestamp", "--retry"])
    assert rc == 0
    assert "X" in capsys.readouterr().out


def test_cli_verify_includes_timestamps(monkeypatch, tmp_path, capsys):
    from eln import cli, timestamp
    from eln.config import Config
    from eln.sdgl import SDGL
    cfg = Config(data_root=tmp_path, timestamp={})
    monkeypatch.setattr(cli, "_load", lambda args: cfg)
    monkeypatch.setattr(SDGL, "verify_hashes",
                        lambda self, node_id=None: {"checked": 0, "ok": 0, "mismatch": [], "missing": []})
    monkeypatch.setattr(timestamp, "resolve_timestamp_config",
                        lambda raw: {"enabled": True, "tsa_url": "u", "cert_bytes": b"C", "paths": []})
    monkeypatch.setattr(timestamp, "verify_all",
                        lambda root, c: {"timestamps": 2, "ok": 2, "invalid": [], "pending": [], "live_anchored": True})

    rc = cli.main(["verify"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "2 ok" in out and "anchored" in out.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -q`
Expected: FAIL — unknown command `timestamp` / no timestamp output in verify.

- [ ] **Step 3: Write minimal implementation**

In `eln/cli.py`, add the handler:
```python
def cmd_timestamp(args):
    from eln import timestamp

    config = _load(args)
    cfg = timestamp.resolve_timestamp_config(config.timestamp)
    if args.retry:
        updated = timestamp.retry_pending(config.data_root, cfg)
        print(f"  completed {len(updated)} pending timestamp(s)")
        for entry in updated:
            print(f"  OK  {entry['id']}")
    else:
        entry = timestamp.create_timestamp(config.data_root, cfg["paths"], cfg)
        print(f"  {entry['status'].upper()}  {entry['id']}")
    return 0
```

Extend `cmd_verify` (append before its `return`):
```python
    from eln import timestamp
    cfg = timestamp.resolve_timestamp_config(config.timestamp)
    ts = timestamp.verify_all(config.data_root, cfg)
    print(f"  {ts['timestamps']} timestamp(s): {ts['ok']} ok, "
          f"{len(ts['invalid'])} invalid, {len(ts['pending'])} pending; "
          f"live snapshot {'anchored' if ts['live_anchored'] else 'NOT anchored'}")
    for item in ts["invalid"]:
        print(f"  INVALID  {item['id']}: {item['reason']}")
    drift = bool(result["mismatch"] or result["missing"] or ts["invalid"])
    return 1 if drift else 0
```
(Replace the existing `return 1 if (result["mismatch"] or result["missing"]) else 0` with the `drift` computation above.)

Register the subcommand in `build_parser` (after the `verify` parser):
```python
    p = sub.add_parser("timestamp", help="obtain an RFC 3161 trusted timestamp (or --retry pending)")
    p.add_argument("--retry", action="store_true", help="re-request tokens for pending timestamps")
    p.set_defaults(func=cmd_timestamp)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add eln/cli.py tests/test_cli.py
git commit -m "feat(timestamp): labbook timestamp subcommand + verify extension"
```

---

## Task 9: Server endpoint `GET /api/timestamp/verify`

**Files:**
- Modify: `eln/server/app.py`
- Test: `tests/server/test_app.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/server/test_app.py` (reuse the existing app/client fixture in that file; this test monkeypatches `verify_all`):
```python
def test_timestamp_verify_endpoint(client, monkeypatch):
    from eln import timestamp
    monkeypatch.setattr(timestamp, "verify_all",
                        lambda root, cfg: {"timestamps": 1, "ok": 1, "invalid": [],
                                           "pending": [], "live_anchored": True})
    resp = client.get("/api/timestamp/verify")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] == 1
```

If the existing fixture builds the app without timestamp config, the endpoint must resolve defaults itself (it does — see implementation).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/server/test_app.py -q`
Expected: FAIL — 404 for the route.

- [ ] **Step 3: Write minimal implementation**

In `eln/server/app.py`, thread the config in. Add `timestamp=None` to the `create_app` signature:
```python
def create_app(root, *, eln_db_path=None, sdgl_db_path=None, assets_dir=None,
               scan_roots=None, channel_aliases=None, scanner=None, timestamp=None):
```
Store the raw table near the other `app.config` assignments (after `HASH_MAX_BYTES`):
```python
    app.config["TIMESTAMP"] = timestamp or {}
```
Add the route beside `sdgl_verify_hashes`:
```python
    @app.route("/api/timestamp/verify", methods=["GET"])
    def timestamp_verify():
        from eln import timestamp as ts_mod
        cfg = ts_mod.resolve_timestamp_config(app.config.get("TIMESTAMP"))
        return jsonify(ts_mod.verify_all(root, cfg))
```
Pass it from the CLI servers — in `eln/cli.py` `cmd_admin` and `cmd_backup`, add to both `create_app(...)` calls:
```python
        timestamp=config.timestamp,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/server/test_app.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add eln/server/app.py eln/cli.py tests/server/test_app.py
git commit -m "feat(timestamp): GET /api/timestamp/verify endpoint"
```

---

## Task 10: Full-suite green + docs + roadmap

**Files:**
- Modify: `docs/ROADMAP.md`
- Optional create: `tests/fixtures/freetsa_sample.tsr` (recorded real token) + a skippable end-to-end verify test.

- [ ] **Step 1: Run the entire suite**

Run: `python -m pytest -q`
Expected: PASS (all prior tests + the new timestamp tests). Fix any regressions before continuing.

- [ ] **Step 2: (Optional) Record a real token for a genuine crypto check**

Run (needs network):
```bash
python - <<'PY'
from eln import timestamp as ts
from eln.timestamp import resolve_timestamp_config
cfg = resolve_timestamp_config({})
tok = ts.request_timestamp("a"*64, tsa_url=cfg["tsa_url"], cert_bytes=cfg["cert_bytes"])
open("tests/fixtures/freetsa_sample.tsr","wb").write(tok)
print("verify:", ts.verify_token(tok, "a"*64, cfg["cert_bytes"]))
PY
```
Add a test that loads the fixture and asserts `verify_token(...)["valid"] is True`, decorated `@pytest.mark.skipif(not Path("tests/fixtures/freetsa_sample.tsr").exists(), reason="no recorded token")`. This gives one real end-to-end verification without making the suite network-dependent.

- [ ] **Step 3: Update the roadmap**

In `docs/ROADMAP.md`, under step 11 / the "Next step" section: mark **layer 3 (RFC 3161 trusted timestamps) done**, and note layer 2 (hash-chained audit log) was **dropped as redundant with git** (see the design spec). Reference `docs/superpowers/specs/2026-06-20-rfc3161-timestamps-design.md`.

- [ ] **Step 4: Commit**

```bash
git add docs/ROADMAP.md tests/
git commit -m "docs(timestamp): roadmap step 11 layer 3 done; optional real-token test"
```

- [ ] **Step 5: Push**

```bash
git push
```

---

## Self-Review

- **Spec coverage:** manifest digest (T1) ✓, storage layout `timestamps/` (T2,T4) ✓, best-effort publish (T7) ✓, retry/`labbook timestamp` (T4,T8) ✓, `verify` + endpoint (T5,T8,T9) ✓, `[timestamp]` config + default TSA + bundled cert (T0,T6) ✓, `rfc3161ng` dep (T0) ✓, honest scope/roadmap (T10) ✓.
- **Backward compatibility:** `publish()` defaults `timestamp_cfg=None` → existing publish tests untouched (T7 third test asserts this).
- **Signatures consistent:** `cfg` dict (`enabled`/`tsa_url`/`cert_bytes`/`paths`) used identically across `create_timestamp`, `retry_pending`, `verify_all`, `resolve_timestamp_config`. `verify_token` returns `gen_time` as ISO string everywhere.
- **No placeholders:** every step has runnable code/commands.
