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
    bank="ppbank",
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
    """The pipeline's defaults are the defaults, with one exception.

    --play is not passed, because passing it always would silently halve every
    run to one level. Neither is --engine.

    --mimicry is the exception and is always passed. Leaving it to the
    pipeline's own default is the seven-rung sweep, which is what turned one
    submitted song into fourteen files. See AGENTS.md, "Never write more than
    two renderings for a song".
    """
    cmd = render_command("python", REQUEST, Path("input/song.mp4"))

    assert "--play" not in cmd
    assert "--engine" not in cmd
    assert cmd[cmd.index("--mimicry") + 1] == "1"


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
        " '  bank ppbank (x, standardised)', '  play conservative, seed 1',"
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


def test_a_finished_run_remembers_where_it_wrote(tmp_path):
    """Otherwise nothing can offer what the run produced.

    output_dir was declared, stored and read, and never once assigned, so
    /jobs/{id}/files answered with an empty list for every run there has ever
    been and the box that lists a run's takes had nothing to show.
    """
    runner, _ = _runner()
    made = tmp_path / "output" / "a_song" / "ppbank"
    made.mkdir(parents=True)
    runner.start(REQUEST, tmp_path / "song.mp4", tmp_path, dict(os.environ),
                 command=_stub(f"print(r'  wrote 2 versions to {made}')"))

    assert _wait_until(lambda: not runner.busy)
    assert runner.current is not None
    assert Path(runner.current.output_dir or "") == made
    # The song is the folder above the bank, which is how output/ is laid out.
    assert runner.current.song == "a_song"


def test_the_folder_is_found_when_only_one_rendering_was_written(tmp_path):
    """`--play wild` writes one file, and the pipeline then names the file
    rather than the folder it went in."""
    runner, _ = _runner()
    made = tmp_path / "output" / "a_song" / "ppbank"
    made.mkdir(parents=True)
    one = made / "a_song.wild.mp3"
    runner.start(REQUEST, tmp_path / "song.mp4", tmp_path, dict(os.environ),
                 command=_stub(f"print(r'  wrote     {one}')"))

    assert _wait_until(lambda: not runner.busy)
    assert runner.current is not None
    assert Path(runner.current.output_dir or "") == made


def test_a_folder_printed_relative_is_read_against_the_run_directory(tmp_path):
    """The pipeline prints the folder as it spelled it, which is relative when
    nothing resolved it. The edge answers from its own directory, which is not
    required to be the one the run was started in."""
    runner, _ = _runner()
    (tmp_path / "output" / "a_song" / "ppbank").mkdir(parents=True)
    runner.start(REQUEST, tmp_path / "song.mp4", tmp_path, dict(os.environ),
                 command=_stub("print(r'  wrote 2 versions to output\\\\a_song\\\\ppbank')"))

    assert _wait_until(lambda: not runner.busy)
    assert runner.current is not None
    assert Path(runner.current.output_dir or "") == \
        (tmp_path / "output" / "a_song" / "ppbank").resolve()


def test_a_folder_that_cannot_be_resolved_does_not_wedge_the_runner(tmp_path):
    """The read loop is the only thing that reaps the process and frees the
    slot, so nothing in it may raise.

    resolve() throws on a NUL byte in a name and on a symlink loop, both of
    which arrive through a filename. An exception here killed the watcher
    thread before process.wait(), leaving the runner busy for the life of the
    edge: every later run refused with "a run is already going", the job stuck
    at queued, and the child never collected.
    """
    runner, _ = _runner()
    runner.start(REQUEST, tmp_path / "song.mp4", tmp_path, dict(os.environ),
                 command=_stub(r"print('  wrote     out\\bad\x00name\\x.mp3')"))

    assert _wait_until(lambda: not runner.busy), "the runner never came free"
    assert runner.current is not None
    assert runner.current.stage is Stage.DONE
    assert runner.current.exit_code == 0
    assert runner.current.output_dir is None


def test_the_folder_is_worked_out_once_however_much_follows_it(
        tmp_path, monkeypatch):
    """resolve() on a path whose host has gone away blocks for twenty seconds,
    and the pipeline prints its summary table after the line that names the
    folder. Repeating the work per line stops draining the pipe the run is
    still writing to."""
    made = tmp_path / "output" / "a_song" / "ppbank"
    made.mkdir(parents=True)

    resolved: list[str] = []
    real = Path.resolve

    def counting(self, *args, **kwargs):
        resolved.append(str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", counting)

    runner, _ = _runner()
    script = (f"print(r'  wrote 2 versions to {made}')\n"
              "print('    conservative   1.00   12   a.mp3')\n"
              "print('    wild           1.00   14   b.mp3')\n"
              "print('  analysis  work/a_song/analysis.json')\n")
    runner.start(REQUEST, tmp_path / "song.mp4", tmp_path, dict(os.environ),
                 command=_stub(script))

    assert _wait_until(lambda: not runner.busy)
    assert runner.current is not None
    assert Path.resolve is counting, "the patch was undone before the assert"
    assert [r for r in resolved if str(made) in r] == [str(made)]


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


# ---------------------------------------------------------------------------
# Starting, when starting is what goes wrong
# ---------------------------------------------------------------------------

def test_a_spawn_that_fails_does_not_brick_the_runner(tmp_path):
    """The busy flag is set under the lock and the spawn happens outside it.
    Without clearing it on failure the runner stays busy forever and every
    later run is refused with `a run is already going`, while nothing runs."""
    runner, _ = _runner()

    with pytest.raises(RuntimeError, match="could not start"):
        runner.start(REQUEST, tmp_path / "s.mp4", tmp_path, dict(os.environ),
                     command=["this-executable-does-not-exist"])

    assert runner.busy is False, "the slot must free up when nothing started"

    runner.start(REQUEST, tmp_path / "s.mp4", tmp_path, dict(os.environ),
                 command=_stub("print('  wrote 1 versions to out')"))
    assert _wait_until(lambda: not runner.busy)


def test_a_spawn_that_fails_is_still_recorded(tmp_path):
    """It happened and it failed, so it belongs in the history rather than
    vanishing because nothing ever produced a line of output."""
    runner, seen = _runner()

    with pytest.raises(RuntimeError):
        runner.start(REQUEST, tmp_path / "s.mp4", tmp_path, dict(os.environ),
                     command=["this-executable-does-not-exist"])

    assert seen, "nothing was reported at all"
    assert seen[-1].stage is Stage.FAILED
    assert "could not start" in (seen[-1].error or "")


def test_the_job_is_reported_before_anything_is_spawned(tmp_path):
    """One writer for the row. When the caller saved it instead, the caller
    and the watcher raced, and a run that finished quickly could be written
    back to queued and sit in the history as queued forever."""
    runner, seen = _runner()

    runner.start(REQUEST, tmp_path / "s.mp4", tmp_path, dict(os.environ),
                 command=_stub("print('  wrote 1 versions to out')"))

    assert seen, "the job was not recorded before the process started"
    assert seen[0].stage is Stage.QUEUED
    assert _wait_until(lambda: not runner.busy)


def test_a_quick_run_ends_settled_in_the_record(tmp_path):
    """The symptom the race produced: a finished run showing as queued."""
    runner, seen = _runner()

    runner.start(REQUEST, tmp_path / "s.mp4", tmp_path, dict(os.environ),
                 command=_stub("print('  wrote 1 versions to out')"))
    assert _wait_until(lambda: not runner.busy)

    assert seen[-1].settled is True
    assert seen[-1].stage is Stage.DONE


def test_the_site_renders_one_rung_rather_than_the_whole_sweep():
    """The pipeline's own default is seven rungs, which is right at a terminal
    where somebody is comparing them by ear. Through the site nobody asked for
    seven: the machine spends a GPU on all of them and one song arrives as
    fourteen near-identical rows in a library that already holds hundreds."""
    from app.main import FULL_MIMICRY, SubmitBody

    asked = SubmitBody(source_url="https://example.invalid/x", bank="ppbank")

    assert asked.mimicry == FULL_MIMICRY == 1.0


def test_the_rung_still_reaches_the_command_line():
    from app.jobs import JobRequest, render_command
    from pathlib import Path

    cmd = render_command("python", JobRequest(
        requested_by="owner@example.invalid",
        source_url="https://example.invalid/x",
        bank="ppbank", mimicry=1.0), Path("song.mp4"))

    assert "--mimicry" in cmd
    assert cmd[cmd.index("--mimicry") + 1] == "1"
