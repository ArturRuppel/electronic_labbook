#!/usr/bin/env python3
"""Generate the documents catalog page (``documents.html``).

Scans ``ROOT/documents`` for freeform, **series-less** write-ups — notes, threads,
anything not tied to an experiment series. One folder per document (markdown or
notebook), rendered as the same collapsible cards as reports but with no database
or ``**Series:**`` coupling. No database is read; like presentations, documents
are a folder-scanned plugin, not a DB table.
"""

import argparse
import json
import re
from pathlib import Path

from eln.generators.code import build_code_index
from eln.generators.nav import render_nav
from eln.generators.reports import (
    REPORTS_HTML_TEMPLATE,
    discover_report_files,
    extract_report_date,
    markdown_to_html,
    notebook_markdown,
    render_notebook_full,
    _rewrite_relative_images,
)


def _document_card(doc_file, root, code_index=None):
    """Render one document file as a collapsible report-style card, or ``None``
    for a malformed notebook (skipped, mirroring the reports generator)."""
    nb = None
    if doc_file.suffix == ".ipynb":
        try:
            nb = json.loads(doc_file.read_text())
        except json.JSONDecodeError:
            print(f"Skipping malformed notebook document: {doc_file}")
            return None
        content = notebook_markdown(nb)
    else:
        content = doc_file.read_text()

    # Media links are authored relative to the document; rewrite them against the
    # catalog dir, exactly as reports do (so documents/<dir>/img.png resolves).
    doc_dir = doc_file.parent.relative_to(root)
    content = _rewrite_relative_images(content, doc_dir)
    html_content = markdown_to_html(content)

    # Title from the markdown H1, falling back to a prettified filename.
    title_match = re.search(r"^# (.+)$", content, re.MULTILINE)
    title = (title_match.group(1).strip() if title_match
             else doc_file.stem.replace("_", " ").replace("-", " ").title())
    slug = doc_file.stem
    doc_date = extract_report_date(content, doc_file)

    # Notebook documents carry a hidden full-notebook "Code" view + a toggle, just
    # like notebook reports; plain markdown documents render prose alone.
    if nb is not None:
        code_html = render_notebook_full(nb, doc_dir, code_index)
        toggle = f"""
                        <div class="report-view-toggle">
                            <button type="button" class="view-btn active" id="btn-report-{slug}"
                                    onclick="setReportView('{slug}', 'report')">Report</button>
                            <button type="button" class="view-btn" id="btn-code-{slug}"
                                    onclick="setReportView('{slug}', 'code')">Code</button>
                        </div>"""
        code_pane = f"""
                        <div class="report-code" id="code-{slug}" style="display: none;">
                            {code_html}
                        </div>"""
    else:
        toggle = ""
        code_pane = ""

    rel_src = doc_file.relative_to(root).as_posix()
    return f"""
                <div class="report-card" id="report-{slug}" data-report-src="{rel_src}">
                    <div class="report-header" onclick="toggleReport('{slug}')">
                        <div class="report-title-row">
                            <span class="expand-icon" id="icon-{slug}">&#9658;</span>
                            {title}
                        </div>
                        <div class="report-date">{doc_date}</div>
                    </div>
                    <div class="report-details" id="details-{slug}">{toggle}
                        <div class="report-view" id="view-{slug}">
                            <div class="report-content">
                                {html_content}
                            </div>
                        </div>{code_pane}
                    </div>
                </div>
            """


def generate_documents(root, catalog_out=None, plugins=None):
    """Generate ``documents.html`` by scanning ``root/documents``.

    Output is written to *catalog_out* (default ``root/catalog``). *plugins*
    (default: discovered by :func:`render_nav`) supply the shared nav links.
    """
    root = Path(root)
    documents_dir = root / "documents"
    catalog_dir = Path(catalog_out) if catalog_out else root / "catalog"

    doc_files = discover_report_files(documents_dir)

    code_index = build_code_index(root)
    cards = [c for c in (_document_card(f, root, code_index) for f in doc_files) if c]
    if cards:
        documents_html = "\n".join(cards)
    else:
        documents_html = ('<div class="no-reports">No documents yet. '
                          'Add a folder with a markdown file under documents/.</div>')

    html = REPORTS_HTML_TEMPLATE.format(
        nav=render_nav(plugins),
        reports_html=documents_html,
        page_title="Documents",
        page_heading="Documents",
        page_subtitle="Freeform notes and write-ups",
    )

    catalog_dir.mkdir(parents=True, exist_ok=True)
    output_file = catalog_dir / "documents.html"
    output_file.write_text(html)
    print(f"Documents catalog generated at: {output_file}")
    print(f"Total documents: {len(cards)}")
    return output_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="data-repo root (holds documents/)")
    parser.add_argument("--catalog-out", type=Path, default=None,
                        help="output directory (default: ROOT/catalog)")
    args = parser.parse_args(argv)
    generate_documents(args.root, args.catalog_out)


if __name__ == "__main__":
    main()
