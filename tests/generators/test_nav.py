"""The shared nav renders core links plus plugin-contributed links, byte-exact."""

from eln.generators.nav import render_nav
from eln.plugins import NavLink, Plugin

EXPECTED = (
    '<div class="nav">\n'
    '        <a href="/">Data Graph</a>\n'
    '        <a href="experiments.html">Experiments</a>\n'
    '        <a href="protocols.html">Protocols</a>\n'
    '        <a href="reports.html">Reports</a>\n'
    '        <a href="presentations.html">Presentations</a>\n'
    '        <a href="documents.html">Documents</a>\n'
    '        <a href="code.html">Code</a>\n'
    '    </div>'
)


def test_render_nav_matches_expected_block():
    # Core links followed by the built-in plugin links, in registration order
    # (presentations, documents, code). Byte-exact so regeneration stays stable.
    assert render_nav() == EXPECTED


def test_render_nav_appends_plugin_links():
    extra = Plugin(name="widgets", nav=NavLink("Widgets", "widgets.html"))
    out = render_nav([extra])
    assert '<a href="/">Data Graph</a>' in out          # core preserved
    assert '<a href="widgets.html">Widgets</a>' in out   # plugin appended
