"""Presentations — the first plugin.

Re-expresses presentations entirely through the plugin extension points: a nav
entry, a static-page generator, a static mount for the slide assets, and a
home-page count. Task 2 moves the generator/scan logic here; for now it wraps the
existing :mod:`eln.generators.presentations` so the registry has a real plugin.
"""

from pathlib import Path

from eln.generators.presentations import generate_presentations
from eln.plugins import HomeCard, NavLink, Plugin, StaticMount


def count_presentations(root):
    """Count presentation decks: subdirs of ``root/presentations`` with an index."""
    pres_dir = Path(root) / "presentations"
    if not pres_dir.exists():
        return 0
    return sum(
        1 for d in pres_dir.iterdir() if d.is_dir() and (d / "index.html").exists()
    )


plugin = Plugin(
    name="presentations",
    nav=NavLink("Presentations", "presentations.html"),
    generate=generate_presentations,
    static_mount=StaticMount("presentations", lambda root: Path(root) / "presentations"),
    home_card=HomeCard("🎬", "Slide decks and seminar talks"),
    home_count=count_presentations,
)
