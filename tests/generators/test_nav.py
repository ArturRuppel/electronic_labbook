"""The shared nav renders core links plus plugin-contributed links, byte-exact."""

from eln.generators.nav import render_nav
from eln.plugins import NavLink, Plugin

EXPECTED = (
    '<div class="nav">\n'
    '        <a href="/">Data Graph</a>\n'
    '        <a href="experiments.html">Experiments</a>\n'
    '        <a href="protocols.html">Protocols</a>\n'
    '        <a href="notebooks.html">Notebooks</a>\n'
    '        <a href="reports.html">Reports</a>\n'
    '        <a href="presentations.html">Presentations</a>\n'
    '    </div>'
)


def test_render_nav_matches_legacy_block():
    # With the default plugin set (presentations builtin) the bar is identical to
    # the previously hand-inlined HTML, keeping regeneration byte-for-byte stable.
    assert render_nav() == EXPECTED


def test_render_nav_appends_plugin_links():
    extra = Plugin(name="widgets", nav=NavLink("Widgets", "widgets.html"))
    out = render_nav([extra])
    assert '<a href="/">Data Graph</a>' in out          # core preserved
    assert '<a href="widgets.html">Widgets</a>' in out   # plugin appended
