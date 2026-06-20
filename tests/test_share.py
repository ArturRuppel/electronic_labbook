"""Static-bundle export (Roadmap step 12): helpers, full/single export, CLI."""

from eln.share import _local_refs, _staticize, _strip_nav


def test_local_refs_keeps_relative_skips_external():
    html = (
        '<a href="experiments.html">x</a>'
        '<img src="reports/a/fig.png">'
        '<a href="https://example.com">y</a>'
        '<a href="//cdn/z.js">z</a>'
        '<a href="mailto:a@b.c">m</a>'
        '<a href="#top">t</a>'
        '<img src="data:image/png;base64,AAAA">'
        '<video><source src="reports/a/m.mp4?v=2#t"></video>'
    )
    assert _local_refs(html) == [
        "experiments.html", "reports/a/fig.png", "reports/a/m.mp4"
    ]


def test_staticize_drops_server_only_literals():
    html = (
        '<head>\n    <script src="auth.js"></script>\n</head>\n'
        '<div class="nav">\n'
        '        <a href="/">Data Graph</a>\n'
        '        <a href="experiments.html">Experiments</a>\n'
        '    </div>\n'
        '            <a href="/" class="card">\n'
        '                <div class="card-icon">D</div>\n'
        '                <div class="card-title">Data Graph</div>\n'
        '            </a>\n'
        '            <a href="reports.html" class="card">keep</a>\n'
    )
    out = _staticize(html)
    assert "auth.js" not in out
    assert 'href="/"' not in out
    assert "Data Graph" not in out
    assert 'href="experiments.html"' in out      # nav itself stays
    assert 'href="reports.html" class="card"' in out  # other cards stay


def test_strip_nav_removes_whole_nav_block():
    html = (
        'before\n'
        '    <div class="nav">\n'
        '        <a href="experiments.html">Experiments</a>\n'
        '    </div>\n'
        'after\n'
    )
    out = _strip_nav(html)
    assert '<div class="nav">' not in out
    assert "Experiments" not in out
    assert "before" in out and "after" in out
