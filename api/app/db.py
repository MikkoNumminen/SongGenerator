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

-- Who may use this edge, as a table rather than an environment variable.
--
-- It was SONGGEN_ALLOWED_EMAILS, read once at startup, so granting somebody
-- access meant editing a file on the desktop and restarting the service. That
-- is fine for a list that never changes and useless for one the owner is meant
-- to manage from a browser.
--
-- The environment variable still seeds this table the first time, so an
-- existing machine keeps working with no manual step, and it stays the way an
-- edge with an empty database lets its owner in at all.
--
-- Admins are NOT in here. They come from the environment and are always
-- allowed, because a panel whose whole job is editing this table must not be
-- able to lock its owner out of itself.
CREATE TABLE IF NOT EXISTS allowed_emails (
    email     TEXT PRIMARY KEY,
    added_at  TEXT NOT NULL,
    added_by  TEXT NOT NULL,
    -- Which libraries this address may see, comma separated. 'demo' is the
    -- one everybody starts with; the rest are bank names off this machine.
    banks     TEXT NOT NULL DEFAULT 'demo',
    -- Whether this address sees every run or only its own. Off by default:
    -- a run names a song somebody chose to make.
    see_all_runs INTEGER NOT NULL DEFAULT 0
);

-- A one-time way in, handed out as a link.
--
-- The token is the secret, so it is the key: knowing it is the whole of the
-- claim. Single use is enforced by the update that spends it, which only
-- matches a row that has not been spent, so two people opening the same link
-- at the same moment cannot both be let in.
CREATE TABLE IF NOT EXISTS invitations (
    token      TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at    TEXT,
    used_by    TEXT
);

-- Small facts about this database rather than about a job.
--
-- It exists for one of them: whether the allowlist has ever been seeded from
-- the environment. "Seed when the table is empty" is not the same question,
-- and the difference is a bug: revoke the last remaining address and the table
-- is empty again, so the next restart seeds it and the revocation undoes
-- itself. Asking whether it has happened before answers it once and for good.
CREATE TABLE IF NOT EXISTS meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
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
    _add_missing_columns(conn)


# Columns added after the first version of a table shipped. CREATE TABLE IF NOT
# EXISTS does nothing to a table that already exists, so a database written
# before a column existed never gains it, and the first query naming it fails
# on the owner's machine and nowhere else.
_LATER_COLUMNS = (
    ("allowed_emails", "banks", "TEXT NOT NULL DEFAULT 'demo'", "*"),
    # No backfill: runs became somebody's own business at the same time this
    # column arrived, so there is no earlier state to preserve. Off is what
    # everybody had a moment ago.
    ("allowed_emails", "see_all_runs", "INTEGER NOT NULL DEFAULT 0", None),
)


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    for table, column, decl, backfill in _LATER_COLUMNS:
        have = {str(r["name"]) for r in
                conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if not have:            # the table itself is not there yet
            continue
        if column not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            if backfill is not None:
                # Only the rows that existed before the column did. They were
                # granted when there was nothing to choose between, so they
                # had everything, and a migration that narrowed them would
                # revoke access nobody asked to revoke.
                conn.execute(f"UPDATE {table} SET {column} = ?", (backfill,))
