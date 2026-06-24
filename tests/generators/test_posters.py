"""Posters catalog page — an SVG displayer driven by posters/posters.json."""

import json

from eln.generators.posters import (
    generate_posters,
    list_poster_files,
    load_index,
    save_index,
)


def _svg(root, name):
    posters = root / "posters"
    posters.mkdir(exist_ok=True)
    (posters / name).write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')


def _index(root, entries):
    (root / "posters").mkdir(exist_ok=True)
    (root / "posters" / "posters.json").write_text(json.dumps(entries))


def test_no_posters_message(tmp_path):
    out = generate_posters(tmp_path)
    assert out.name == "posters.html"
    html = out.read_text()
    assert ">Posters</p>" in html          # subtitle
    assert "No posters yet" in html


def test_renders_poster_entry(tmp_path):
    _svg(tmp_path, "talk.svg")
    _index(tmp_path, [{"title": "My Big Talk", "file": "talk.svg"}])
    html = generate_posters(tmp_path).read_text()
    assert "My Big Talk" in html
    assert 'src="posters/talk.svg"' in html
    assert 'data-poster-file="talk.svg"' in html
    assert "No posters yet" not in html
    # Card image is wired to the lightbox (click → expand in a popup).
    assert 'data-full="posters/talk.svg"' in html
    assert 'id="poster-modal"' in html


def test_entry_with_missing_file_is_flagged_not_broken(tmp_path):
    _index(tmp_path, [{"title": "Ghost", "file": "gone.svg"}])
    html = generate_posters(tmp_path).read_text()
    assert "Ghost" in html
    assert "SVG file not found" in html
    assert 'src="posters/gone.svg"' not in html   # no broken <img>


def test_title_is_html_escaped(tmp_path):
    _svg(tmp_path, "p.svg")
    _index(tmp_path, [{"title": "A & B <x>", "file": "p.svg"}])
    html = generate_posters(tmp_path).read_text()
    assert "A &amp; B &lt;x&gt;" in html


def test_load_index_tolerates_missing_and_malformed(tmp_path):
    assert load_index(tmp_path) == []                 # no folder at all
    (tmp_path / "posters").mkdir()
    (tmp_path / "posters" / "posters.json").write_text("{not json")
    assert load_index(tmp_path) == []                 # malformed → empty


def test_load_index_drops_incomplete_entries(tmp_path):
    _index(tmp_path, [{"title": "ok", "file": "a.svg"},
                      {"title": "", "file": "b.svg"},
                      {"title": "no file"}])
    assert load_index(tmp_path) == [{"title": "ok", "file": "a.svg"}]


def test_save_index_roundtrips(tmp_path):
    save_index(tmp_path, [{"title": " Padded ", "file": " a.svg "}])
    assert load_index(tmp_path) == [{"title": "Padded", "file": "a.svg"}]


def test_list_poster_files_only_svgs(tmp_path):
    _svg(tmp_path, "b.svg")
    _svg(tmp_path, "a.svg")
    (tmp_path / "posters" / "notes.txt").write_text("x")
    (tmp_path / "posters" / "posters.json").write_text("[]")
    assert list_poster_files(tmp_path) == ["a.svg", "b.svg"]
