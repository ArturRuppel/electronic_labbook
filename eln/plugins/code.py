"""Code — a folder-scanned plugin for the reusable analysis source.

Mirrors the documents plugin: a nav entry and a static-page generator. Scans
``ROOT/code`` and renders each ``.py`` module with syntax highlighting on a single
``code.html`` page, so the analysis machinery that report notebooks import is
inspectable in the web interface (and deep-linkable from a notebook's Code view).
Highlighting is inlined at build time, so there is no asset mount to serve.
"""

from eln.generators.code import generate_code
from eln.plugins import NavLink, Plugin


plugin = Plugin(
    name="code",
    nav=NavLink("Code", "code.html"),
    generate=generate_code,
)
