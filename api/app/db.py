"""SQLite storage for job state and history.

PostgreSQL is the target stack's database and would be the better answer for
anything shared. Nothing here is shared: the edge runs on one machine, beside
the audio it describes, and a hosted Postgres costs money that this project
does not spend. SQLite is the cost decision, recorded here and in the README
rather than dressed up as the ideal.

What that costs, honestly: one writer at a time, no network access, and a
schema migration story of "the table is small enough to rebuild". What it buys
is a file that lives beside `work/`, is already gitignored there, and needs no
service running to read.

The schema is small on purpose. A run's audio is on disk and the pipeline owns
it; this table records what was asked for and how it went, and points at the
directory. Copying the results in would give two sources of truth for the same
files.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    created_at    TEXT    NOT NULL,
    started_at    TEXT,
    finished_at   TEXT,
    requested_by  TEXT    NOT NULL,

    source_url    TEXT    NOT NULL,
    song          TEXT,
    bank          TEXT    NOT NULL,
    level         TEXT,
    mimicry       REAL,
    engine        TEXT,
    arrangement   TEXT,

    stage         TEXT    NOT NULL,
    percent       INTEGER,
    detail        TEXT,
    exit_code     INTEGER,
    error         TEXT,
    output_dir    TEXT
);

CREATE INDEX IF NOT EXISTS jobs_created_at ON jobs (created_at DESC);
"""


def connect(path: Path) -> sqlite3.Connection:
    """Open the database, creating the file and its parent if needed.

    WAL so a reader listing history is never blocked by the run writing its
    progress, which happens every couple of seconds while a job is going.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    """Idempotent. Called at startup rather than shipped as a migration step."""
    conn.executescript(SCHEMA)
