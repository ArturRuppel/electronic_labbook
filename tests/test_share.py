"""Static-bundle export (Roadmap step 12): helpers, full/single export, CLI."""

from eln.share import _local_refs, _staticize, _strip_nav, _collect_assets


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


def test_collect_assets_transitive_and_skips(tmp_path):
    root = tmp_path / "root"
    dest = tmp_path / "dest"
    # A presentation page links to a nested self-contained presentation html,
    # which in turn links a slide and a movie; a build script must NOT be copied.
    (root / "presentations" / "P").mkdir(parents=True)
    (root / "presentations" / "P" / "index.html").write_text(
        '<img src="slides/1.png"><source src="movie.mp4">'
    )
    (root / "presentations" / "P" / "slides").mkdir()
    (root / "presentations" / "P" / "slides" / "1.png").write_bytes(b"PNG")
    (root / "presentations" / "P" / "movie.mp4").write_bytes(b"MP4DATA")
    (root / "presentations" / "P" / "build.sh").write_text("echo unused")
    dest.mkdir()

    start = [("", '<a href="presentations/P/index.html">P</a>'
                  '<a href="experiments.html">sibling</a>')]
    # experiments.html is a generated sibling page already present in dest:
    (dest / "experiments.html").write_text("<html>generated</html>")

    seen, missing, total = _collect_assets(start, root, dest, generated={"experiments.html"})

    assert (dest / "presentations" / "P" / "index.html").is_file()
    assert (dest / "presentations" / "P" / "slides" / "1.png").read_bytes() == b"PNG"
    assert (dest / "presentations" / "P" / "movie.mp4").is_file()
    assert not (dest / "presentations" / "P" / "build.sh").exists()  # unreferenced
    index_text = '<img src="slides/1.png"><source src="movie.mp4">'
    assert total == len(b"PNG") + len(b"MP4DATA") + len(index_text)
    assert missing == []


def test_collect_assets_reports_missing(tmp_path):
    root = tmp_path / "root"; root.mkdir()
    dest = tmp_path / "dest"; dest.mkdir()
    start = [("", '<img src="reports/gone.png">')]
    seen, missing, total = _collect_assets(start, root, dest, generated=set())
    assert missing == ["reports/gone.png"]
    assert total == 0
