"""Auto per-series report scaffolding (reports/<CODE>/<CODE>.md)."""

import json
import sqlite3

from eln.db import init_db
from eln.generators.reports import AUTO_END, AUTO_START, generate_series_reports


def _notebook_with_markdown(text):
    """A minimal .ipynb whose single markdown cell holds *text*."""
    return json.dumps({
        "cells": [{"cell_type": "markdown", "source": text}],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
    })


def _setup(root):
    """A repo with two series — SORVI claimed by a hand-authored report, COV2D
    unclaimed — and one active repetition each."""
    db = root / "experiments.db"
    init_db.init_db(db)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO experiment_codes (title, code) VALUES ('Sorting', 'SORVI')")
    conn.execute("INSERT INTO experiment_codes (title, code) VALUES ('Coverage', 'COV2D')")
    conn.execute("INSERT INTO experiments (id, experiment_type, repetition, excluded, file_path) "
                 "VALUES (1,'Sorting',1,0,'x')")
    conn.execute("INSERT INTO experiments (id, experiment_type, repetition, excluded, file_path) "
                 "VALUES (2,'Coverage',1,0,'x')")
    conn.commit()
    conn.close()
    reports = root / "reports"
    reports.mkdir()
    (reports / "sorvi_notes.md").write_text(
        "# Notes\n\n**Series:** SORVI\n\n{{experiments}}\n")


def test_scaffolds_unclaimed_series_only(tmp_path):
    _setup(tmp_path)
    written = generate_series_reports(tmp_path)
    reports = tmp_path / "reports"
    assert (reports / "COV2D" / "COV2D.md").exists()
    assert not (reports / "SORVI" / "SORVI.md").exists()   # claimed by a hand-authored report
    text = (reports / "COV2D" / "COV2D.md").read_text()
    assert "**Series:** COV2D" in text
    assert "{{experiments}}" in text
    assert AUTO_START in text and AUTO_END in text
    assert [p.name for p in written] == ["COV2D.md"]


def test_regeneration_preserves_human_prose(tmp_path):
    _setup(tmp_path)
    generate_series_reports(tmp_path)
    cov = tmp_path / "reports" / "COV2D" / "COV2D.md"
    cov.write_text(cov.read_text() + "\n## My analysis\n\nProse the generator must keep.\n")
    generate_series_reports(tmp_path)   # re-run
    text = cov.read_text()
    assert "Prose the generator must keep." in text
    assert text.count(AUTO_START) == 1            # marked block not duplicated
    assert text.count("**Series:** COV2D") == 1


def test_notebook_report_claims_its_series(tmp_path):
    """A hand-authored .ipynb declaring **Series:** COV2D claims it just like a
    .md report would — so no duplicate auto stub is scaffolded for COV2D."""
    _setup(tmp_path)
    (tmp_path / "reports" / "cov2d_report.ipynb").write_text(
        _notebook_with_markdown("# COV2D\n\n**Series:** COV2D\n\n{{experiments}}\n"))
    written = generate_series_reports(tmp_path)
    assert not (tmp_path / "reports" / "COV2D" / "COV2D.md").exists()
    assert [p.name for p in written] == []


def test_malformed_notebook_does_not_break_dedup(tmp_path):
    """A corrupt .ipynb is skipped during the claim scan rather than crashing."""
    _setup(tmp_path)
    (tmp_path / "reports" / "broken.ipynb").write_text("{not json")
    written = generate_series_reports(tmp_path)   # must not raise
    assert [p.name for p in written] == ["COV2D.md"]


def test_series_with_no_active_experiments_is_skipped(tmp_path):
    """An orphaned title->code mapping (no active experiments) gets no stub."""
    _setup(tmp_path)
    conn = sqlite3.connect(tmp_path / "experiments.db")
    conn.execute("INSERT INTO experiment_codes (title, code) VALUES ('Ghost', 'GHOST')")
    # An *excluded*-only series is still "no active repetitions" -> skipped.
    conn.execute("INSERT INTO experiments (id, experiment_type, repetition, excluded, file_path) "
                 "VALUES (3,'Ghost',1,1,'x')")
    conn.commit()
    conn.close()
    written = generate_series_reports(tmp_path)
    assert not (tmp_path / "reports" / "GHOST" / "GHOST.md").exists()
    assert [p.name for p in written] == ["COV2D.md"]


def test_auto_stub_not_self_claimed(tmp_path):
    """The auto stub declares its own series, but must not count as 'claimed' on a
    later run — otherwise the second run would stop refreshing it."""
    _setup(tmp_path)
    generate_series_reports(tmp_path)
    written = generate_series_reports(tmp_path)
    assert [p.name for p in written] == ["COV2D.md"]
