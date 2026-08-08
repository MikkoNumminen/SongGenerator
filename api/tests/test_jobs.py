"""The runner's lifecycle, against a stub that behaves like the pipeline.

The stub prints the same stage headers the real pipeline prints and then waits,
so the states, the transitions and cancellation can be exercised in
milliseconds without a GPU. What it cannot tell us is whether the real pipeline
still prints those lines; `test_stages.py` holds that, against captured output.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest
from app.jobs import Job, JobRequest, JobRunner, render_command
from app.stages import Stage

REQUEST = JobRequest(
    source_url="https://example.invalid/watch?v=abc",
    bank="curated",
    requested_by="someone@example.invalid",
)


def _stub(script: str) -> list[str]:
    return [sys.executable, "-c", script]


def _wait_until(predicate, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _runner() -> tuple[JobRunner, list[Job]]:
    seen: list[Job] = []
    lock = threading.Lock()

    def record(job: Job) -> None:
        with lock:
            seen.append(job)

    return JobRunner(on_update=record), seen


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

def test_only_the_flags_that_were_asked_for_are_passed():
    """The pipeline's defaults are the defaults. Passing --play always would
    silently halve every run to one level."""
    cmd = render_command("python", REQUEST, Path("input/song.mp4"))

    assert "--play" not in cmd
    assert "--mimicry" not in cmd
    assert "--engine" not in cmd
    assert cmd[-2:] == ["--bank", "curated"]


def test_the_settings_that_were_asked_for_do_reach_the_command():
    request = JobRequest(source_url="u", bank="muslimbank", requested_by="a",
                         level="wild", mimicry=0.45, engine="world")
    cmd = render_command("python", request, Path("input/song.mp4"))

    assert cmd[cmd.index("--play") + 1] == "wild"
    assert cmd[cmd.index("--mimicry") + 1] == "0.45"
    assert cmd[cmd.index("--engine") + 1] == "world"


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

def test_a_run_walks_the_stages_and_ends_done(tmp_path):
    runner, seen = _runner()
    script = (
        "import time\n"
        "for line in ['  separator roformer', '  stems 1s -> w',"
        " '  bank curated (x, standardised)', '  play conservative, seed 1',"
        " '  wrote 7 versions to out']:\n"
        "    print(line, flush=True); time.sleep(0.02)\n"
    )
    runner.start(REQUEST, tmp_path / "song.mp4", tmp_path, dict(os.environ),
                 command=_stub(script))

    assert _wait_until(lambda: not runner.busy), "the run never finished"
    stages = [j.stage for j in seen]
    assert stages[-1] is Stage.DONE
    assert Stage.SEPARATING in stages and Stage.RENDERING in stages
    assert runner.current is not None and runner.current.exit_code == 0


def test_a_song_with_no_vocal_is_refused_not_failed(tmp_path):
    """Exit 3 is the pipeline's mode B. It is a normal answer about the song,
    and the UI needs to say something different from `it broke`."""
    runner, _ = _runner()
    script = (
        "import sys\n"
        "print('  separator roformer', flush=True)\n"
        "print('    verdict           MODE B -- no vocals', flush=True)\n"
        "sys.exit(3)\n"
    )
    runner.start(REQUEST, tmp_path / "s.mp4", tmp_path, dict(os.environ),
                 command=_stub(script))

    assert _wait_until(lambda: not runner.busy)
    assert runner.current is not None
    assert runner.current.stage is Stage.REFUSED
    assert runner.current.error is None, "a refusal is not an error"


def test_a_crash_is_failed_and_says_the_exit_code(tmp_path):
    runner, _ = _runner()
    runner.start(REQUEST, tmp_path / "s.mp4", tmp_path, dict(os.environ),
                 command=_stub("import sys; print('  separator x'); sys.exit(2)"))

    assert _wait_until(lambda: not runner.busy)
    assert runner.current is not None
    assert runner.current.stage is Stage.FAILED
    assert "2" in (runner.current.error or "")


def test_finishing_records_when_it_finished(tmp_path):
    runner, _ = _runner()
    runner.start(REQUEST, tmp_path / "s.mp4", tmp_path, dict(os.environ),
                 command=_stub("print('  wrote 1 versions to out')"))

    assert _wait_until(lambda: not runner.busy)
    assert runner.current is not None and runner.current.finished_at


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

def test_cancelling_a_run_stops_it(tmp_path):
    runner, _ = _runner()
    script = (
        "import time\n"
        "print('  separator roformer', flush=True)\n"
        "time.sleep(60)\n"
    )
    runner.start(REQUEST, tmp_path / "s.mp4", tmp_path, dict(os.environ),
                 command=_stub(script))
    assert _wait_until(lambda: runner.current is not None
                       and runner.current.stage is Stage.SEPARATING)

    assert runner.cancel() is True
    assert _wait_until(lambda: not runner.busy), "cancel did not stop the run"
    assert runner.current is not None
    assert runner.current.error == "cancelled"


def test_cancelling_when_nothing_is_running_is_not_an_error(tmp_path):
    runner, _ = _runner()
    assert runner.cancel() is False


def test_cancelling_a_finished_run_does_nothing(tmp_path):
    runner, _ = _runner()
    runner.start(REQUEST, tmp_path / "s.mp4", tmp_path, dict(os.environ),
                 command=_stub("print('  wrote 1 versions to out')"))
    assert _wait_until(lambda: not runner.busy)

    assert runner.cancel() is False


# ---------------------------------------------------------------------------
# One at a time
# ---------------------------------------------------------------------------

def test_a_second_run_is_refused_while_one_is_going(tmp_path):
    """The pipeline wants the whole GPU. Two at once is slower than the same
    two in sequence, and makes the progress of each unreadable."""
    runner, _ = _runner()
    runner.start(REQUEST, tmp_path / "s.mp4", tmp_path, dict(os.environ),
                 command=_stub("import time; print('  separator x', flush=True); time.sleep(30)"))
    assert _wait_until(lambda: runner.busy)

    with pytest.raises(RuntimeError, match="already going"):
        runner.start(REQUEST, tmp_path / "s2.mp4", tmp_path, dict(os.environ),
                     command=_stub("print('x')"))

    runner.cancel()


def test_the_slot_frees_up_once_a_run_ends(tmp_path):
    runner, _ = _runner()
    runner.start(REQUEST, tmp_path / "s.mp4", tmp_path, dict(os.environ),
                 command=_stub("print('  wrote 1 versions to out')"))
    assert _wait_until(lambda: not runner.busy)

    runner.start(REQUEST, tmp_path / "s2.mp4", tmp_path, dict(os.environ),
                 command=_stub("print('  wrote 1 versions to out')"))
    assert _wait_until(lambda: not runner.busy)


# ---------------------------------------------------------------------------
# Updates
# ---------------------------------------------------------------------------

def test_updates_only_fire_when_something_changed(tmp_path):
    """The watcher reads every line. A callback per line would write to SQLite
    hundreds of times for one separation."""
    runner, seen = _runner()
    script = (
        "print('  separator roformer', flush=True)\n"
        "for _ in range(50): print('    some chatter with no stage in it', flush=True)\n"
        "print('  wrote 1 versions to out', flush=True)\n"
    )
    runner.start(REQUEST, tmp_path / "s.mp4", tmp_path, dict(os.environ),
                 command=_stub(script))
    assert _wait_until(lambda: not runner.busy)

    assert len(seen) <= 4, [j.stage for j in seen]
