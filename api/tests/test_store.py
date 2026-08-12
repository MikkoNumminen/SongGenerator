"""History that survives a restart, including an ugly one.

The interesting cases are not the round trip. They are what the table looks
like after the process died mid-render, because a job stuck at `rendering`
forever is worse than one that says it does not know how it ended.
"""

from __future__ import annotations

from app.jobs import Job
from app.stages import Stage
from app.store import open_store


def _job(job_id: str, stage: Stage = Stage.QUEUED, created: str = "2026-08-08T00:00:00+00:00") -> Job:
    return Job(
        id=job_id,
        created_at=created,
        requested_by="someone@example.invalid",
        source_url="https://example.invalid/watch?v=abc",
        bank="ppbank",
        stage=stage,
    )


def test_a_job_round_trips(tmp_path):
    store = open_store(tmp_path / "jobs.sqlite3")
    store.save(_job("aaa"))

    got = store.get("aaa")
    assert got is not None
    assert got.id == "aaa"
    assert got.stage is Stage.QUEUED
    assert got.bank == "ppbank"


def test_saving_the_same_job_again_updates_it(tmp_path):
    """The runner calls save on every change. Without the upsert the caller
    would have to track whether a row exists, which is exactly the state it
    should not be keeping."""
    store = open_store(tmp_path / "jobs.sqlite3")
    store.save(_job("aaa"))
    store.save(_job("aaa", stage=Stage.RENDERING))

    assert len(store.recent()) == 1
    got = store.get("aaa")
    assert got is not None and got.stage is Stage.RENDERING


def test_a_missing_job_is_none_not_an_error(tmp_path):
    store = open_store(tmp_path / "jobs.sqlite3")
    assert store.get("nope") is None


def test_history_is_newest_first(tmp_path):
    store = open_store(tmp_path / "jobs.sqlite3")
    store.save(_job("old", created="2026-08-01T00:00:00+00:00"))
    store.save(_job("new", created="2026-08-08T00:00:00+00:00"))

    assert [j.id for j in store.recent()] == ["new", "old"]


def test_history_can_be_empty(tmp_path):
    """A fresh machine. The table renders an empty state, not an error."""
    store = open_store(tmp_path / "jobs.sqlite3")
    assert store.recent() == []


def test_the_optional_settings_survive_the_round_trip(tmp_path):
    store = open_store(tmp_path / "jobs.sqlite3")
    job = Job(
        id="bbb", created_at="2026-08-08T00:00:00+00:00",
        requested_by="a@b.invalid", source_url="u", bank="muslimbank",
        stage=Stage.DONE, level="wild", mimicry=0.45, engine="world",
        arrangement="# seed 42\nphrase 0\n", exit_code=0,
        output_dir="output/song/muslimbank",
    )
    store.save(job)

    got = store.get("bbb")
    assert got is not None
    assert (got.level, got.mimicry, got.engine) == ("wild", 0.45, "world")
    assert got.arrangement is not None and got.arrangement.startswith("# seed 42")
    assert got.output_dir == "output/song/muslimbank"


def test_a_run_the_process_died_during_is_settled_at_startup(tmp_path):
    """Nothing was watching it, so its real outcome cannot be known from here.
    Saying that is better than a history row that claims it is still going."""
    path = tmp_path / "jobs.sqlite3"
    store = open_store(path)
    store.save(_job("crashed", stage=Stage.RENDERING))

    reopened = open_store(path)
    assert len(reopened.unsettled()) == 1

    settled = reopened.reconcile(now="2026-08-08T01:00:00+00:00")

    assert settled == 1
    got = reopened.get("crashed")
    assert got is not None
    assert got.stage is Stage.FAILED
    assert got.error is not None and "unknown" in got.error
    assert got.finished_at == "2026-08-08T01:00:00+00:00"


def test_reconcile_leaves_finished_jobs_alone(tmp_path):
    """It runs at every startup, so it must be safe to run against a table of
    perfectly good history."""
    store = open_store(tmp_path / "jobs.sqlite3")
    store.save(_job("done", stage=Stage.DONE))
    store.save(_job("refused", stage=Stage.REFUSED))

    assert store.reconcile(now="2026-08-08T01:00:00+00:00") == 0
    assert store.get("done").stage is Stage.DONE          # type: ignore[union-attr]
    assert store.get("refused").stage is Stage.REFUSED    # type: ignore[union-attr]


def test_a_refused_run_is_not_treated_as_unfinished(tmp_path):
    """Mode B is a settled outcome. Reconciling it into failed would rewrite a
    true answer about the song into a false one about the edge."""
    store = open_store(tmp_path / "jobs.sqlite3")
    store.save(_job("novocal", stage=Stage.REFUSED))

    assert store.unsettled() == []
