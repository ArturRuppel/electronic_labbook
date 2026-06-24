"""The shared nav renders core links plus plugin-contributed links, byte-exact."""

from eln.generators.nav import render_nav
from eln.plugins import NavLink, Plugin

EXPECTED = (
    '<div class="nav">\n'
    '        <a href="/">Data Explorer</a>\n'
    '        <a href="experiments.html">Experiment Catalog</a>\n'
    '        <a href="reports.html">Reports</a>\n'
    '        <a href="protocols.html">Protocols</a>\n'
    '        <a href="code.html">Code</a>\n'
    '        <a href="documents.html">Documents</a>\n'
    '        <a href="presentations.html">Presentations</a>\n'
    '        <a href="posters.html">Posters</a>\n'
    '    </div>'
)


def test_render_nav_matches_expected_block():
    # Core + plugin links reordered by NAV_ORDER (Posters last). Byte-exact so
    # regeneration stays stable.
    assert render_nav() == EXPECTED


def test_render_nav_appends_plugin_links():
    extra = Plugin(name="widgets", nav=NavLink("Widgets", "widgets.html"))
    out = render_nav([extra])
    assert '<a href="/">Data Explorer</a>' in out       # core preserved
    assert '<a href="widgets.html">Widgets</a>' in out   # plugin appended


def test_sdgl_static_nav_matches_render_nav():
    """The SDGL viewer (served at /) is a static page with a hand-coded nav, not
    render_nav output. Keep its link set in sync with the canonical nav so new
    pages/plugins (e.g. Documents, Code) appear there too instead of silently
    drifting — which is exactly how the Code tab went missing from the / page."""
    import re
    from pathlib import Path

    sdgl = (Path(__file__).resolve().parents[2] / "catalog" / "sdgl.html").read_text()
    static_block = re.search(r'<nav class="nav">(.*?)</nav>', sdgl, re.DOTALL).group(1)
    static_hrefs = re.findall(r'href="([^"]+)"', static_block)
    canonical_hrefs = re.findall(r'href="([^"]+)"', render_nav())
    assert static_hrefs == canonical_hrefs
