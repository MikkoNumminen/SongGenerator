"""The HTTP surface. Thin on purpose.

Every handler here is a few lines: check who is asking, call into a module that
knows how to do the thing, shape the answer. The work lives in `banks`, `jobs`,
`store` and `auth`, because a desktop front end will want exactly that work and
none of this.

`create_app` takes its collaborators as arguments so the whole surface can be
exercised without a GPU, a Google account, or a real pipeline. The production
wiring is in `build`, at the bottom.

One route is deliberately open. `/health` answers without a token because the
front end uses it to decide whether the backend is reachable at all, and a
front end that had to authenticate before it could ask "are you there" would
show a sign-in error when the honest answer is "that desktop is switched off".
It reports liveness and configuration, never anything about songs or accounts.
"""

# No `from __future__ import annotations` here, deliberately. FastAPI
# resolves a handler's annotations with get_type_hints against module
# globals, and the dependency alias below is a local inside create_app.
# With postponed annotations it cannot be resolved, so every guarded route
# silently stopped guarding and answered 422 to an anonymous caller instead
# of 401. Python 3.11 evaluates the `X | None` forms here natively anyway.

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from .auth import AuthError, Principal, google_verifier, verify
from .banks import catalog
from .config import Settings, load_settings
from .jobs import Job, JobRequest, JobRunner
from .songs import SongError, prepare
from .store import JobStore, open_store

# Levels the pipeline offers. Read from its config at wiring time rather than
# hardcoded, so a level added there does not need editing here too.
_ENGINES = ("world", "rubberband")


class SubmitBody(BaseModel):
    """A request to make a song.

    Validated here as well as in the browser. The browser's validation is for
    the person typing; this one is because the browser is not the only thing
    that can post to this.
    """

    source_url: str = Field(min_length=1, max_length=2048)
    bank: str = Field(min_length=1, max_length=64)
    level: str | None = None
    mimicry: float | None = Field(default=None, ge=0.0, le=1.0)
    engine: str | None = None
    arrangement: str | None = Field(default=None, max_length=1_000_000)

    @field_validator("source_url")
    @classmethod
    def _looks_like_a_link(cls, value: str) -> str:
        text = value.strip()
        if not text.startswith(("http://", "https://")):
            raise ValueError("that does not look like a link")
        return text

    @field_validator("engine")
    @classmethod
    def _known_engine(cls, value: str | None) -> str | None:
        if value is not None and value not in _ENGINES:
            raise ValueError(f"engine must be one of: {', '.join(_ENGINES)}")
        return value


def _job_payload(job: Job) -> dict[str, Any]:
    data = asdict(job)
    data["stage"] = job.stage.value
    data["settled"] = job.settled
    # The pasted arrangement can be enormous and nothing renders it back. It is
    # kept in the store for re-running, not shipped on every poll.
    data.pop("arrangement", None)
    return data


def create_app(
    settings: Settings,
    runner: JobRunner,
    store: JobStore,
    banks: dict[str, str],
    standardised_suffix: str,
    levels: tuple[str, ...],
    # Required, not optional. It used to default to None and the submit route
    # answered 503 when nothing supplied it, which meant production wiring
    # could forget the one thing this service exists to do and only say so at
    # request time. A missing collaborator is now a wiring error.
    prepare_song: Callable[[str], Path],
    verifier: Callable[[str, str], dict[str, object]] = google_verifier,
) -> FastAPI:
    """Build the app around already-made collaborators."""
    app = FastAPI(title="SongGenerator edge", version="0.1.0")
    # Recorded on the app so the wiring can be asserted directly. A
    # request cannot show it: an unauthenticated one stops at the guard
    # long before anything fetches, which is how a missing fetcher went
    # unnoticed until somebody pressed go.
    app.state.prepare_song = prepare_song

    # The front end is served from somewhere else entirely, so the browser
    # will preflight. Origins are configured rather than "*", because "*" plus
    # credentials is the combination browsers refuse anyway.
    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.allowed_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    def principal(request: Request) -> Principal:
        header = request.headers.get("Authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        try:
            return verify(token, settings.allowed_emails,
                          settings.google_client_id, verifier)
        except AuthError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    @app.get("/health")
    def health() -> dict[str, Any]:
        """Open by design. Says nothing about songs or who may use this."""
        return {
            "status": "ok",
            "auth_configured": settings.auth_configured,
            "busy": runner.busy,
        }

    Caller = Annotated[Principal, Depends(principal)]

    @app.get("/banks")
    def list_banks(_: Caller) -> dict[str, Any]:
        found = catalog(banks, settings.repo_root, standardised_suffix)
        return {
            "banks": [asdict(b) | {"usable": b.usable} for b in found],
            # Said explicitly so the front end can show the empty state rather
            # than an enabled picker whose every option fails at render time.
            "any_usable": any(b.usable for b in found),
            "levels": list(levels),
            "engines": list(_ENGINES),
        }

    @app.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
    def submit(body: SubmitBody, who: Caller) -> dict[str, Any]:
        found = {b.name: b for b in catalog(banks, settings.repo_root,
                                            standardised_suffix)}
        chosen = found.get(body.bank)
        if chosen is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"no bank called {body.bank!r} on this machine")
        if not chosen.usable:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"the bank {body.bank!r} has no clips built yet")
        if body.level is not None and body.level not in levels:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"level must be one of: {', '.join(levels)}")
        if runner.busy:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "a run is already going; this machine takes one at a time")

        request = JobRequest(
            source_url=body.source_url, bank=body.bank, requested_by=who.email,
            level=body.level, mimicry=body.mimicry, engine=body.engine,
            arrangement=body.arrangement,
        )
        try:
            song = prepare_song(body.source_url)
        except SongError as exc:
            # The link itself is the problem: a playlist, a removed video, or a
            # title that collides with a song already here. The caller can fix
            # all of those, so it is theirs rather than a server fault.
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

        # The runner records the job itself, before it spawns anything, so
        # there is one writer for that row rather than two racing.
        try:
            job = runner.start(request, song, settings.repo_root, _child_env(settings))
        except RuntimeError as exc:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
        return _job_payload(job)

    @app.get("/jobs")
    def history(_: Caller, limit: int = 50) -> dict[str, Any]:
        capped = max(1, min(limit, 200))
        return {"jobs": [_job_payload(j) for j in store.recent(capped)]}

    @app.get("/jobs/{job_id}")
    def one(job_id: str, _: Caller) -> dict[str, Any]:
        live = runner.current
        if live is not None and live.id == job_id:
            return _job_payload(live)
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such run")
        return _job_payload(job)

    @app.post("/jobs/{job_id}/cancel")
    def cancel(job_id: str, _: Caller) -> dict[str, Any]:
        live = runner.current
        if live is None or live.id != job_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "that run is not the one going")
        if not runner.cancel():
            raise HTTPException(status.HTTP_409_CONFLICT, "that run had already finished")
        current = runner.current
        if current is not None:
            store.save(current)
        return {"cancelled": True}

    return app


def _child_env(settings: Settings) -> dict[str, str]:
    """The environment a pipeline subprocess needs."""
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(settings.repo_root / "src")
    return env


def build() -> FastAPI:
    """Production wiring. Reads the pipeline's own configuration for its lists."""
    import sys

    settings = load_settings()
    sys.path.insert(0, str(settings.repo_root / "src"))
    from song_generator import config as pipeline_config

    store = open_store(settings.database_path)
    from datetime import datetime
    store.reconcile(datetime.now(UTC).isoformat(timespec="seconds"))

    runner = JobRunner(on_update=store.save)

    def fetch_song(url: str) -> Path:
        return prepare(url, settings.repo_root / "input")

    return create_app(
        prepare_song=fetch_song,
        settings=settings,
        runner=runner,
        store=store,
        banks=dict(pipeline_config.BANKS),
        standardised_suffix=pipeline_config.STD_SUFFIX,
        levels=tuple(pipeline_config.PLAY_LEVELS),
    )
