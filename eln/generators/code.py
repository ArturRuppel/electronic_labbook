#!/usr/bin/env python3
"""Generate the code catalog page (``code.html``).

Scans ``ROOT/code`` for the reusable analysis source that report notebooks import
(e.g. ``code/cov2d/plotting.py``) and renders each ``.py`` file with build-time
syntax highlighting (Pygments). Highlighting is inlined — CSS in a ``<style>``
block, highlighted HTML in the page — so the page is self-contained and survives
``eln export``; no CDN or client-side JS.

Every file gets a stable anchor (``module_anchor``), and Pygments line anchors
give every line one too. :func:`build_code_index` exposes the file anchors keyed
by dotted module name, so a notebook's Code view can deep-link an ``import`` here
(see ``reports._linkify_imports``).
"""

import argparse
import ast
import re
from pathlib import Path

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import PythonLexer

from eln.generators.nav import render_nav
from eln.generators.reports import REPORTS_HTML_TEMPLATE

_PYGMENTS_STYLE = "default"


def iter_code_files(code_dir):
    """All ``.py`` files under *code_dir* (recursively), sorted by path so the
    page order is stable. ``__pycache__`` is skipped; ``__init__.py`` sorts first
    within its package (leading underscore < letters)."""
    code_dir = Path(code_dir)
    if not code_dir.exists():
        return []
    return sorted(
        p for p in code_dir.glob("**/*.py")
        if "__pycache__" not in p.parts
    )


def module_anchor(rel_posix):
    """Stable DOM id for a file given its path relative to ``code/``.

    ``cov2d/plotting.py`` -> ``code-cov2d-plotting-py``. Used both as the section
    ``id`` here and as the cross-link target in :func:`build_code_index`, so the
    two never drift."""
    return "code-" + re.sub(r"[^a-z0-9]+", "-", rel_posix.lower()).strip("-")


def module_dotted(rel_posix):
    """Dotted import name for a file relative to ``code/``.

    ``cov2d/plotting.py`` -> ``cov2d.plotting``; a package ``cov2d/__init__.py``
    -> ``cov2d`` (so ``import cov2d`` links to the package's ``__init__``)."""
    parts = rel_posix[:-3].split("/")  # drop the .py suffix
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def build_code_index(root):
    """Map every importable module under ``root/code`` to its ``code.html`` anchor.

    ``{"cov2d.plotting": "code.html#code-cov2d-plotting-py", ...}``. Empty when
    there is no ``code/`` directory. Consumed by the notebook-import linkifier."""
    code_dir = Path(root) / "code"
    index = {}
    for path in iter_code_files(code_dir):
        rel = path.relative_to(code_dir).as_posix()
        dotted = module_dotted(rel)
        if dotted:  # skip a bare top-level __init__.py (dotted == "")
            index[dotted] = f"code.html#{module_anchor(rel)}"
    return index


def top_level_symbols(src):
    """Top-level ``def``/``class`` names with their line numbers, for the sidebar.
    Best-effort: a file that does not parse contributes no symbols."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    return [(node.name, node.lineno) for node in tree.body if isinstance(node, kinds)]


def _code_css():
    """Pygments token styles (scoped to ``.highlight``) plus the code-page layout
    (sticky sidebar + highlighted file sections)."""
    pyg = HtmlFormatter(style=_PYGMENTS_STYLE).get_style_defs(".highlight")
    layout = """
        .container { max-width: 1180px; }
        .reports-list { display: block; }
        .code-layout { display: grid; grid-template-columns: 230px minmax(0, 1fr);
            gap: 1.5rem; align-items: start; }
        .code-sidebar { position: sticky; top: 1rem; max-height: calc(100vh - 2rem);
            overflow: auto; background: #fff; border: 1px solid #d7dde2;
            border-radius: 8px; padding: 0.8rem 0.9rem; font-size: 0.85rem; }
        .code-side-title { font-weight: 700; text-transform: uppercase;
            letter-spacing: 0.04em; font-size: 0.72rem; color: #5b6b78; margin-bottom: 0.5rem; }
        .code-sidebar .code-grp { font-weight: 700; color: #27313a; margin: 0.6rem 0 0.2rem;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
        .code-sidebar ul { list-style: none; margin: 0 0 0.2rem; padding-left: 0.6rem; }
        .code-sidebar a { color: #286b9f; text-decoration: none; }
        .code-sidebar a:hover { text-decoration: underline; }
        .code-sidebar .code-syms a { color: #5b6b78; font-family: ui-monospace, monospace;
            font-size: 0.8rem; }
        .code-file { background: #fff; border: 1px solid #d7dde2; border-radius: 8px;
            margin-bottom: 1.2rem; scroll-margin-top: 1rem; }
        .code-file-h { display: flex; align-items: center; gap: 0.5rem;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.95rem;
            padding: 0.7rem 0.9rem; border-bottom: 1px solid #eef1f4; background: #f7f9fb;
            border-radius: 8px 8px 0 0; }
        .code-file-h .code-permalink { color: #9aa7b1; text-decoration: none; margin-left: auto; }
        .code-file .highlight { margin: 0; overflow-x: auto; padding: 0.7rem 0.9rem;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.82rem;
            line-height: 1.5; }
        .code-file .highlight pre { margin: 0; background: none; line-height: 1.5; }
        .code-file .highlight a { text-decoration: none; color: inherit; }
    """
    return pyg + "\n" + layout


def _sidebar(entries):
    """Sidebar: files grouped by top-level package dir, each with its top-level
    symbols. *entries* is a list of (rel_posix, anchor, symbols) tuples."""
    groups = {}
    for rel, anchor, symbols in entries:
        grp = rel.split("/")[0] + "/" if "/" in rel else ""
        groups.setdefault(grp, []).append((rel, anchor, symbols))
    parts = ['<div class="code-side-title">Modules</div>']
    for grp in sorted(groups):
        if grp:
            parts.append(f'<div class="code-grp">{grp}</div>')
        parts.append("<ul>")
        for rel, anchor, symbols in groups[grp]:
            name = rel.split("/")[-1]
            parts.append(f'<li><a href="#{anchor}">{name}</a>')
            if symbols:
                parts.append('<ul class="code-syms">')
                for sym, lineno in symbols:
                    parts.append(f'<li><a href="#{anchor}-{lineno}">{sym}</a></li>')
                parts.append("</ul>")
            parts.append("</li>")
        parts.append("</ul>")
    return "\n".join(parts)


def _file_section(rel_posix, src):
    """One highlighted file section with a stable anchor and per-line anchors."""
    anchor = module_anchor(rel_posix)
    formatter = HtmlFormatter(nowrap=False, lineanchors=anchor, cssclass="highlight")
    body = highlight(src, PythonLexer(), formatter)
    return (
        f'<section class="code-file" id="{anchor}">'
        f'<div class="code-file-h"><span class="code-path">{rel_posix}</span>'
        f'<a class="code-permalink" href="#{anchor}" title="Link to this file">#</a></div>'
        f"{body}</section>"
    )


def generate_code(root, catalog_out=None, plugins=None):
    """Generate ``code.html`` by scanning ``root/code``.

    Output is written to *catalog_out* (default ``root/catalog``). *plugins*
    (default: discovered by :func:`render_nav`) supply the shared nav links.
    """
    root = Path(root)
    code_dir = root / "code"
    catalog_dir = Path(catalog_out) if catalog_out else root / "catalog"

    files = iter_code_files(code_dir)
    if not files:
        body = ('<div class="no-reports">No code yet. Reusable analysis modules '
                'that report notebooks import live under <code>code/</code>.</div>')
    else:
        entries, sections = [], []
        for path in files:
            rel = path.relative_to(code_dir).as_posix()
            src = path.read_text()
            entries.append((rel, module_anchor(rel), top_level_symbols(src)))
            sections.append(_file_section(rel, src))
        body = (
            f"<style>{_code_css()}</style>\n"
            f'<div class="code-layout">\n'
            f'<aside class="code-sidebar">{_sidebar(entries)}</aside>\n'
            f'<div class="code-main">{"".join(sections)}</div>\n'
            f"</div>"
        )

    html = REPORTS_HTML_TEMPLATE.format(
        nav=render_nav(plugins),
        reports_html=body,
        page_title="Code",
        page_heading="Code",
    )

    catalog_dir.mkdir(parents=True, exist_ok=True)
    output_file = catalog_dir / "code.html"
    output_file.write_text(html)
    print(f"Code catalog generated at: {output_file}")
    print(f"Total source files: {len(files)}")
    return output_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="data-repo root (holds code/)")
    parser.add_argument("--catalog-out", type=Path, default=None,
                        help="output directory (default: ROOT/catalog)")
    args = parser.parse_args(argv)
    generate_code(args.root, args.catalog_out)


if __name__ == "__main__":
    main()
