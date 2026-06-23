"""Documents — a folder-scanned plugin for freeform, series-less write-ups.

Mirrors the presentations plugin: a nav entry, a static-page generator, and a
static mount for the document media. Documents are *not* a database table — the
generator scans ``ROOT/documents`` and renders each markdown/notebook document as
a card, exactly as presentations scan ``ROOT/presentations``.
"""

from pathlib import Path

from eln.generators.documents import generate_documents
from eln.plugins import NavLink, Plugin, StaticMount


plugin = Plugin(
    name="documents",
    nav=NavLink("Documents", "documents.html"),
    generate=generate_documents,
    static_mount=StaticMount("documents", lambda root: Path(root) / "documents"),
)
