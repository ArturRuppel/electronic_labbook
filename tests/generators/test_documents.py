"""Documents catalog page — freeform, series-less write-ups under documents/."""

import json

from eln.generators.documents import generate_documents


def _doc(root, dirname, filename, text):
    d = root / "documents" / dirname
    d.mkdir(parents=True)
    (d / filename).write_text(text)
    return d


def test_no_documents_message(tmp_path):
    out = generate_documents(tmp_path)
    assert out.name == "documents.html"
    html = out.read_text()
    assert "Documents" in html           # page heading
    assert "No documents yet" in html


def test_renders_markdown_document(tmp_path):
    _doc(tmp_path, "2026-05-05_thread", "2026-05-05_thread.md",
         "# A Thread\n\n**Date:** 2026-05-05\n\nHello body text.\n")
    html = generate_documents(tmp_path).read_text()
    assert "A Thread" in html            # H1 used as card title
    assert "Hello body text." in html
    assert "2026-05-05" in html          # date pulled from **Date:**
    assert "No documents yet" not in html


def test_relative_media_rewritten_against_documents_dir(tmp_path):
    _doc(tmp_path, "2026-05-05_thread", "2026-05-05_thread.md",
         "# T\n\n![clip](post1.png)\n")
    html = generate_documents(tmp_path).read_text()
    # Media authored relative to the doc resolves under documents/<dir>/.
    assert "documents/2026-05-05_thread/post1.png" in html


def test_readme_is_not_a_document(tmp_path):
    (tmp_path / "documents").mkdir()
    (tmp_path / "documents" / "README.md").write_text("# Docs folder\n\nnot a doc\n")
    html = generate_documents(tmp_path).read_text()
    assert "No documents yet" in html
    assert "Docs folder" not in html


def test_malformed_notebook_is_skipped(tmp_path):
    _doc(tmp_path, "broken", "broken.ipynb", "{not json")
    html = generate_documents(tmp_path).read_text()   # must not raise
    assert "No documents yet" in html


def test_notebook_document_renders_markdown_cells(tmp_path):
    nb = json.dumps({
        "cells": [{"cell_type": "markdown", "source": "# NB Doc\n\nprose"}],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
    })
    _doc(tmp_path, "nbdoc", "nbdoc.ipynb", nb)
    html = generate_documents(tmp_path).read_text()
    assert "NB Doc" in html
    assert "prose" in html
