#!/usr/bin/env python3
"""Scientific Data Graph Layer: storage, migration, and scanner.

Ported from the original in-place ``sdgl.py``. Two changes from
the original:

1. The ELN database defaults to ``<root>/experiments.db`` (the data-repo layout),
   not ``<root>/data/experiments.db``.
2. The scan materializes ``experiment_metadata.start_date`` (earliest raw-file
   mtime) into the ELN database, so the derived dates ride inside experiments.sql
   and the generators never need sdgl.db (Plan G).

The already-debugged refinements are preserved as acceptance criteria: hidden-
folder exclusion (os.walk loops + reports glob + self-healing prune of recorded
hidden paths) and raw-only date derivation (qualifier='raw').
"""

import hashlib
import json
import os
import re
import sqlite3
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

from eln.hashing import sha256_file


# Legacy AA00-style public UID. Retired as the node id (CODE-NN replaces it) but
# the column and allocator linger until the DB is tidied out manually.
UID_RE = re.compile(r"^[A-Z]{2}[0-9]{2}$")

# A 5-character experiment code (letters and/or digits) and the CODE-NN
# identifier built from it. The code is fixed-length and the repetition is
# dash-delimited, so digits in the code stay unambiguous (TFM01-02 -> rep 2).
CODE_RE = re.compile(r"^[A-Z0-9]{5}$")
# A directory matches an experiment when its name is EXACTLY the CODE-NN id — no
# trailing tags. Downstream structure (raw/, analysis/, ...) comes from nesting
# beneath the folder, e.g. SORVI-01/raw, not from the folder name. The repetition
# is matched numerically, so SPHIM-01 is rep 1 while SPHIM-010 is rep 10 (a
# different experiment). An optional X before the digits marks an excluded session
# (COV2D-X03), numbered in its own per-family sequence independent of the active ones.
ID_FOLDER_RE = re.compile(
    r"^(?P<code>[A-Z0-9]{5})-(?P<excl>X?)(?P<rep>\d+)$"
)
# A bare experiment-code folder (CODE with no -NN repetition) holds aggregate
# analyses or other material spanning the whole experiment. The name must be
# exactly the 5-character code. The shape alone is ambiguous (NOTES, TOOLS, ADMIN
# all match [A-Z0-9]{5}), so a bare folder is only ever recognized when its code is
# a known experiment code. The CODE-NN form is matched first, so repetition folders
# never fall through to this pattern.
CODE_FOLDER_RE = re.compile(r"^(?P<code>[A-Z0-9]{5})$")

CORE_NODE_TYPES = {
    "experiment",
    "protocol",
    "dataset",
    "analysis",
    "aggregate_analysis",
    "report",
    "file_bundle",
}

CORE_RELATION_TYPES = {
    "uses_protocol",
    "derived_from",
    "analyzed_by",
    "generates",
    "documents",
    "contains",
    "version_of",
    "has_report",
}


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_hash(*parts):
    digest = hashlib.sha1()
    for part in parts:
        digest.update(str(part).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def json_dumps(value):
    return json.dumps(value or {}, sort_keys=True)


def json_loads(value):
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {"raw": value}


def uid_for_index(index):
    if index < 0 or index >= 26 * 26 * 100:
        raise ValueError("experiment UID index is outside AA00-ZZ99")
    letters, digits = divmod(index, 100)
    first, second = divmod(letters, 26)
    return f"{chr(ord('A') + first)}{chr(ord('A') + second)}{digits:02d}"


def allocate_experiment_uids(db_path):
    """Add experiments.experiment_uid when missing and allocate stable public UIDs."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(experiments)")
    columns = [row[1] for row in cursor.fetchall()]
    if "experiment_uid" not in columns:
        cursor.execute("ALTER TABLE experiments ADD COLUMN experiment_uid TEXT")

    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_experiments_experiment_uid "
        "ON experiments(experiment_uid)"
    )

    rows = cursor.execute(
        "SELECT id, experiment_uid FROM experiments ORDER BY id"
    ).fetchall()
    used = {uid for _, uid in rows if uid}
    next_index = 0
    for experiment_id, current_uid in rows:
        if current_uid:
            continue
        while uid_for_index(next_index) in used:
            next_index += 1
        uid = uid_for_index(next_index)
        cursor.execute(
            "UPDATE experiments SET experiment_uid = ? WHERE id = ?",
            (uid, experiment_id),
        )
        used.add(uid)

    conn.commit()
    conn.close()


def format_experiment_id(code, repetition, excluded=False):
    """Build the CODE-NN identifier, zero-padded to width 2 (widening past 99).

    An excluded session carries an X before the digits (COV2D-X03); active and
    excluded repetitions are independent sequences scoped by (code, excluded)."""
    try:
        rep = int(repetition)
    except (TypeError, ValueError):
        rep = 0
    if excluded:
        return f"{code}-X{rep:02d}"
    return f"{code}-{rep:02d}"


def parse_id_folder(name):
    """Parse a folder name into {code, rep, excluded} when it carries a CODE-NN
    token. An X before the digits (COV2D-X03) marks an excluded session."""
    match = ID_FOLDER_RE.match(name)
    if not match:
        return None
    return {
        "code": match.group("code"),
        "rep": int(match.group("rep")),
        "excluded": bool(match.group("excl")),
    }


def parse_code_folder(name):
    """Parse a folder name into {code} when it is a bare experiment-code folder
    (no -NN repetition). Returns None for CODE-NN folders and non-matches; the
    caller must still confirm the code is a known experiment before recognizing
    it, since the name shape is otherwise ambiguous."""
    if parse_id_folder(name):
        return None
    match = CODE_FOLDER_RE.match(name)
    if not match:
        return None
    return {"code": match.group("code")}


def _root_is_observable(root_path):
    """Whether a scan root's filesystem can be trusted as the source of truth.

    A root must exist and contain at least one entry. An unmounted drive's mount
    point usually lingers as an empty directory, which is indistinguishable from a
    genuinely empty root — so we treat "exists but empty" (and any unreadable
    root) as unobservable and refuse to prune its prior entries."""
    try:
        with os.scandir(root_path) as entries:
            return any(True for _ in entries)
    except OSError:
        return False


def _is_hidden(name):
    """Dot-prefixed names are invisible (.git, .venv, .DS_Store, ...). They are
    excluded at scan time so they never appear in any listing."""
    return name.startswith(".")


def derive_code(title, used):
    """Derive a unique 5-character [A-Z0-9]{5} code from a title, avoiding `used`.

    Used to backfill codes for pre-existing titles; new titles set their code
    explicitly through the admin form."""
    letters = re.sub(r"[^A-Za-z0-9]", "", title or "").upper()
    base = (letters + "XXXXX")[:5]
    if base not in used:
        return base
    # Resolve collisions by varying the last position first, then earlier ones.
    for pos in range(4, -1, -1):
        for char in string.ascii_uppercase:
            candidate = base[:pos] + char + base[pos + 1:]
            if candidate not in used:
                return candidate
    raise ValueError("could not derive a unique code for title: " + (title or ""))


def allocate_experiment_codes(db_path):
    """Ensure the experiment_codes table and repetition column exist and backfill
    both. Idempotent and self-healing (mirrors allocate_experiment_uids) so the
    CODE-NN identity works even before the dedicated migration script is run."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS experiment_codes (
            title TEXT PRIMARY KEY,
            code  TEXT NOT NULL UNIQUE
        )
        """
    )
    cursor.execute("PRAGMA table_info(experiments)")
    columns = [row[1] for row in cursor.fetchall()]
    if "repetition" not in columns:
        cursor.execute("ALTER TABLE experiments ADD COLUMN repetition INTEGER")
    # Every existing session starts active; the excluded sequence is opt-in.
    if "excluded" not in columns:
        cursor.execute("ALTER TABLE experiments ADD COLUMN excluded INTEGER DEFAULT 0")

    # Backfill a code for every title that lacks one, in first-appearance order.
    # Normalize titles by stripping whitespace to avoid collisions from "Foo " vs "Foo".
    existing = dict(cursor.execute("SELECT title, code FROM experiment_codes").fetchall())
    used = set(existing.values())

    # Normalize existing experiment_codes entries: if we have both "Foo" and "Foo ",
    # keep the trimmed version and update any experiments referencing the untrimmed one.
    titles_to_remove = []
    for title in existing:
        title_normalized = title.strip()
        if title != title_normalized and title_normalized in existing:
            # Merge: update experiments to use the normalized title, then remove the duplicate
            cursor.execute(
                "UPDATE experiments SET experiment_type = ? WHERE experiment_type = ?",
                (title_normalized, title)
            )
            titles_to_remove.append(title)
    for title in titles_to_remove:
        cursor.execute("DELETE FROM experiment_codes WHERE title = ?", (title,))
        del existing[title]

    titles = cursor.execute(
        "SELECT experiment_type, MIN(id) AS first_id FROM experiments "
        "WHERE experiment_type IS NOT NULL AND experiment_type <> '' "
        "GROUP BY TRIM(experiment_type) ORDER BY first_id"
    ).fetchall()
    for title, _ in titles:
        title_normalized = title.strip()
        if title_normalized in existing:
            continue
        code = derive_code(title_normalized, used)
        used.add(code)
        cursor.execute(
            "INSERT INTO experiment_codes (title, code) VALUES (?, ?)", (title_normalized, code)
        )
        existing[title_normalized] = code

    # Backfill a repetition for every session that lacks one, keeping any already
    # set. Order by id (insertion order ≈ chronological, since date is no longer
    # stored); fill the next free number within each title.
    by_title = {}
    for row in cursor.execute(
        "SELECT id, experiment_type, repetition FROM experiments "
        "WHERE experiment_type IS NOT NULL AND experiment_type <> '' "
        "ORDER BY id"
    ).fetchall():
        by_title.setdefault(row[1], []).append({"id": row[0], "rep": row[2]})
    for items in by_title.values():
        used_reps = {it["rep"] for it in items if it["rep"] is not None}
        next_rep = 1
        for it in items:
            if it["rep"] is not None:
                continue
            while next_rep in used_reps:
                next_rep += 1
            cursor.execute(
                "UPDATE experiments SET repetition = ? WHERE id = ?", (next_rep, it["id"])
            )
            used_reps.add(next_rep)
            next_rep += 1

    conn.commit()
    conn.close()


def hashing_options(scanner):
    """Pull content-hashing settings out of a ``[scanner]`` config dict.

    Returns ``(content_hash, hash_max_bytes)``. Hashing is opt-in
    (``content_hashing = true``) so that turning on a first, potentially
    expensive pass over a large raw corpus is always a deliberate choice.
    ``hash_max_bytes`` is an optional ceiling to keep that pass bounded.
    """
    scanner = scanner or {}
    return bool(scanner.get("content_hashing")), scanner.get("hash_max_bytes")


class SDGL:
    def __init__(self, root_path, eln_db_path=None, sdgl_db_path=None):
        self.root_path = Path(root_path)
        # Data-repo layout: experiments.db / sdgl.db live at the root, not under data/.
        self.eln_db_path = Path(eln_db_path) if eln_db_path else self.root_path / "experiments.db"
        self.sdgl_db_path = Path(sdgl_db_path) if sdgl_db_path else self.root_path / "sdgl.db"
        self.sdgl_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self):
        conn = sqlite3.connect(str(self.sdgl_db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        # WAL lets the read-heavy explorer endpoints run concurrently with the
        # background scanner's writes instead of being locked out; busy_timeout
        # makes the rare writer-vs-writer overlap wait briefly rather than fail
        # immediately with "database is locked".
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def initialize(self):
        if self.eln_db_path.exists():
            allocate_experiment_codes(self.eln_db_path)
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT,
                description TEXT,
                created_at TEXT,
                updated_at TEXT,
                experiment_id INTEGER,
                metadata TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS edges (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                created_at TEXT,
                metadata TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS file_locations (
                id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                root_name TEXT,
                path TEXT NOT NULL,
                role TEXT,
                qualifier TEXT,
                rel_path TEXT,
                size INTEGER,
                mtime REAL,
                is_dir INTEGER,
                first_seen_at TEXT,
                last_seen_at TEXT,
                exists_now INTEGER,
                metadata TEXT,
                content_hash TEXT,
                hashed_size INTEGER,
                hashed_mtime REAL,
                hashed_at TEXT
            )
            """
        )
        # Self-heal older sdgl.db files that predate the scan-by-ID and
        # content-hashing columns (layer 1).
        existing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(file_locations)")}
        for column, decl in (
            ("rel_path", "TEXT"),
            ("size", "INTEGER"),
            ("mtime", "REAL"),
            ("is_dir", "INTEGER"),
            ("content_hash", "TEXT"),
            ("hashed_size", "INTEGER"),
            ("hashed_mtime", "REAL"),
            ("hashed_at", "TEXT"),
        ):
            if column not in existing_cols:
                cursor.execute(f"ALTER TABLE file_locations ADD COLUMN {column} {decl}")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_findings (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                root_name TEXT,
                path TEXT NOT NULL,
                name TEXT,
                suggestion TEXT,
                first_seen_at TEXT,
                last_seen_at TEXT,
                exists_now INTEGER,
                metadata TEXT
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_locations_node ON file_locations(node_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_locations_path ON file_locations(path)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_locations_hash ON file_locations(content_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scan_findings_status ON scan_findings(status)")
        conn.commit()
        conn.close()

    def sync_eln(self):
        if not self.eln_db_path.exists():
            return
        allocate_experiment_codes(self.eln_db_path)
        eln = sqlite3.connect(str(self.eln_db_path))
        eln.row_factory = sqlite3.Row
        conn = self.connect()
        try:
            # Tags are the optional ELN classification reused by the SDGL graph.
            tags_by_experiment = {}
            if self._eln_table_exists(eln, "experiment_tags") and self._eln_table_exists(eln, "tags"):
                for tag_row in eln.execute(
                    """
                    SELECT et.experiment_id AS experiment_id, t.name AS name
                    FROM experiment_tags et
                    JOIN tags t ON t.id = et.tag_id
                    ORDER BY t.name
                    """
                ):
                    tags_by_experiment.setdefault(tag_row["experiment_id"], []).append(tag_row["name"])

            # Channels are the microscopy channel annotations (channel_label, target, modality).
            channels_by_experiment = {}
            if self._eln_table_exists(eln, "experiment_channels"):
                for ch_row in eln.execute(
                    """
                    SELECT experiment_id, channel_order, channel_label, target, modality
                    FROM experiment_channels
                    ORDER BY experiment_id, channel_order
                    """
                ):
                    channels_by_experiment.setdefault(ch_row["experiment_id"], []).append({
                        "channel_order": ch_row["channel_order"],
                        "channel_label": ch_row["channel_label"],
                        "target": ch_row["target"],
                        "modality": ch_row["modality"],
                    })

            code_by_title = dict(eln.execute("SELECT title, code FROM experiment_codes").fetchall())
            # experiment row id (int) -> CODE-NN; drives the protocol edges below.
            id_by_experiment = {}
            for row in eln.execute("SELECT * FROM experiments ORDER BY id"):
                title = row["experiment_type"] if "experiment_type" in row.keys() else None
                code = code_by_title.get(title)
                rep = row["repetition"] if "repetition" in row.keys() else None
                if not code or rep is None:
                    # Cannot form a CODE-NN id without both a code and repetition.
                    continue
                excluded = bool(row["excluded"]) if "excluded" in row.keys() else False
                exp_id = format_experiment_id(code, rep, excluded)
                id_by_experiment[row["id"]] = exp_id
                tags = tags_by_experiment.get(row["id"], [])
                channels = channels_by_experiment.get(row["id"], [])
                metadata = {
                    key: row[key]
                    for key in row.keys()
                    if key not in {"id", "experiment_uid", "created_at", "modified_at"}
                }
                metadata["code"] = code
                metadata["repetition"] = rep
                metadata["excluded"] = excluded
                metadata["experiment_id"] = exp_id
                metadata["tags"] = tags
                metadata["channels"] = channels
                self.upsert_node(
                    "experiment:" + exp_id,
                    "experiment",
                    title,
                    row["comments"] if "comments" in row.keys() else None,
                    row["id"],
                    metadata,
                    conn=conn,
                )

            if self._eln_table_exists(eln, "protocols"):
                for row in eln.execute("SELECT * FROM protocols ORDER BY id"):
                    title = row["name"]
                    if "version" in row.keys() and row["version"]:
                        title = f"{title} v{row['version']}"
                    self.upsert_node(
                        "protocol:" + str(row["id"]),
                        "protocol",
                        title,
                        row["description"] if "description" in row.keys() else None,
                        None,
                        {key: row[key] for key in row.keys() if key != "content"},
                        conn=conn,
                    )

            if self._eln_table_exists(eln, "experiment_protocols"):
                rows = eln.execute(
                    "SELECT experiment_id, protocol_id FROM experiment_protocols"
                ).fetchall()
                for row in rows:
                    exp_id = id_by_experiment.get(row["experiment_id"])
                    if not exp_id:
                        continue
                    self.upsert_edge(
                        "experiment:" + exp_id,
                        "protocol:" + str(row["protocol_id"]),
                        "uses_protocol",
                        {},
                        conn=conn,
                    )

            # Sync reports from markdown files
            if self._eln_table_exists(eln, "reports"):
                self._sync_reports(eln, conn, id_by_experiment)

            # Prune experiment nodes that no longer correspond to an ELN session
            # (e.g. after a code rename), so the graph mirrors the ELN exactly.
            current_ids = {"experiment:" + exp_id for exp_id in id_by_experiment.values()}
            stale_ids = [
                row["id"]
                for row in conn.execute("SELECT id FROM nodes WHERE type = 'experiment'")
                if row["id"] not in current_ids
            ]
            for stale_id in stale_ids:
                conn.execute("DELETE FROM edges WHERE source_id = ? OR target_id = ?", (stale_id, stale_id))
                conn.execute("DELETE FROM file_locations WHERE node_id = ?", (stale_id,))
                conn.execute("DELETE FROM nodes WHERE id = ?", (stale_id,))

            conn.commit()
        finally:
            conn.close()
            eln.close()

    def _sync_reports(self, eln, conn, id_by_experiment):
        """Scan reports/*.md files, populate the reports table, and create SDGL nodes/edges.

        Args:
            eln: ELN database connection.
            conn: SDGL database connection.
            id_by_experiment: Map from ELN experiment id (int) to CODE-NN string.
        """
        reports_dir = self.root_path / "reports"
        if not reports_dir.exists():
            return

        # Purge legacy series-level 'documents' edges. These were created by the
        # old date/free-text matching fallback (now removed); coverage is declared
        # explicitly via '**Series:** CODE' and linked as 'has_report' below.
        conn.execute("DELETE FROM edges WHERE relation_type = 'documents'")

        # Collect all report files
        report_files = sorted(
            p for p in reports_dir.glob("**/*.md")
            if not any(_is_hidden(part) for part in p.relative_to(reports_dir).parts)
        )

        # Track which reports exist for pruning
        seen_report_paths = set()

        for report_file in report_files:
            rel_path = str(report_file.relative_to(self.root_path))
            seen_report_paths.add(rel_path)

            # Extract title from markdown frontmatter or filename
            content = report_file.read_text(encoding="utf-8")
            title_match = re.match(r'^#\s+(.+)$', content, re.MULTILINE)
            title = title_match.group(1).strip() if title_match else report_file.stem.replace('_', ' ').replace('-', ' ').title()

            # Extract the declared series if present (e.g., "**Series:** NESFM").
            # This single declaration is the canonical coverage signal, shared with
            # the report-overview block in generate_reports.py.
            series_match = re.search(r'\*\*Series:\*\*\s*([A-Z]{5})', content)
            report_series = series_match.group(1) if series_match else None

            # Insert or update report in ELN
            eln.execute("""
                INSERT INTO reports (title, file_path, modified_at)
                VALUES (?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    title = excluded.title,
                    modified_at = excluded.modified_at
            """, (title, rel_path, utcnow()))

            report_id = eln.execute(
                "SELECT id FROM reports WHERE file_path = ?", (rel_path,)
            ).fetchone()["id"]

            # Create SDGL report node
            self.upsert_node(
                "report:" + str(report_id),
                "report",
                title,
                None,
                None,
                {"file_path": rel_path, "title": title, "series": report_series},
                conn=conn,
            )

            # Clear existing report-experiment edges for this report (will be recreated below)
            report_node_id = "report:" + str(report_id)
            conn.execute("DELETE FROM edges WHERE target_id = ? AND relation_type = 'has_report'", (report_node_id,))

            # Link the report to every active repetition of its declared series
            # (e.g. "NESFM" -> NESFM-01, NESFM-02, ...). id_by_experiment maps
            # ELN row id (int) -> CODE-NN string. Reports without a **Series:**
            # produce no experiment edges (correct for the Bluesky thread).
            if report_series:
                for eln_exp_id, exp_code in id_by_experiment.items():
                    # Active repetitions only (CODE-NN), excluding CODE-XNN, to
                    # match the active-only experiments table in the report block.
                    if exp_code.startswith(report_series + "-") and "-X" not in exp_code:
                        self.upsert_edge(
                            "experiment:" + exp_code,
                            report_node_id,
                            "has_report",
                            {},
                            conn=conn,
                        )

        # Prune reports that no longer exist
        for row in eln.execute("SELECT id, file_path FROM reports"):
            report_node_id = "report:" + str(row["id"])
            if row["file_path"] not in seen_report_paths:
                # Report file deleted - remove everything
                eln.execute("DELETE FROM experiment_reports WHERE report_id = ?", (row["id"],))
                eln.execute("DELETE FROM reports WHERE id = ?", (row["id"],))
                conn.execute("DELETE FROM edges WHERE source_id = ? OR target_id = ?",
                           (report_node_id, report_node_id))
                conn.execute("DELETE FROM nodes WHERE id = ?", (report_node_id,))

        eln.commit()

    @staticmethod
    def _eln_table_exists(conn, table_name):
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def upsert_node(self, node_id, node_type, title=None, description=None, experiment_id=None, metadata=None, conn=None):
        if node_type not in CORE_NODE_TYPES:
            raise ValueError("unsupported SDGL node type: " + node_type)
        owns_conn = conn is None
        conn = conn or self.connect()
        now = utcnow()
        try:
            existing = conn.execute("SELECT id FROM nodes WHERE id = ?", (node_id,)).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE nodes
                    SET type = ?, title = ?, description = ?, updated_at = ?,
                        experiment_id = ?, metadata = ?
                    WHERE id = ?
                    """,
                    (node_type, title, description, now, experiment_id, json_dumps(metadata), node_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO nodes (
                        id, type, title, description, created_at, updated_at,
                        experiment_id, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (node_id, node_type, title, description, now, now, experiment_id, json_dumps(metadata)),
                )
            if owns_conn:
                conn.commit()
        finally:
            if owns_conn:
                conn.close()

    def upsert_edge(self, source_id, target_id, relation_type, metadata=None, conn=None):
        if relation_type not in CORE_RELATION_TYPES:
            raise ValueError("unsupported SDGL relation type: " + relation_type)
        owns_conn = conn is None
        conn = conn or self.connect()
        edge_id = "edge:" + stable_hash(source_id, relation_type, target_id)
        now = utcnow()
        try:
            existing = conn.execute("SELECT id FROM edges WHERE id = ?", (edge_id,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE edges SET metadata = ? WHERE id = ?",
                    (json_dumps(metadata), edge_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO edges (
                        id, source_id, target_id, relation_type, created_at, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (edge_id, source_id, target_id, relation_type, now, json_dumps(metadata)),
                )
            if owns_conn:
                conn.commit()
        finally:
            if owns_conn:
                conn.close()
        return edge_id

    def upsert_location(self, node_id, root_name, path, role, qualifier="",
                        rel_path="", size=None, mtime=None, is_dir=0,
                        metadata=None, conn=None, hash_path=None,
                        hash_max_bytes=None):
        """Record a file sighting. When ``hash_path`` is given and the entry is a
        file, a SHA-256 content hash is stored (layer 1). The
        hash is recomputed only when the file is new or its size/mtime changed
        since it was last hashed, so re-scans of an unchanged corpus do no I/O.
        When ``hash_path`` is ``None`` any previously stored hash is preserved."""
        owns_conn = conn is None
        conn = conn or self.connect()
        location_id = "location:" + stable_hash(root_name or "", os.path.abspath(path))
        now = utcnow()
        try:
            existing = conn.execute(
                "SELECT content_hash, hashed_size, hashed_mtime, hashed_at "
                "FROM file_locations WHERE id = ?", (location_id,)
            ).fetchone()
            content_hash, hashed_size, hashed_mtime, hashed_at = (
                self._resolve_content_hash(
                    existing, hash_path if not is_dir else None,
                    size, mtime, hash_max_bytes, now)
            )
            if existing:
                conn.execute(
                    """
                    UPDATE file_locations
                    SET node_id = ?, role = ?, qualifier = ?, rel_path = ?,
                        size = ?, mtime = ?, is_dir = ?, last_seen_at = ?,
                        exists_now = 1, metadata = ?,
                        content_hash = ?, hashed_size = ?, hashed_mtime = ?,
                        hashed_at = ?
                    WHERE id = ?
                    """,
                    (node_id, role, qualifier, rel_path, size, mtime, is_dir,
                     now, json_dumps(metadata), content_hash, hashed_size,
                     hashed_mtime, hashed_at, location_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO file_locations (
                        id, node_id, root_name, path, role, qualifier,
                        rel_path, size, mtime, is_dir,
                        first_seen_at, last_seen_at, exists_now, metadata,
                        content_hash, hashed_size, hashed_mtime, hashed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                    """,
                    (location_id, node_id, root_name, os.path.abspath(path), role,
                     qualifier, rel_path, size, mtime, is_dir, now, now,
                     json_dumps(metadata), content_hash, hashed_size,
                     hashed_mtime, hashed_at),
                )
            if owns_conn:
                conn.commit()
        finally:
            if owns_conn:
                conn.close()
        return location_id

    @staticmethod
    def _resolve_content_hash(existing, hash_path, size, mtime, hash_max_bytes, now):
        """Return the ``(content_hash, hashed_size, hashed_mtime, hashed_at)``
        tuple to store. Reuses the existing hash when size+mtime are unchanged,
        recomputes when they drift, and carries the prior hash forward untouched
        when hashing is not requested for this sighting."""
        prior = (
            (existing["content_hash"], existing["hashed_size"],
             existing["hashed_mtime"], existing["hashed_at"])
            if existing else (None, None, None, None)
        )
        if not hash_path:
            return prior  # hashing disabled here — never erase a stored hash
        if prior[0] and prior[1] == size and prior[2] == mtime:
            return prior  # unchanged since last hashed — skip the re-read
        if hash_max_bytes is not None and size is not None and size > hash_max_bytes:
            return prior  # too large to hash under the configured cap
        try:
            digest = sha256_file(hash_path)
        except OSError:
            return prior  # unreadable (permissions, vanished mid-scan)
        return digest, size, mtime, now

    def upsert_finding(self, status, root_name, path, name=None, suggestion=None, metadata=None, exists_now=1, conn=None):
        owns_conn = conn is None
        conn = conn or self.connect()
        finding_id = "finding:" + stable_hash(status, root_name or "", os.path.abspath(path))
        now = utcnow()
        try:
            existing = conn.execute(
                "SELECT id FROM scan_findings WHERE id = ?", (finding_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE scan_findings
                    SET last_seen_at = ?, exists_now = ?, suggestion = ?, metadata = ?
                    WHERE id = ?
                    """,
                    (now, exists_now, suggestion, json_dumps(metadata), finding_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO scan_findings (
                        id, status, root_name, path, name, suggestion,
                        first_seen_at, last_seen_at, exists_now, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (finding_id, status, root_name, os.path.abspath(path), name, suggestion, now, now, exists_now, json_dumps(metadata)),
                )
            if owns_conn:
                conn.commit()
        finally:
            if owns_conn:
                conn.close()

    def scan_from_config(self, config_path=None):
        from eln.config import load_config

        config = load_config(config_path, root_override=str(self.root_path))
        content_hash, hash_max_bytes = hashing_options(config.scanner)
        return self.scan_roots(
            config.scan_roots, content_hash=content_hash,
            hash_max_bytes=hash_max_bytes,
        )

    def scan_roots(self, roots, list_paths=False, progress=None,
                   content_hash=False, hash_max_bytes=None):
        """Discover CODE-NN folders across the given roots and index their
        subtree metadata (names, sizes, mtimes — and, when ``content_hash`` is
        set, a SHA-256 per file for tamper-evidence and dedup).

        Args:
            roots: List of scan root configurations.
            list_paths: If True, return recognized paths in the summary.
            content_hash: If True, store/refresh a SHA-256 per file
                (layer 1). Recomputed only when size/mtime drift.
            hash_max_bytes: Optional ceiling; files larger than this are left
                unhashed (keeps a first pass over huge raw corpora bounded).
        """
        self.sync_eln()
        summary = {"recognized": 0, "unmatched": 0, "aggregates": 0,
                   "removed": 0, "duplicates": 0}
        if list_paths:
            summary["recognized_paths"] = []
        conn = self.connect()
        known = self._known_experiment_ids()
        title_by_code = self._experiment_titles_by_code()
        known_codes = {code for (code, _rep, _excluded) in known}
        seen_paths = set()
        present_root_names = []
        try:
            for root in roots:
                root_name = root.get("name") or Path(root.get("path", "")).name
                root_path = Path(root.get("path", ""))
                if not root_path.is_absolute():
                    root_path = self.root_path / root_path
                if progress:
                    progress({"phase": "root", "root": root_name, "path": str(root_path)})
                if not _root_is_observable(root_path):
                    continue
                present_root_names.append(root_name)
                for dirpath, dirnames, _filenames in os.walk(root_path):
                    # Prune in place so os.walk does not descend into hidden dirs.
                    dirnames[:] = sorted(d for d in dirnames if not _is_hidden(d))
                    matched = []
                    for dirname in list(dirnames):
                        parsed = parse_id_folder(dirname)
                        if not parsed:
                            agg = parse_code_folder(dirname)
                            if agg and agg["code"] in known_codes:
                                matched.append(dirname)
                                folder = Path(dirpath) / dirname
                                code = agg["code"]
                                node_id = "aggregate_analysis:" + code
                                self.upsert_node(
                                    node_id, "aggregate_analysis",
                                    title_by_code.get(code), None, None,
                                    {"code": code, "kind": "aggregate"}, conn=conn,
                                )
                                self._index_id_folder(
                                    node_id, root_name, folder, conn, seen_paths,
                                    content_hash, hash_max_bytes,
                                )
                                self.upsert_finding(
                                    "recognized", root_name, str(folder), name=dirname,
                                    metadata={"code": code, "kind": "aggregate"}, conn=conn,
                                )
                                summary["aggregates"] += 1
                                if list_paths:
                                    summary["recognized_paths"].append(str(folder))
                                conn.commit()
                            continue
                        matched.append(dirname)
                        folder = Path(dirpath) / dirname
                        exp_id = known.get((parsed["code"], parsed["rep"], parsed["excluded"]))
                        if exp_id:
                            self._index_id_folder(
                                "experiment:" + exp_id, root_name, folder, conn, seen_paths,
                                content_hash, hash_max_bytes,
                            )
                            self.upsert_finding(
                                "recognized", root_name, str(folder), name=dirname,
                                metadata={"experiment_id": exp_id}, conn=conn,
                            )
                            summary["recognized"] += 1
                            if list_paths:
                                summary["recognized_paths"].append(str(folder))
                        else:
                            self.upsert_finding(
                                "unmatched", root_name, str(folder), name=dirname,
                                suggestion="create or rename to match an experiment ID",
                                metadata={"code": parsed["code"], "rep": parsed["rep"]},
                                conn=conn,
                            )
                            summary["unmatched"] += 1
                        conn.commit()
                    dirnames[:] = [d for d in dirnames if d not in matched]

            # Remove file locations from scan roots that are no longer configured.
            # This prevents duplicates when a root is renamed (e.g., "gaia" -> "gaia-tirf").
            all_root_names = [r.get("name") or Path(r.get("path", "")).name for r in roots]
            stale_roots = conn.execute(
                "SELECT DISTINCT root_name FROM file_locations"
            ).fetchall()
            for (stale_root,) in stale_roots:
                if stale_root not in all_root_names:
                    # This root is no longer configured; remove its entries
                    conn.execute(
                        "DELETE FROM file_locations WHERE root_name = ?", (stale_root,)
                    )
                    summary["removed"] += 1
                    if list_paths:
                        print(f"  Removed stale root '{stale_root}'", file=sys.stderr)

            # The filesystem of a root we could actually walk is the source of
            # truth: drop any previously-indexed path under it that we didn't see
            # this time and that no longer exists on disk (renamed, moved, or
            # deleted). We never retain stale "missing" rows.
            for root_name in present_root_names:
                rows = conn.execute(
                    "SELECT id, path FROM file_locations WHERE root_name = ?",
                    (root_name,),
                ).fetchall()
                for row in rows:
                    # A previously-recorded hidden path is now excluded by policy,
                    # so drop it even if it still exists on disk (e.g. .Trash-1000).
                    hidden = any(_is_hidden(part) for part in Path(row["path"]).parts)
                    if hidden or (
                        os.path.abspath(row["path"]) not in seen_paths
                        and not Path(row["path"]).exists()
                    ):
                        conn.execute(
                            "DELETE FROM file_locations WHERE id = ?",
                            (row["id"],),
                        )
                        summary["removed"] += 1

            # Duplicates are resolved at read/assembly time; here we only count the
            # extra copies sighted at the same (experiment, relative path).
            duplicate_rows = conn.execute(
                """
                SELECT COUNT(*) - COUNT(DISTINCT node_id || '\n' || COALESCE(rel_path, ''))
                       AS extra
                FROM file_locations
                WHERE exists_now = 1
                """
            ).fetchone()
            summary["duplicates"] = (duplicate_rows["extra"] if duplicate_rows else 0) or 0

            conn.commit()

            # Materialize derived start_date into experiment_metadata so the dates
            # ride inside experiments.sql and the generators never need sdgl.db.
            if self.eln_db_path.exists():
                eln = sqlite3.connect(str(self.eln_db_path))
                eln.row_factory = sqlite3.Row
                try:
                    self._materialize_experiment_dates(eln, conn)
                finally:
                    eln.close()
        finally:
            conn.close()
        # A scan rebuilds the scanned graph; replay committed provenance (dataset
        # nodes + generates/derived_from edges) so stamps survive the rebuild.
        from eln.sdgl.provenance_store import load_provenance
        load_provenance(self)
        if progress:
            progress({"phase": "done", "summary": summary})
        return summary

    def _materialize_experiment_dates(self, eln, conn):
        """Write experiment_metadata.start_date (earliest raw-file mtime, as
        YYYY-MM-DD) for every experiment, and clear it for those with no raw
        files. This is still 'derive from files' — just cached into the curated
        DB so the date is portable and versioned inside experiments.sql."""
        code_by_title = dict(eln.execute("SELECT title, code FROM experiment_codes").fetchall())
        for row in eln.execute(
            "SELECT id, experiment_type, repetition, excluded FROM experiments"
        ).fetchall():
            code = code_by_title.get(row["experiment_type"])
            rep = row["repetition"]
            if not code or rep is None:
                continue
            exp_id = format_experiment_id(code, rep, bool(row["excluded"]))
            oldest = self._oldest_mtime(conn, "experiment:" + exp_id)
            if oldest:
                value = datetime.fromtimestamp(oldest).strftime("%Y-%m-%d")
                eln.execute(
                    "INSERT INTO experiment_metadata (experiment_id, key, value) "
                    "VALUES (?, 'start_date', ?) "
                    "ON CONFLICT(experiment_id, key) DO UPDATE SET value = excluded.value",
                    (row["id"], value),
                )
            else:
                eln.execute(
                    "DELETE FROM experiment_metadata WHERE experiment_id = ? AND key = 'start_date'",
                    (row["id"],),
                )
        eln.commit()

    def _known_experiment_ids(self):
        """Map (code, repetition, excluded) -> CODE-NN for every ELN session, for
        matching. Active and excluded reps are distinct keys so COV2D-01 and
        COV2D-X01 never collide."""
        result = {}
        if not self.eln_db_path.exists():
            return result
        eln = sqlite3.connect(str(self.eln_db_path))
        eln.row_factory = sqlite3.Row
        try:
            if not self._eln_table_exists(eln, "experiment_codes"):
                return result
            code_by_title = dict(eln.execute("SELECT title, code FROM experiment_codes").fetchall())
            for row in eln.execute("SELECT experiment_type, repetition, excluded FROM experiments"):
                code = code_by_title.get(row["experiment_type"])
                rep = row["repetition"]
                if code and rep is not None:
                    excluded = bool(row["excluded"])
                    result[(code, int(rep), excluded)] = format_experiment_id(code, rep, excluded)
        finally:
            eln.close()
        return result

    def _experiment_titles_by_code(self):
        """Map experiment code -> title (experiment_type) from the ELN, used to
        title the aggregate_analysis node created for a bare-code folder."""
        result = {}
        if not self.eln_db_path.exists():
            return result
        eln = sqlite3.connect(str(self.eln_db_path))
        try:
            if not self._eln_table_exists(eln, "experiment_codes"):
                return result
            for title, code in eln.execute("SELECT title, code FROM experiment_codes"):
                if code:
                    result[code] = title
        finally:
            eln.close()
        return result

    @staticmethod
    def _safe_stat(path):
        try:
            return path.stat()
        except OSError:
            return None

    @staticmethod
    def _in_raw(rel_path):
        """True when any path component is a `raw` subtree (merged silently)."""
        return "raw" in Path(rel_path).parts if rel_path else False

    def verify_hashes(self, node_id=None):
        """Recompute the SHA-256 of every hashed file location and compare it to
        the stored hash — the tamper-evidence half of content hashing (layer 1).

        Returns ``{"checked", "ok", "mismatch": [...], "missing": [...]}``. A
        *mismatch* means a file's contents diverged from the witnessed hash
        (corruption or tampering); *missing* means the file is gone or
        unreadable. Pass ``node_id`` to scope the check to one node.
        """
        conn = self.connect()
        result = {"checked": 0, "ok": 0, "mismatch": [], "missing": []}
        query = (
            "SELECT node_id, path, rel_path, content_hash FROM file_locations "
            "WHERE content_hash IS NOT NULL"
        )
        params = ()
        if node_id:
            query += " AND node_id = ?"
            params = (node_id,)
        try:
            for row in conn.execute(query, params).fetchall():
                result["checked"] += 1
                entry = {"node_id": row["node_id"], "path": row["path"],
                         "rel_path": row["rel_path"]}
                if not os.path.exists(row["path"]):
                    result["missing"].append(entry)
                    continue
                try:
                    actual = sha256_file(row["path"])
                except OSError:
                    result["missing"].append(entry)
                    continue
                if actual == row["content_hash"]:
                    result["ok"] += 1
                else:
                    result["mismatch"].append(
                        {**entry, "stored": row["content_hash"], "actual": actual})
        finally:
            conn.close()
        return result

    def _index_id_folder(self, node_id, root_name, folder, conn, seen_paths,
                         content_hash=False, hash_max_bytes=None):
        """Record the matched folder and every descendant as a file_location.
        Metadata only — names, extensions, sizes, mtimes — plus, when
        ``content_hash`` is set, a SHA-256 of each file's contents."""
        folder = Path(folder)
        base_stat = self._safe_stat(folder)
        seen_paths.add(os.path.abspath(str(folder)))
        self.upsert_location(
            node_id, root_name, str(folder), role="id_folder", rel_path="",
            size=None, mtime=(base_stat.st_mtime if base_stat else None), is_dir=1,
            metadata={"name": folder.name}, conn=conn,
        )
        for dirpath, dirnames, filenames in os.walk(folder):
            # Prune in place so os.walk does not descend into hidden dirs; also
            # drop hidden files so they are never recorded as locations.
            dirnames[:] = sorted(d for d in dirnames if not _is_hidden(d))
            filenames = sorted(f for f in filenames if not _is_hidden(f))
            for name in dirnames + filenames:
                entry = Path(dirpath) / name
                is_dir = entry.is_dir()
                rel = os.path.relpath(str(entry), str(folder))
                stat = self._safe_stat(entry)
                seen_paths.add(os.path.abspath(str(entry)))
                self.upsert_location(
                    node_id, root_name, str(entry),
                    role=("dir" if is_dir else "file"),
                    qualifier=("raw" if self._in_raw(rel) else ""),
                    rel_path=rel,
                    size=(stat.st_size if stat and not is_dir else None),
                    mtime=(stat.st_mtime if stat else None),
                    is_dir=1 if is_dir else 0,
                    metadata={"name": name, "ext": entry.suffix.lower().lstrip(".")},
                    conn=conn,
                    hash_path=(str(entry) if content_hash and not is_dir else None),
                    hash_max_bytes=hash_max_bytes,
                )

    def get_node(self, node_id):
        self.sync_eln()
        conn = self.connect()
        try:
            row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
            if not row:
                return None
            node = self._row_to_dict(row)
            node["locations"] = [
                self._row_to_dict(location)
                for location in conn.execute(
                    "SELECT * FROM file_locations WHERE node_id = ? ORDER BY exists_now DESC, path",
                    (node_id,),
                )
            ]
            node["incoming"] = [
                self._row_to_dict(edge)
                for edge in conn.execute(
                    "SELECT * FROM edges WHERE target_id = ? ORDER BY relation_type, source_id",
                    (node_id,),
                )
            ]
            node["outgoing"] = [
                self._row_to_dict(edge)
                for edge in conn.execute(
                    "SELECT * FROM edges WHERE source_id = ? ORDER BY relation_type, target_id",
                    (node_id,),
                )
            ]
            return node
        finally:
            conn.close()

    def get_location(self, location_id):
        conn = self.connect()
        try:
            row = conn.execute("SELECT * FROM file_locations WHERE id = ?", (location_id,)).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def list_findings(self, status=None):
        conn = self.connect()
        try:
            if status:
                rows = conn.execute(
                    "SELECT * FROM scan_findings WHERE status = ? ORDER BY exists_now DESC, path",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM scan_findings ORDER BY status, exists_now DESC, path"
                ).fetchall()
            return [self._row_to_dict(row) for row in rows]
        finally:
            conn.close()

    # ---- File-explorer tree -------------------------------------------------

    def tree(self):
        """Assemble the three-level explorer payload: experiment (title group) ->
        repetitions -> deduped filesystem tree + explicitly-linked entities.

        All qualifiers (tags, channels, microscope, cell_types, etc.) are stored
        at the repetition level since they can vary between repetitions.
        """
        self.sync_eln()
        conn = self.connect()
        try:
            exp_nodes = [
                self._row_to_dict(row)
                for row in conn.execute("SELECT * FROM nodes WHERE type = 'experiment'")
            ]
            groups = {}
            for node in exp_nodes:
                metadata = node.get("metadata") or {}
                code = metadata.get("code") or ""
                title = node.get("title") or ""
                key = code or title
                group = groups.setdefault(
                    key, {"code": code, "title": title, "repetitions": []}
                )
                # All qualifiers live at the repetition level since they can vary.
                files = self._assemble_files(conn, node["id"])
                # Date is derived from the earliest raw-file mtime (the experiment
                # start), not stored on the experiment.
                oldest_mtime = self._oldest_mtime(conn, node["id"])
                derived_date = (
                    datetime.fromtimestamp(oldest_mtime).strftime("%Y-%m-%d")
                    if oldest_mtime else None
                )
                group["repetitions"].append({
                    "id": metadata.get("experiment_id") or node["id"].split(":", 1)[-1],
                    "node_id": node["id"],
                    "repetition": metadata.get("repetition"),
                    "excluded": bool(metadata.get("excluded")),
                    "date": derived_date,
                    "oldest_mtime": oldest_mtime,
                    "files": files,
                    "links": self._linked_entities(conn, node["id"]),
                    "artifacts": self._stamped_artifacts(conn, node["id"]),
                    # Qualifiers (can vary per repetition):
                    "tags": metadata.get("tags") or [],
                    "channels": metadata.get("channels") or [],
                    "cell_types": metadata.get("cell_types"),
                    "microscope": metadata.get("microscope"),
                    "live_or_fixed": metadata.get("live_or_fixed"),
                    "comments": metadata.get("comments"),
                })

            experiments = []
            for group in groups.values():
                # Tags for the group are the union of all repetition tags (for filtering/search).
                all_tags = set()
                for rep in group["repetitions"]:
                    all_tags.update(rep.get("tags") or [])
                group["tags"] = sorted(all_tags)
                # Excluded reps sort after the active ones within a group.
                group["repetitions"].sort(
                    key=lambda rep: (
                        rep["excluded"], rep["repetition"] is None, rep["repetition"] or 0
                    )
                )
                group["repetition_count"] = len(group["repetitions"])
                group["aggregate"] = self._aggregate_for_code(conn, group["code"])
                # A progress report declares a '**Series:** CODE' and is linked
                # to every active repetition; surface it once at the series
                # (parent) level rather than as an artifact under each position.
                # Non-report links stay on their repetition.
                series_reports = {}
                for rep in group["repetitions"]:
                    kept = []
                    for link in rep["links"]:
                        if link["type"] == "report":
                            series_reports.setdefault(link["node_id"], link)
                        else:
                            kept.append(link)
                    rep["links"] = kept
                group["reports"] = sorted(
                    series_reports.values(),
                    key=lambda link: (link.get("title") or link["node_id"]).lower(),
                )
                experiments.append(group)
            experiments.sort(key=lambda group: (group["title"] or "").lower())
            return {"experiments": experiments}
        finally:
            conn.close()

    def _aggregate_for_code(self, conn, code):
        """Full-experiment aggregate folder for a code, if one was scanned.
        Returns the assembled file tree under aggregate_analysis:<code>, or None."""
        if not code:
            return None
        node_id = "aggregate_analysis:" + code
        node = conn.execute("SELECT id FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not node:
            return None
        files = self._assemble_files(conn, node_id)
        if not files:
            return None
        return {
            "node_id": node_id,
            "oldest_mtime": self._oldest_mtime(conn, node_id),
            "files": files,
            "links": self._linked_entities(conn, node_id),
        }

    def _oldest_mtime(self, conn, node_id):
        # Only raw acquisition files (qualifier='raw') count toward the experiment
        # date; processed/derived outputs have later mtimes and would skew it.
        row = conn.execute(
            "SELECT MIN(mtime) AS oldest FROM file_locations "
            "WHERE node_id = ? AND mtime IS NOT NULL AND qualifier = 'raw'",
            (node_id,),
        ).fetchone()
        return row["oldest"] if row else None

    def _linked_entities(self, conn, node_id):
        """Explicitly-linked protocols/reports/presentations for the detail pane.

        Stamped artifacts (``generates`` edges to ``dataset`` nodes) are excluded
        here — they are surfaced separately by :meth:`_stamped_artifacts` so the
        explorer can render them distinctly with their provenance recipe."""
        entities = []
        for edge in conn.execute(
            "SELECT * FROM edges WHERE source_id = ? OR target_id = ?", (node_id, node_id)
        ):
            if edge["relation_type"] == "generates":
                continue
            other = edge["target_id"] if edge["source_id"] == node_id else edge["source_id"]
            if other.startswith("experiment:"):
                continue
            other_node = conn.execute(
                "SELECT type, title FROM nodes WHERE id = ?", (other,)
            ).fetchone()
            if not other_node:
                continue
            entities.append({
                "node_id": other,
                "type": other_node["type"],
                "title": other_node["title"],
                "relation": edge["relation_type"],
            })
        entities.sort(key=lambda item: (item["type"], item["title"] or item["node_id"]))
        return entities

    def _stamped_artifacts(self, conn, node_id):
        """Artifacts this experiment produced, from outgoing ``generates`` edges.

        Each item carries the ``dataset`` node and the full recipe recorded on the
        edge (kind, library/function/params/inputs or tool/method, stamped_at), so
        the explorer renders committed artifacts distinctly from raw scanned files
        and can show their provenance in the detail pane."""
        artifacts = []
        for edge in conn.execute(
            "SELECT target_id, metadata FROM edges "
            "WHERE source_id = ? AND relation_type = 'generates'", (node_id,)
        ):
            target = edge["target_id"]
            node = conn.execute(
                "SELECT title, metadata FROM nodes WHERE id = ?", (target,)
            ).fetchone()
            node_meta = json_loads(node["metadata"]) if node else {}
            record = json_loads(edge["metadata"])
            rel_path = node_meta.get("rel_path") or record.get("path")
            artifacts.append({
                "node_id": target,
                "name": (node["title"] if node else None)
                        or (rel_path or target).rsplit("/", 1)[-1],
                "rel_path": rel_path,
                "kind": node_meta.get("kind") or record.get("kind"),
                "record": record,
            })
        artifacts.sort(key=lambda item: item["rel_path"] or item["node_id"])
        return artifacts

    def _assemble_files(self, conn, node_id):
        """Dedup file_locations by relative path (newest mtime wins; size-differing
        older copies flagged stale, raw/ exempt) and nest into a folder tree."""
        rows = [
            self._row_to_dict(row)
            for row in conn.execute(
                "SELECT * FROM file_locations WHERE node_id = ? ORDER BY rel_path", (node_id,)
            )
        ]
        by_rel = {}
        for row in rows:
            rel = row.get("rel_path")
            if not rel:  # "" is the matched id folder itself (the tree root)
                continue
            by_rel.setdefault(rel, []).append(row)

        entries = {}
        for rel, copies in by_rel.items():
            ordered = sorted(copies, key=lambda c: (c.get("mtime") or 0), reverse=True)
            primary = ordered[0]
            is_dir = bool(primary.get("is_dir"))
            in_raw = self._in_raw(rel)
            sizes = {c.get("size") for c in copies if not c.get("is_dir")}
            stale_ids = set()
            if not is_dir and not in_raw and len(sizes) > 1:
                for copy in ordered[1:]:
                    if copy.get("size") != primary.get("size"):
                        stale_ids.add(copy.get("id"))
            entries[rel] = {
                "rel_path": rel,
                "name": (primary.get("metadata") or {}).get("name") or Path(rel).name,
                "is_dir": is_dir,
                "size": primary.get("size"),
                "mtime": primary.get("mtime"),
                "ext": (primary.get("metadata") or {}).get("ext", ""),
                "in_raw": in_raw,
                "exists_now": any(c.get("exists_now") for c in copies),
                "stale_count": len(stale_ids),
                "locations": [
                    {
                        "id": c.get("id"),
                        "root_name": c.get("root_name"),
                        "path": c.get("path"),
                        "size": c.get("size"),
                        "mtime": c.get("mtime"),
                        "exists_now": c.get("exists_now"),
                        "stale": c.get("id") in stale_ids,
                    }
                    for c in ordered
                ],
                "children": {},
            }

        # Nest entries into a tree, materialising any intermediate dirs not
        # explicitly recorded (shallowest paths first so parents exist).
        root = {"children": {}}
        for rel in sorted(entries, key=lambda r: r.count(os.sep)):
            parts = Path(rel).parts
            cursor = root
            for index, part in enumerate(parts):
                partial = os.sep.join(parts[: index + 1])
                children = cursor["children"]
                if part not in children:
                    children[part] = entries.get(partial) or {
                        "rel_path": partial, "name": part, "is_dir": True,
                        "size": None, "mtime": None, "ext": "", "in_raw": self._in_raw(partial),
                        "exists_now": True, "stale_count": 0, "locations": [], "children": {},
                    }
                cursor = children[part]

        def to_list(node):
            kids = list(node.get("children", {}).values())
            kids.sort(key=lambda c: (not c.get("is_dir"), (c.get("name") or "").lower()))
            node["children"] = [to_list(child) for child in kids]
            return node

        top = sorted(
            root["children"].values(),
            key=lambda c: (not c.get("is_dir"), (c.get("name") or "").lower()),
        )
        return [to_list(child) for child in top]

    @staticmethod
    def _row_to_dict(row):
        result = dict(row)
        if "metadata" in result:
            result["metadata"] = json_loads(result["metadata"])
            # Surface tags as a top-level array so clients need not parse metadata.
            if isinstance(result["metadata"], dict) and "tags" in result["metadata"]:
                result["tags"] = result["metadata"]["tags"]
        return result


def update_labbook(root_path=None, verbose=True, list_paths=False):
    """Run an SDGL scan and print progress feedback.

    This is the CLI entry point for scanning filesystem roots and updating
    the SDGL database with recognized experiment folders.

    Args:
        root_path: Data-repo root (holds experiments.db); scan roots come from
            the unified labbook.toml.
                   If None, uses the current working directory.
        verbose: If True, print progress information (items found, updated, errors).
        list_paths: If True, print all recognized experiment folder paths.

    Returns:
        dict: Scan summary with counts of recognized, unmatched, aggregates, etc.
    """
    from eln.config import load_config

    root = Path(root_path) if root_path else Path.cwd()
    service = SDGL(root)
    config = load_config(root_override=str(root))
    roots = config.scan_roots

    if not roots:
        print("No scan roots configured in labbook.toml", file=sys.stderr)
        return {"error": "No scan roots configured"}

    if verbose:
        print(f"Starting SDGL scan of {len(roots)} root(s)...", file=sys.stderr)

    result = service.scan_roots(roots, list_paths=list_paths)

    if verbose:
        print(f"Scan complete:", file=sys.stderr)
        print(f"  Recognized: {result.get('recognized', 0)}", file=sys.stderr)
        print(f"  Unmatched:  {result.get('unmatched', 0)}", file=sys.stderr)
        print(f"  Aggregates: {result.get('aggregates', 0)}", file=sys.stderr)
        print(f"  Removed:    {result.get('removed', 0)}", file=sys.stderr)
        print(f"  Duplicates: {result.get('duplicates', 0)}", file=sys.stderr)

    if list_paths and "recognized_paths" in result:
        print(f"\nRecognized paths:", file=sys.stderr)
        for path in sorted(result["recognized_paths"]):
            print(f"  {path}", file=sys.stderr)

    return result


if __name__ == "__main__":
    update_labbook(list_paths="--list" in sys.argv)
