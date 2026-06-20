"""Auto per-series report scaffolding (reports/auto/<CODE>.md)."""

import sqlite3

from eln.db import init_db
from eln.generators.reports import AUTO_END, AUTO_START, generate_series_reports


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
    auto = tmp_path / "reports" / "auto"
    assert (auto / "COV2D.md").exists()
    assert not (auto / "SORVI.md").exists()   # claimed by a hand-authored report
    text = (auto / "COV2D.md").read_text()
    assert "**Series:** COV2D" in text
    assert "{{experiments}}" in text
    assert AUTO_START in text and AUTO_END in text
    assert [p.name for p in written] == ["COV2D.md"]


def test_regeneration_preserves_human_prose(tmp_path):
    _setup(tmp_path)
    generate_series_reports(tmp_path)
    cov = tmp_path / "reports" / "auto" / "COV2D.md"
    cov.write_text(cov.read_text() + "\n## My analysis\n\nProse the generator must keep.\n")
    generate_series_reports(tmp_path)   # re-run
    text = cov.read_text()
    assert "Prose the generator must keep." in text
    assert text.count(AUTO_START) == 1            # marked block not duplicated
    assert text.count("**Series:** COV2D") == 1


def test_auto_stub_not_self_claimed(tmp_path):
    """The auto stub declares its own series, but must not count as 'claimed' on a
    later run — otherwise the second run would stop refreshing it."""
    _setup(tmp_path)
    generate_series_reports(tmp_path)
    written = generate_series_reports(tmp_path)
    assert [p.name for p in written] == ["COV2D.md"]
