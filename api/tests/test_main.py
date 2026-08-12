"""The HTTP surface, with everything behind it faked.

No GPU, no Google, no pipeline. What is worth asserting here is the surface's
own behaviour: who is turned away, what a caller is told when the machine is
busy or the bank is empty, and that the one open route stays open.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.config import Settings
from app.jobs import Job, JobRunner
from app.main import create_app
from app.stages import Stage
from app.store import open_store
from app.users import open_invitations, open_requests, open_users
from fastapi.testclient import TestClient

CLIENT_ID = "1234.apps.googleusercontent.com"
OWNER = "owner@example.invalid"

BANKS = {"ppbank": "words_hq", "muslimbank": "words_muslim"}
LEVELS = ("conservative", "wild")


def _settings(tmp_path: Path, **over: object) -> Settings:
    base = {
        "repo_root": tmp_path,
        "database_path": tmp_path / "jobs.sqlite3",
        "allowed_emails": frozenset({OWNER}),
        "google_client_id": CLIENT_ID,
        "allowed_origins": (),
    }
    base.update(over)
    return Settings(**base)  # type: ignore[arg-type]


def _claims(email: str = OWNER) -> dict[str, object]:
    return {"iss": "https://accounts.google.com", "aud": CLIENT_ID,
            "email": email, "email_verified": True, "name": "Owner"}


def _verifier(email: str = OWNER):
    def verify(token: str, client_id: str) -> dict[str, object]:
        if token == "bad":
            raise ValueError("signature")
        return _claims(email)
    return verify


def _build_bank(tmp_path: Path, name: str, clips: int = 3) -> None:
    import json
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "words.json").write_text(
        json.dumps({f"c_{i}.wav": {"words": ["raw"]} for i in range(clips)}),
        encoding="utf-8")


def _app(tmp_path: Path, runner: JobRunner | None = None,
         verifier=None, **over: object):
    settings = _settings(tmp_path, **over)
    store = open_store(settings.database_path)
    # The allowlist lives in the database now. Seeding it from the settings is
    # what production does at startup, so the tests get the same world.
    users = open_users(store.connection)
    invitations = open_invitations(store.connection)
    requests = open_requests(store.connection)
    users.seed(settings.allowed_emails, at="2026-01-01T00:00:00+00:00")
    runner = runner or JobRunner(on_update=store.save)
    app = create_app(
        settings=settings, runner=runner, store=store, users=users, invitations=invitations, requests=requests, banks=BANKS,
        standardised_suffix=".std", levels=LEVELS,
        verifier=verifier or _verifier(),
        prepare_song=lambda url: tmp_path / "song.mp4",
    )
    return TestClient(app), store, runner


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer good-token"}


# ---------------------------------------------------------------------------
# The open route
# ---------------------------------------------------------------------------

def test_health_answers_without_a_token(tmp_path):
    """The front end asks this to decide whether the machine is even on. If it
    needed a token, a switched-off desktop would look like a sign-in problem."""
    client, _, _ = _app(tmp_path)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_says_nothing_about_songs_or_people(tmp_path):
    """It is the one route anybody on the internet can reach, so its answer is
    liveness and configuration and nothing else."""
    client, _, _ = _app(tmp_path)

    body = client.get("/health").json()

    assert set(body) == {"status", "auth_configured", "busy"}
    assert OWNER not in repr(body)


def test_health_admits_when_nobody_could_sign_in(tmp_path):
    """An edge started with no allowlist is misconfigured, not unauthorised,
    and the front end can say so instead of showing a broken sign-in."""
    client, _, _ = _app(tmp_path, allowed_emails=frozenset())

    assert client.get("/health").json()["auth_configured"] is False


# ---------------------------------------------------------------------------
# Everything else is closed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,path", [
    ("get", "/banks"), ("get", "/jobs"), ("get", "/jobs/abc"),
    ("post", "/jobs"), ("post", "/jobs/abc/cancel"),
])
def test_every_other_route_refuses_an_anonymous_caller(tmp_path, method, path):
    """The funnel address is not a secret, so this is the only thing between
    the pipeline and the internet."""
    client, _, _ = _app(tmp_path)

    response = getattr(client, method)(path)

    assert response.status_code == 401


def test_a_signed_in_stranger_is_still_refused(tmp_path):
    """A real Google account that is not on the list gets no further than no
    account at all."""
    settings = _settings(tmp_path)
    store = open_store(settings.database_path)
    users = open_users(store.connection)
    invitations = open_invitations(store.connection)
    requests = open_requests(store.connection)
    users.seed(settings.allowed_emails, at="2026-01-01T00:00:00+00:00")
    app = create_app(settings=settings, runner=JobRunner(on_update=store.save),
                     store=store, users=users, invitations=invitations, requests=requests, banks=BANKS,
                     standardised_suffix=".std",
                     levels=LEVELS, verifier=_verifier("stranger@example.invalid"),
                     prepare_song=lambda url: tmp_path / "s.mp4")

    response = TestClient(app).get("/banks", headers=_auth())

    assert response.status_code == 403
    assert "not been given access" in response.json()["detail"]


def test_a_bad_signature_is_refused_not_a_crash(tmp_path):
    client, _, _ = _app(tmp_path)

    response = client.get("/banks", headers={"Authorization": "Bearer bad"})

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Banks
# ---------------------------------------------------------------------------

def test_banks_are_listed_with_whether_they_can_actually_sing(tmp_path):
    _build_bank(tmp_path, "words_hq", clips=25)
    client, _, _ = _app(tmp_path)

    body = client.get("/banks", headers=_auth()).json()

    by_name = {b["name"]: b for b in body["banks"]}
    assert by_name["ppbank"]["usable"] is True
    assert by_name["ppbank"]["units"] == 25
    assert by_name["muslimbank"]["usable"] is False, "never built on this machine"
    assert body["any_usable"] is True


def test_a_machine_with_no_bank_built_says_so_rather_than_erroring(tmp_path):
    """A fresh clone. The picker needs an empty state, not two options that
    both fail the moment somebody presses go."""
    client, _, _ = _app(tmp_path)

    body = client.get("/banks", headers=_auth()).json()

    assert body["any_usable"] is False
    assert all(not b["usable"] for b in body["banks"])


# ---------------------------------------------------------------------------
# Submitting
# ---------------------------------------------------------------------------

def test_a_run_can_be_submitted_and_is_remembered(tmp_path):
    _build_bank(tmp_path, "words_hq")
    client, store, runner = _app(tmp_path)

    response = client.post("/jobs", headers=_auth(), json={
        "source_url": "https://example.invalid/watch?v=abc", "bank": "ppbank"})

    assert response.status_code == 202
    job_id = response.json()["id"]
    assert store.get(job_id) is not None
    runner.cancel()


def test_something_that_is_not_a_link_is_refused(tmp_path):
    _build_bank(tmp_path, "words_hq")
    client, _, _ = _app(tmp_path)

    response = client.post("/jobs", headers=_auth(),
                           json={"source_url": "not a link", "bank": "ppbank"})

    assert response.status_code == 422


def test_a_bank_this_machine_does_not_have_is_refused_by_name(tmp_path):
    client, _, _ = _app(tmp_path)

    response = client.post("/jobs", headers=_auth(), json={
        "source_url": "https://example.invalid/x", "bank": "nosuchbank"})

    assert response.status_code == 400
    assert "nosuchbank" in response.json()["detail"]


def test_a_bank_with_no_clips_is_refused_before_anything_starts(tmp_path):
    """Better than starting a render that fails minutes later inside the
    pipeline with a message about a missing index."""
    client, _, _ = _app(tmp_path)

    response = client.post("/jobs", headers=_auth(), json={
        "source_url": "https://example.invalid/x", "bank": "ppbank"})

    assert response.status_code == 409
    assert "built" in response.json()["detail"]


def test_an_unknown_level_is_refused(tmp_path):
    _build_bank(tmp_path, "words_hq")
    client, _, _ = _app(tmp_path)

    response = client.post("/jobs", headers=_auth(), json={
        "source_url": "https://example.invalid/x", "bank": "ppbank",
        "level": "sideways"})

    assert response.status_code == 400


def test_an_unknown_engine_is_refused(tmp_path):
    _build_bank(tmp_path, "words_hq")
    client, _, _ = _app(tmp_path)

    response = client.post("/jobs", headers=_auth(), json={
        "source_url": "https://example.invalid/x", "bank": "ppbank",
        "engine": "kazoo"})

    assert response.status_code == 422


def test_a_mimicry_outside_the_dial_is_refused(tmp_path):
    _build_bank(tmp_path, "words_hq")
    client, _, _ = _app(tmp_path)

    response = client.post("/jobs", headers=_auth(), json={
        "source_url": "https://example.invalid/x", "bank": "ppbank",
        "mimicry": 1.5})

    assert response.status_code == 422


def test_a_second_run_is_refused_while_one_is_going(tmp_path):
    """The machine takes one at a time, and the caller is told that rather
    than being queued invisibly."""
    _build_bank(tmp_path, "words_hq")

    class Busy(JobRunner):
        @property
        def busy(self) -> bool:
            return True

    client, _, _ = _app(tmp_path, runner=Busy(on_update=lambda job: None))

    response = client.post("/jobs", headers=_auth(), json={
        "source_url": "https://example.invalid/x", "bank": "ppbank"})

    assert response.status_code == 409
    assert "one at a time" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Reading runs back
# ---------------------------------------------------------------------------

def test_an_unknown_run_is_a_clean_404(tmp_path):
    client, _, _ = _app(tmp_path)

    assert client.get("/jobs/nope", headers=_auth()).status_code == 404


def test_history_starts_empty(tmp_path):
    client, _, _ = _app(tmp_path)

    assert client.get("/jobs", headers=_auth()).json()["jobs"] == []


def test_a_stored_run_comes_back_with_its_stage(tmp_path):
    client, store, _ = _app(tmp_path)
    store.save(Job(id="abc", created_at="2026-08-08T00:00:00+00:00",
                   requested_by=OWNER, source_url="u", bank="ppbank",
                   stage=Stage.REFUSED))

    body = client.get("/jobs/abc", headers=_auth()).json()

    assert body["stage"] == "refused"
    assert body["settled"] is True


def test_the_pasted_arrangement_is_not_shipped_on_every_poll(tmp_path):
    """It can be enormous and nothing renders it back. It stays in the store
    for re-running."""
    client, store, _ = _app(tmp_path)
    store.save(Job(id="abc", created_at="2026-08-08T00:00:00+00:00",
                   requested_by=OWNER, source_url="u", bank="ppbank",
                   arrangement="# seed 42\n" + "phrase 0\n" * 500))

    body = client.get("/jobs/abc", headers=_auth()).json()

    assert "arrangement" not in body


def test_cancelling_a_run_that_is_not_going_is_a_conflict(tmp_path):
    client, _, _ = _app(tmp_path)

    assert client.post("/jobs/abc/cancel", headers=_auth()).status_code == 409


# ---------------------------------------------------------------------------
# The production wiring
# ---------------------------------------------------------------------------

def test_the_real_wiring_builds_and_registers_every_route(tmp_path, monkeypatch):
    """The bug this guards against is the one that shipped: a collaborator
    the tests always injected and the production wiring never supplied, so the
    route that matters answered 503 to anybody who pressed go.

    This is also what pins that the production wiring supplies a fetcher, since
    `prepare_song` is required: a `build` that forgot it cannot reach the point
    of registering a route. Asserting the fetcher separately needed the app to
    carry a reference to it that nothing else read, so that went away with it.

    The repository root is the real one, because `build` imports the pipeline
    to read its bank and level lists, and that is tracked. Only the database is
    redirected, so this writes nothing a person would miss.
    """
    from app.main import build

    monkeypatch.setenv("SONGGEN_DATABASE_PATH", str(tmp_path / "jobs.sqlite3"))
    monkeypatch.setenv("SONGGEN_ALLOWED_EMAILS", "owner@example.invalid")
    monkeypatch.setenv("SONGGEN_GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")

    app = build()

    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert {"/health", "/banks", "/jobs", "/jobs/{job_id}",
            "/jobs/{job_id}/cancel"} <= paths


def test_a_fetcher_is_not_optional(tmp_path):
    """The bug was a collaborator the tests always injected and the production
    wiring never supplied, so it could only be discovered by a person pressing
    go. Leaving it out is a wiring error now, raised where the app is built.

    Asserted directly rather than through a request, because a request without
    credentials stops at the guard and would pass whether a fetcher exists or
    not, which is how this went unnoticed the first time.
    """
    settings = _settings(tmp_path)
    store = open_store(settings.database_path)

    with pytest.raises(TypeError, match="prepare_song"):
        create_app(  # type: ignore[call-arg]
            settings=settings, runner=JobRunner(on_update=store.save),
            store=store, banks=BANKS, standardised_suffix=".std",
            levels=LEVELS, verifier=_verifier(),
        )
