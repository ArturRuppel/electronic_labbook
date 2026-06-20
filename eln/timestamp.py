"""RFC 3161 trusted timestamps (Roadmap step 11, compliance layer 3).

Anchors a publish to a signed proof-of-existence-at-a-time over a content
manifest digest of the published snapshot. Self-contained: verification needs
only the token, the recomputed digest, and the TSA cert -- not git or GitHub.

See ``docs/superpowers/specs/2026-06-20-rfc3161-timestamps-design.md``.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import rfc3161ng

from eln.hashing import sha256_hex

DEFAULT_TSA_URL = "https://freetsa.org/tsr"
DEFAULT_TSA_CERT = Path(__file__).parent / "certs" / "freetsa_cacert.pem"
TIMESTAMPS_DIR = "timestamps"

# Paths whose contents a snapshot covers (mirrors publish.PUBLISH_PATHS; the
# timestamps dir itself is included so prior tokens are part of later snapshots).
SNAPSHOT_PATHS = ["experiments.sql", "reports", "presentations", "thumbnails",
                  TIMESTAMPS_DIR]


# ---- manifest + snapshot digest ------------------------------------------

def _iter_files(root, paths):
    """Yield ``(relpath_posix, abspath)`` for every file under each path, sorted."""
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


# ---- timestamp id + index I/O --------------------------------------------

def make_timestamp_id(digest_hex, when=None):
    """``<UTCstamp>-<digest[:12]>`` — sortable, collision-resistant per publish."""
    when = when or datetime.now(timezone.utc)
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{digest_hex[:12]}"


def _index_path(root):
    return Path(root) / TIMESTAMPS_DIR / "index.jsonl"


def read_index(root):
    path = _index_path(root)
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
    _index_path(root).write_text(
        "".join(json.dumps(e, sort_keys=True) + "\n" for e in rows), encoding="utf-8")


# ---- TSA request + token verify (rfc3161ng wrappers) ---------------------

def request_timestamp(digest_hex, *, tsa_url, cert_bytes, timeout=10):
    """Request a DER timestamp token for ``digest_hex`` from the TSA.

    Raises on any network/TSA failure (the caller decides best-effort handling).
    """
    stamper = rfc3161ng.RemoteTimestamper(
        tsa_url, certificate=cert_bytes, hashname="sha256", timeout=timeout)
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


# ---- orchestration --------------------------------------------------------

def _timestamps_dir(root):
    d = Path(root) / TIMESTAMPS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_timestamp(root, paths, cfg):
    """Compute the snapshot digest, request a token, and record the result.

    Returns the index entry. On TSA failure the entry is ``status="pending"``
    (the manifest is persisted so a later retry can re-request the same digest).
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
        updated.append({**entry, "status": "ok", "gen_time": result.get("gen_time")})
    return updated


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
        result = verify_token(token_path.read_bytes(), entry["snapshot_digest"],
                              cfg["cert_bytes"])
        if result["valid"]:
            summary["ok"] += 1
            latest_ok_digest = entry["snapshot_digest"]
        else:
            summary["invalid"].append({"id": entry["id"], "reason": result["reason"]})

    if latest_ok_digest is not None:
        current_digest, _ = snapshot_digest(root, cfg["paths"])
        summary["live_anchored"] = (current_digest == latest_ok_digest)
    return summary


# ---- config normalization -------------------------------------------------

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
