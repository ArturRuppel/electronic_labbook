"""CODE-NN experiment identifier resolution.

Pure, cursor-based helpers extracted from the original ``api_server.py`` so the
identity logic (code allocation, repetition namespaces, the excluded marker) can
be unit-tested without a running Flask app. The grammar:

- a *code* is 5 letters/digits, a property of the experiment *title*; editing a
  title's code renames it for every session sharing that title;
- a *repetition* is a positive integer, with active and excluded reps kept in
  independent sequences scoped by ``(code, excluded)``;
- a leading ``X``/``x`` on the repetition field sets the excluded marker (``X3``).
"""

from eln.sdgl import CODE_RE, format_experiment_id


class ExperimentIdError(ValueError):
    """Raised when a submitted code/repetition is invalid or conflicts."""


def ensure_code_schema(cursor):
    """Create experiment_codes and the repetition / excluded columns if missing."""
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS experiment_codes "
        "(title TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE)"
    )
    columns = [row[1] for row in cursor.execute("PRAGMA table_info(experiments)")]
    if "repetition" not in columns:
        cursor.execute("ALTER TABLE experiments ADD COLUMN repetition INTEGER")
    # Every existing session starts active; the excluded sequence is opt-in.
    if "excluded" not in columns:
        cursor.execute("ALTER TABLE experiments ADD COLUMN excluded INTEGER DEFAULT 0")


def code_for_title(cursor, title):
    cursor.execute("SELECT code FROM experiment_codes WHERE title = ?", (title,))
    row = cursor.fetchone()
    return row[0] if row else None


def resolve_code_for_title(cursor, title, submitted_code):
    """Resolve the code for a title, treating an edited code as a rename.

    The code is a property of the title, so changing it renames the title's code
    for every session that shares the title. A new title needs a valid code; an
    existing title keeps its code unless a different valid, unique one is given."""
    code = (submitted_code or "").strip().upper()
    existing = code_for_title(cursor, title)

    if existing:
        if not code or code == existing:
            return existing
        # Editing the suggestion: rename this title's code everywhere.
        if not CODE_RE.match(code):
            raise ExperimentIdError("Code must be 5 characters (letters or digits).")
        cursor.execute(
            "SELECT title FROM experiment_codes WHERE code = ? AND title <> ?", (code, title)
        )
        if cursor.fetchone():
            raise ExperimentIdError(f"Code {code} is already used by another title.")
        cursor.execute("UPDATE experiment_codes SET code = ? WHERE title = ?", (code, title))
        return code

    if not CODE_RE.match(code):
        raise ExperimentIdError("A new title needs a 5-character code (letters or digits).")
    cursor.execute("SELECT title FROM experiment_codes WHERE code = ?", (code,))
    if cursor.fetchone():
        raise ExperimentIdError(f"Code {code} is already used by another title.")
    cursor.execute("INSERT INTO experiment_codes (title, code) VALUES (?, ?)", (title, code))
    return code


def used_repetitions(cursor, code, excluded, exclude_id=None):
    """Repetitions already taken within one namespace. Active and excluded reps
    are independent sequences scoped by (code, excluded), so the query filters by
    the excluded flag to keep the two namespaces from colliding."""
    cursor.execute(
        """
        SELECT e.id, e.repetition
        FROM experiments e
        JOIN experiment_codes c ON c.title = e.experiment_type
        WHERE c.code = ? AND e.repetition IS NOT NULL
              AND COALESCE(e.excluded, 0) = ?
        """,
        (code, 1 if excluded else 0),
    )
    return {row[1] for row in cursor.fetchall() if row[0] != exclude_id}


def resolve_repetition(cursor, code, submitted, exclude_id=None):
    """Validate a submitted repetition or default to the next free one, returning
    (rep, excluded).

    The repetition field carries the excluded marker: an optional leading X/x
    prefix sets the excluded flag and the digits set the repetition (X3, x03).
    An explicit number is required — bare "X" is rejected. Active and excluded
    reps are validated against their own namespace."""
    excluded = False
    if isinstance(submitted, str):
        token = submitted.strip()
        if token[:1] in ("X", "x"):
            excluded = True
            submitted = token[1:]
        else:
            submitted = token

    used = used_repetitions(cursor, code, excluded, exclude_id)

    # A blank repetition only ever means "next free active rep"; an X prefix with
    # no digits is an explicit-number-required error, handled in parsing below.
    if not excluded and submitted in (None, ""):
        rep = 1
        while rep in used:
            rep += 1
        return rep, excluded

    try:
        rep = int(submitted)
    except (TypeError, ValueError):
        raise ExperimentIdError("Repetition must be a positive integer.")
    if rep < 1:
        raise ExperimentIdError("Repetition must be a positive integer.")
    if rep in used:
        raise ExperimentIdError(f"{format_experiment_id(code, rep, excluded)} already exists.")
    return rep, excluded


def attach_experiment_id(cursor, exp):
    """Add resolved code / experiment_id (CODE-NN) to an experiment dict."""
    code = code_for_title(cursor, exp.get('experiment_type'))
    rep = exp.get('repetition')
    excluded = bool(exp.get('excluded'))
    exp['code'] = code
    exp['excluded'] = excluded
    exp['experiment_id'] = (
        format_experiment_id(code, rep, excluded) if code and rep is not None else None
    )
    return exp
