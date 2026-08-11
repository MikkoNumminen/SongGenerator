"""Jobs, saved so history survives a restart.

The runner holds the job that is going right now; this holds every job that
ever went. They are separate because the runner is about a process and this is
about a record, and because a desktop front end would want the history without
wanting to own a subprocess.

Writes are upserts keyed on the job id, so the runner can call `save` on every
change without the caller tracking whether a row exists yet.

One deliberate gap: a job left `running` by a power cut is not repaired on
startup. It is recorded here rather than fixed silently, because the honest
repair needs to know whether the render actually finished, and the only witness
to that is the output directory. `reconcile` does that check when the edge
starts, and marks the rest as interrupted rather than guessing.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, fields
from pathlib import Path

from .jobs import Job
from .stages import Stage

_COLUMNS = (
    "id", "created_at", "started_at", "finished_at", "requested_by",
    "source_url", "song", "bank", "level", "mimicry", "engine", "arrangement",
    "stage", "percent", "detail", "exit_code", "error", "output_dir",
)


def _to_row(job: Job) -> dict[str, object]:
    data = asdict(job)
    data["stage"] = job.stage.value
    return {c: data.get(c) for c in _COLUMNS}


def _from_row(row: sqlite3.Row) -> Job:
    known = {f.name for f in fields(Job)}
    # .keys() is not redundant here: sqlite3.Row is a sequence, so `k in row`
    # tests the values rather than the column names.
    data: dict[str, object] = {k: row[k] for k in row.keys() if k in known}  # noqa: SIM118
    data["stage"] = Stage(row["stage"])
    return Job(**data)  # type: ignore[arg-type]


class JobStore:
    """Every run this machine has been asked for."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def connection(self) -> sqlite3.Connection:
        """The open database, for the other tables in the same file.

        Exposed rather than opened twice: SQLite allows one writer, and a
        second connection to the same file would be a second writer waiting on
        the first for no reason. The schema for every table is applied
        together in db.apply_schema.
        """
        return self._conn

    def save(self, job: Job) -> None:
        row = _to_row(job)
        columns = ", ".join(_COLUMNS)
        placeholders = ", ".join(f":{c}" for c in _COLUMNS)
        updates = ", ".join(f"{c}=excluded.{c}" for c in _COLUMNS if c != "id")
        self._conn.execute(
            f"INSERT INTO jobs ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}",
            row,
        )

    def get(self, job_id: str) -> Job | None:
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _from_row(row) if row else None

    def recent(self, limit: int = 50) -> list[Job]:
        """Newest first. The history table's only query."""
        rows = self._conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,)).fetchall()
        return [_from_row(r) for r in rows]

    def unsettled(self) -> list[Job]:
        finished = (Stage.DONE.value, Stage.REFUSED.value, Stage.FAILED.value)
        rows = self._conn.execute(
            f"SELECT * FROM jobs WHERE stage NOT IN ({','.join('?' * len(finished))})",
            finished).fetchall()
        return [_from_row(r) for r in rows]

    def reconcile(self, now: str) -> int:
        """Settle jobs that were running when the process died.

        Called at startup. Nothing was watching them, so their real outcome is
        unknowable from here; they are marked failed and say why, rather than
        sitting in the history as permanently running. Returns how many.
        """
        stranded = self.unsettled()
        for job in stranded:
            self._conn.execute(
                "UPDATE jobs SET stage = ?, error = ?, finished_at = ? WHERE id = ?",
                (Stage.FAILED.value,
                 "the edge stopped while this was running, so how it ended is unknown",
                 now, job.id),
            )
        return len(stranded)


def open_store(path: Path) -> JobStore:
    """A store on the given database file, schema applied."""
    from .db import apply_schema, connect

    conn = connect(path)
    apply_schema(conn)
    return JobStore(conn)
