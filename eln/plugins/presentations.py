"""Presentations — the first plugin.

Re-expresses presentations entirely through the plugin extension points: a nav
entry, a static-page generator, and a static mount for the slide assets. Task 2
moves the generator/scan logic here; for now it wraps the existing
:mod:`eln.generators.presentations` so the registry has a real plugin.
"""

from pathlib import Path

from eln.generators.presentations import generate_presentations
from eln.plugins import NavLink, Plugin, StaticMount


plugin = Plugin(
    name="presentations",
    nav=NavLink("Presentations", "presentations.html"),
    generate=generate_presentations,
    static_mount=StaticMount("presentations", lambda root: Path(root) / "presentations"),
)
