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
