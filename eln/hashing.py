"""Content hashing helpers, dependency-free so any layer can import them.

Both the SDGL backup tool (duplicate detection) and the analysis-provenance
library (input/artifact fingerprints) need a streamed file hash; keeping it here
avoids a circular import between ``eln.sdgl`` and ``eln.analysis``.
"""

from __future__ import annotations

import hashlib

_CHUNK = 1 << 20  # 1 MiB


def sha256_hex(path, chunk=_CHUNK):
    """Return the lowercase hex SHA-256 of ``path``'s contents."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_file(path, chunk=_CHUNK):
    """Return the SHA-256 of ``path`` as a prefixed ``"sha256:<hex>"`` string.

    The prefix records the algorithm alongside the digest so provenance records
    stay self-describing if the hash function ever changes.
    """
    return "sha256:" + sha256_hex(path, chunk)
