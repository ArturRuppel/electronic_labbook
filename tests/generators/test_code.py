"""Code catalog page — highlighted source under code/, with deep-linkable anchors."""

from eln.generators.code import (
    build_code_index,
    generate_code,
    module_anchor,
    module_dotted,
    top_level_symbols,
)
from eln.generators.reports import _linkify_imports, render_notebook_full


def _mod(root, relpath, text):
    p = root / "code" / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


# --- unit: anchor / dotted-name / symbol helpers -----------------------------
def test_module_anchor_and_dotted():
    assert module_anchor("cov2d/plotting.py") == "code-cov2d-plotting-py"
    assert module_dotted("cov2d/plotting.py") == "cov2d.plotting"
    # a package __init__ collapses to the package's dotted name
    assert module_dotted("cov2d/__init__.py") == "cov2d"


def test_top_level_symbols_skips_unparseable():
    assert top_level_symbols("def a():\n    pass\nclass B:\n    pass\n") == [("a", 1), ("B", 3)]
    assert top_level_symbols("def oops(:\n") == []  # syntax error -> no symbols


# --- build_code_index --------------------------------------------------------
def test_build_code_index_maps_modules_to_anchors(tmp_path):
    _mod(tmp_path, "cov2d/__init__.py", "")
    _mod(tmp_path, "cov2d/plotting.py", "x = 1\n")
    index = build_code_index(tmp_path)
    assert index["cov2d.plotting"] == "code.html#code-cov2d-plotting-py"
    assert index["cov2d"] == "code.html#code-cov2d-init-py"


def test_build_code_index_empty_without_code_dir(tmp_path):
    assert build_code_index(tmp_path) == {}


# --- generate_code -----------------------------------------------------------
def test_no_code_message(tmp_path):
    out = generate_code(tmp_path)
    assert out.name == "code.html"
    html = out.read_text()
    assert "Code" in html              # page heading
    assert "No code yet" in html


def test_renders_highlighted_source_with_anchors(tmp_path):
    _mod(tmp_path, "cov2d/plotting.py", "def write_superplot():\n    return 1\n")
    html = generate_code(tmp_path).read_text()
    assert 'id="code-cov2d-plotting-py"' in html          # file anchor (cross-link target)
    assert 'class="highlight"' in html                    # pygments highlighted block
    assert "write_superplot" in html
    assert 'href="#code-cov2d-plotting-py-1"' in html      # sidebar symbol -> line anchor
    assert "cov2d/plotting.py" in html                     # file path heading
    assert "No code yet" not in html


# --- cross-linking notebook imports -> Code page -----------------------------
def test_linkify_imports_wraps_known_modules():
    index = {"cov2d.plotting": "code.html#code-cov2d-plotting-py",
             "cov2d": "code.html#code-cov2d-init-py"}
    escaped = "from cov2d.plotting import write_superplot"
    out = _linkify_imports(escaped, index)
    assert '<a class="code-xref" href="code.html#code-cov2d-plotting-py">cov2d.plotting</a>' in out


def test_linkify_imports_respects_token_boundaries():
    index = {"cov2d": "code.html#code-cov2d-init-py"}
    # 'cov2d' inside 'cov2d.plotting' (unknown submodule) must NOT be linked,
    # nor inside a longer identifier.
    assert "<a" not in _linkify_imports("import cov2d.plotting", index)
    assert "<a" not in _linkify_imports("x = mycov2d", index)
    assert '<a class="code-xref"' in _linkify_imports("import cov2d", index)


def test_linkify_noop_without_index():
    assert _linkify_imports("from cov2d.plotting import x", {}) == "from cov2d.plotting import x"


def test_render_notebook_full_links_code_cells():
    nb = {"cells": [{"cell_type": "code", "execution_count": 1,
                     "source": ["from cov2d.figures import screen\n"], "outputs": []}]}
    index = {"cov2d.figures": "code.html#code-cov2d-figures-py"}
    html = render_notebook_full(nb, "reports/COV2D", index)
    assert 'href="code.html#code-cov2d-figures-py">cov2d.figures</a>' in html
