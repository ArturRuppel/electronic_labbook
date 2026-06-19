"""Selectable data backup (Roadmap step 8).

Copies the identified raw+derived files tracked in SDGL's ``file_locations`` to a
user-chosen destination, organized by experiment CODE. Duplicate sightings of one
logical file are deduped by content hash: identical copies collapse to one,
differing copies are surfaced as a conflict for the user to resolve.
"""

import hashlib
import os
import shutil
import threading
from pathlib import Path

CHUNK = 1024 * 1024


def hash_file(path, chunk=CHUNK):
    """Stream a file's SHA-256 so large media never load fully into memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def dest_subpath(node_id):
    """Destination folder for a node, organized by CODE (over mirroring source paths).

    ``experiment:TFMSP-01`` -> ``TFMSP/TFMSP-01``; an excluded session keeps its
    own ``COV2D-X03`` folder; ``aggregate_analysis:TFMSP`` -> ``TFMSP/TFMSP_aggregate``.
    """
    kind, _, suffix = node_id.partition(":")
    if kind == "aggregate_analysis":
        return Path(suffix) / f"{suffix}_aggregate"
    code = suffix.split("-", 1)[0]
    return Path(code) / suffix
