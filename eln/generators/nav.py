"""The shared nav bar, rendered from core links + plugin-contributed links.

Keeping this in one place is what makes **nav registration** a real extension
point: a plugin's :class:`~eln.plugins.NavLink` appears on every generated page
without editing each generator. The output is byte-for-byte identical to the
previously hand-inlined block so regeneration stays churn-free.
"""

from eln.plugins import NavLink, discover_plugins

# Core pages are part of the notebook itself, not plugins.
CORE_NAV = [
    NavLink("Data Explorer", "/"),
    NavLink("Experiment Catalog", "experiments.html"),
    NavLink("Reports", "reports.html"),
    NavLink("Protocols", "protocols.html"),
]

# Desired left-to-right tab order, by label. Links not listed here keep their
# natural (core-then-plugin) order and are appended after the known ones, so a
# new third-party plugin still shows up.
NAV_ORDER = [
    "Data Explorer",
    "Experiment Catalog",
    "Reports",
    "Protocols",
    "Code",
    "Documents",
    "Presentations",
    "Posters",
]


def render_nav(plugins=None):
    """Return the ``<div class="nav">…</div>`` block (no outer indent on the
    opening tag; inner links indented 8 spaces, closing tag 4) so callers can
    drop it in behind a 4-space template indent.

    Links are ordered by :data:`NAV_ORDER`; any not listed there are appended
    in their natural core-then-plugin order."""
    if plugins is None:
        plugins = discover_plugins()
    links = [*CORE_NAV, *(p.nav for p in plugins if p.nav)]
    rank = {label: i for i, label in enumerate(NAV_ORDER)}
    links.sort(key=lambda link: rank.get(link.label, len(rank)))
    rows = "\n".join(f'        <a href="{link.href}">{link.label}</a>' for link in links)
    return f'<div class="nav">\n{rows}\n    </div>'
