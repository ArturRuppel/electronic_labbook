"""Reports generator: series parsing, notebook rendering, provenance footer."""

from eln.generators.reports import parse_series


def test_parse_series_alpha_code():
    assert parse_series("intro\n**Series:** SORVI\nmore") == "SORVI"


def test_parse_series_alphanumeric_code():
    # Regression: the old [A-Z]{5} regex did not match a code with a digit.
    assert parse_series("# COV2D\n**Series:** COV2D\n{{experiments}}") == "COV2D"


def test_parse_series_absent():
    assert parse_series("no series declared here") is None


def test_parse_series_rejects_non_code():
    # A five-char token that is not a valid code grammar is not a series.
    assert parse_series("**Series:** ab cd") is None


from eln.generators.reports import notebook_markdown


def _nb(cells):
    return {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}


def test_notebook_markdown_keeps_markdown_drops_code():
    nb = _nb([
        {"cell_type": "markdown", "source": ["# Title\n", "\n", "**prose**\n"]},
        {"cell_type": "code", "source": ["import numpy as np\n"], "outputs": []},
        {"cell_type": "markdown", "source": ["After the code.\n"]},
    ])
    md = notebook_markdown(nb)
    assert "# Title" in md
    assert "**prose**" in md
    assert "After the code." in md
    assert "import numpy" not in md  # code cell fully hidden


def test_notebook_markdown_ignores_outputs():
    nb = _nb([
        {"cell_type": "code", "source": ["print('hi')\n"],
         "outputs": [{"output_type": "stream", "name": "stdout", "text": ["hi\n"]}]},
    ])
    assert notebook_markdown(nb).strip() == ""


def test_notebook_markdown_source_as_string():
    nb = _nb([{"cell_type": "markdown", "source": "plain string\n"}])
    assert "plain string" in notebook_markdown(nb)
