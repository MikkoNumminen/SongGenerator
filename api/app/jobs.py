"""Starting a run, watching it, stopping it, and remembering it happened.

Transport-free on purpose. A web request handler and a desktop window both want
exactly this, and logic written into a request handler has to be written again
for the next front end.

The runner shells out to the pipeline's own entry point rather than importing
it. That keeps the pipeline the source of truth, keeps a crash inside a render
from taking the edge down with it, and makes cancellation possible at all,
since a thread running numpy cannot be interrupted and a process can.

On cancelling mid-render: the pipeline writes wavs through an atomic temp file
and rename, so a killed run cannot leave a truncated clip at a real name. It
can leave a stray `.tmp` beside one, which `AGENTS.md` records as safe to
delete. Nothing here tidies those up, because guessing which temp files belong
to which run is how a tool ends up deleting somebody's bank.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from .stages import Progress, Stage, final_stage


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class JobRequest:
    """What the caller asked for. Validated before it gets here."""

    source_url: str
    bank: str
    requested_by: str
    level: str | None = None          # None means every level the config has
    mimicry: float | None = None      # None means the full seven-rung sweep
    engine: str | None = None
    arrangement: str | None = None    # .arr text to replay, if any


@dataclass(frozen=True)
class Job:
    """A run, as stored and as reported."""

    id: str
    created_at: str
    requested_by: str
    source_url: str
    bank: str
    stage: Stage = Stage.QUEUED
    percent: int | None = None
    detail: str | None = None
    song: str | None = None
    level: str | None = None
    mimicry: float | None = None
    engine: str | None = None
    arrangement: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    error: str | None = None
    output_dir: str | None = None

    @property
    def settled(self) -> bool:
        """Whether this record is final.

        Note this is about the record, not about the process. The runner knows
        whether anything is still executing; a stage of DONE arrives from a
        line the pipeline prints while it is still exiting.
        """
        return self.stage in (Stage.DONE, Stage.REFUSED, Stage.FAILED)


def render_command(python: str, request: JobRequest, song_path: Path) -> list[str]:
    """The command line a person would have typed.

    Built here rather than inline so it can be asserted in a test without
    starting anything. Flags are only passed when the caller asked for them, so
    the pipeline's own defaults stay the defaults: passing `--play` always
    would silently halve every run to one level.
    """
    cmd = [python, "-m", "song_generator.cli", str(song_path), "--bank", request.bank]
    if request.level:
        cmd += ["--play", request.level]
    if request.mimicry is not None:
        cmd += ["--mimicry", f"{request.mimicry:g}"]
    if request.engine:
        cmd += ["--engine", request.engine]
    return cmd


class JobRunner:
    """Owns the running subprocess for one job at a time.

    One at a time by design, not by accident: the pipeline wants the whole GPU,
    and two renders at once are slower than the same two in sequence while also
    making the progress of each unreadable.
    """

    def __init__(self, on_update: Callable[[Job], None],
                 python: str | None = None) -> None:
        self._on_update = on_update
        self._python = python or sys.executable
        self._process: subprocess.Popen[str] | None = None
        self._job: Job | None = None
        self._lock = threading.Lock()
        self._cancelled = False
        # Liveness comes from the process, never from the parsed stage. The
        # stage reaches DONE when the pipeline prints that it wrote its files,
        # which is before it exits: reading busy off the stage freed the slot
        # early, so a second run could start while the first still held the
        # GPU, and a caller could see a finished job with no exit code on it.
        self._active = False

    @property
    def current(self) -> Job | None:
        with self._lock:
            return self._job

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._active

    def start(self, request: JobRequest, song_path: Path, cwd: Path,
              env: dict[str, str], command: Sequence[str] | None = None) -> Job:
        """Begin a run. Raises if one is already going."""
        with self._lock:
            if self._active:
                raise RuntimeError("a run is already going; the GPU takes one at a time")
            job = Job(
                id=uuid.uuid4().hex[:12],
                created_at=_now(),
                started_at=_now(),
                requested_by=request.requested_by,
                source_url=request.source_url,
                bank=request.bank,
                level=request.level,
                mimicry=request.mimicry,
                engine=request.engine,
                arrangement=request.arrangement,
                stage=Stage.QUEUED,
            )
            self._job = job
            self._cancelled = False
            self._active = True

        cmd = list(command) if command else render_command(self._python, request, song_path)
        self._process = subprocess.Popen(
            cmd, cwd=str(cwd), env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=1,
        )
        threading.Thread(target=self._watch, daemon=True).start()
        return job

    def cancel(self) -> bool:
        """Stop the run. False when there was nothing to stop."""
        with self._lock:
            process, job = self._process, self._job
            if process is None or job is None or not self._active:
                return False
            self._cancelled = True

        # terminate, not kill: the pipeline gets the chance to unwind, which is
        # what removes the temp file a half-written wav is going to.
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        return True

    def _watch(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None

        progress = Progress()
        for line in process.stdout:
            progress = progress.advance(line)
            with self._lock:
                job = self._job
                if job is None:
                    break
                if (job.stage, job.percent) != (progress.stage, progress.percent):
                    self._job = replace(job, stage=progress.stage,
                                        percent=progress.percent,
                                        detail=progress.detail)
                    updated = self._job
                else:
                    updated = None
            if updated is not None:
                self._on_update(updated)

        code = process.wait()
        with self._lock:
            job = self._job
            if job is None:
                return
            if self._cancelled:
                ended, error = Stage.FAILED, "cancelled"
            else:
                ended, error = final_stage(code, progress.stage), None
                if ended is Stage.FAILED:
                    error = f"the pipeline exited {code}"
            self._job = replace(job, stage=ended, exit_code=code,
                                finished_at=_now(), error=error, percent=None)
            done = self._job
            # Last, so that a caller who sees the slot free also sees the
            # finished record rather than racing this assignment.
            self._active = False
        self._on_update(done)
