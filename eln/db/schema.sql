-- Canonical schema for experiments.db — the source of truth.
--
-- A fresh database is created from THIS file by init_db.py. The diffable
-- experiments.sql dump (dump_db.py) carries this schema plus data; rebuild_db.py
-- reconstructs the binary from that dump. Keep this file authoritative; schema
-- changes are migrations layered on top.
--
-- This reflects the live schema after the migrations that (a) removed the dead
-- name/description/Date fields from experiments, (b) added repetition/excluded,
-- and (c) introduced experiment_codes (title<->code sync), reports, and the
-- experiment_reports junction.

-- ---------------------------------------------------------------------------
-- Base tables (no foreign keys)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS protocols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    description TEXT,
    content TEXT,
    file_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_latest BOOLEAN DEFAULT 1,
    UNIQUE(name, version)
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    file_path TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

-- An experiment repetition. Identity is the experiment_uid (e.g. AA01) plus
-- repetition; name/description were removed as dead fields.
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_type TEXT,
    cell_types TEXT,
    microscope TEXT,
    live_or_fixed TEXT,
    comments TEXT,
    file_path TEXT NOT NULL,
    thumbnail_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    experiment_uid TEXT,
    repetition INTEGER,
    excluded INTEGER DEFAULT 0
);

-- Title <-> code mapping backing title<->ID synchronization.
CREATE TABLE IF NOT EXISTS experiment_codes (
    title TEXT PRIMARY KEY,
    code  TEXT NOT NULL UNIQUE
);

-- ---------------------------------------------------------------------------
-- Dependent tables (foreign keys into the above)
-- ---------------------------------------------------------------------------

-- Flexible key-value metadata. The experiment date is NOT stored here: it is
-- always derived live from the earliest raw-file mtime. (A legacy 'start_date'
-- key was materialized here; the SDGL scan now scrubs it.)
CREATE TABLE IF NOT EXISTS experiment_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE,
    UNIQUE(experiment_id, key)
);

CREATE TABLE IF NOT EXISTS experiment_tags (
    experiment_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (experiment_id, tag_id),
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS experiment_protocols (
    experiment_id INTEGER NOT NULL,
    protocol_id INTEGER NOT NULL,
    PRIMARY KEY (experiment_id, protocol_id),
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE,
    FOREIGN KEY (protocol_id) REFERENCES protocols(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS experiment_reports (
    experiment_id INTEGER NOT NULL,
    report_id INTEGER NOT NULL,
    PRIMARY KEY (experiment_id, report_id),
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE,
    FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS experiment_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL,
    channel_order INTEGER,
    channel_label TEXT,
    target TEXT,
    modality TEXT,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_experiment_type ON experiments(experiment_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_experiments_experiment_uid ON experiments(experiment_uid);
CREATE INDEX IF NOT EXISTS idx_metadata_key ON experiment_metadata(key);
CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);
CREATE INDEX IF NOT EXISTS idx_protocol_name ON protocols(name);
CREATE INDEX IF NOT EXISTS idx_protocol_latest ON protocols(is_latest);
CREATE INDEX IF NOT EXISTS idx_experiment_protocols_exp ON experiment_protocols(experiment_id);
CREATE INDEX IF NOT EXISTS idx_experiment_protocols_proto ON experiment_protocols(protocol_id);
CREATE INDEX IF NOT EXISTS idx_experiment_channels_exp ON experiment_channels(experiment_id);
