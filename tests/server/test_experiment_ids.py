"""Unit tests for the CODE-NN identifier helpers (no Flask needed)."""

import sqlite3

import pytest

from eln.db import init_db
from eln.server.experiment_ids import (
    ExperimentIdError,
    code_for_title,
    ensure_code_schema,
    resolve_code_for_title,
    resolve_repetition,
)


@pytest.fixture
def cursor(tmp_path):
    db = tmp_path / "experiments.db"
    init_db.init_db(db)
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    ensure_code_schema(cur)
    yield cur
    conn.close()


def test_new_title_requires_valid_code(cursor):
    with pytest.raises(ExperimentIdError):
        resolve_code_for_title(cursor, "Traction Force", "")
    with pytest.raises(ExperimentIdError):
        resolve_code_for_title(cursor, "Traction Force", "abc")  # too short
    assert resolve_code_for_title(cursor, "Traction Force", "tfmsp") == "TFMSP"
    assert code_for_title(cursor, "Traction Force") == "TFMSP"


def test_existing_title_keeps_code_and_rename_propagates(cursor):
    resolve_code_for_title(cursor, "Traction Force", "TFMSP")
    # No code given → keep existing.
    assert resolve_code_for_title(cursor, "Traction Force", "") == "TFMSP"
    # New valid code → rename.
    assert resolve_code_for_title(cursor, "Traction Force", "TFMNW") == "TFMNW"
    assert code_for_title(cursor, "Traction Force") == "TFMNW"


def test_code_collision_across_titles_rejected(cursor):
    resolve_code_for_title(cursor, "Traction Force", "TFMSP")
    with pytest.raises(ExperimentIdError):
        resolve_code_for_title(cursor, "Migration", "TFMSP")


def test_repetition_defaults_to_next_free_active(cursor):
    resolve_code_for_title(cursor, "Traction Force", "TFMSP")
    cursor.execute(
        "INSERT INTO experiments (experiment_type, repetition, excluded, file_path) "
        "VALUES ('Traction Force', 1, 0, 'x')"
    )
    rep, excluded = resolve_repetition(cursor, "TFMSP", None)
    assert (rep, excluded) == (2, False)


def test_excluded_namespace_is_independent(cursor):
    resolve_code_for_title(cursor, "Traction Force", "TFMSP")
    cursor.execute(
        "INSERT INTO experiments (experiment_type, repetition, excluded, file_path) "
        "VALUES ('Traction Force', 1, 0, 'x')"
    )
    # X1 is free even though active rep 1 is taken.
    rep, excluded = resolve_repetition(cursor, "TFMSP", "X1")
    assert (rep, excluded) == (1, True)


def test_duplicate_repetition_rejected(cursor):
    resolve_code_for_title(cursor, "Traction Force", "TFMSP")
    cursor.execute(
        "INSERT INTO experiments (experiment_type, repetition, excluded, file_path) "
        "VALUES ('Traction Force', 2, 0, 'x')"
    )
    with pytest.raises(ExperimentIdError):
        resolve_repetition(cursor, "TFMSP", "2")


def test_repetition_must_be_positive_integer(cursor):
    resolve_code_for_title(cursor, "Traction Force", "TFMSP")
    with pytest.raises(ExperimentIdError):
        resolve_repetition(cursor, "TFMSP", "abc")
    with pytest.raises(ExperimentIdError):
        resolve_repetition(cursor, "TFMSP", "0")
