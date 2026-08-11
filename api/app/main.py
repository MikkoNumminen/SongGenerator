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
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from .auth import AuthError, Principal, google_verifier, verify
from .banks import catalog
from .config import Settings, load_settings
from .jobs import Job, JobRequest, JobRunner
from .songs import SongError, prepare
from .store import JobStore, open_store
from .users import UserStore, open_users

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


class HealthReply(BaseModel):
    """What an unauthenticated caller may learn. Deliberately nothing else."""

    status: str
    auth_configured: bool
    busy: bool


class BankReply(BaseModel):
    """One bank, as `banks.BankInfo` reports it plus the derived verdict."""

    name: str
    directory: str
    built: bool
    units: int
    standardised: bool
    problem: str | None = None
    usable: bool


class BanksReply(BaseModel):
    banks: list[BankReply]
    any_usable: bool
    levels: list[str]
    engines: list[str]


class JobReply(BaseModel):
    """A run as reported. Mirrors `jobs.Job` without the arrangement.

    The pasted arrangement can be enormous and nothing renders it back, so it
    stays in the store for re-running rather than riding on every poll.
    """

    id: str
    created_at: str
    requested_by: str
    source_url: str
    bank: str
    stage: str
    settled: bool
    percent: int | None = None
    detail: str | None = None
    song: str | None = None
    level: str | None = None
    mimicry: float | None = None
    engine: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    error: str | None = None
    output_dir: str | None = None


class HistoryReply(BaseModel):
    jobs: list[JobReply]


class CancelReply(BaseModel):
    cancelled: bool


class FileReply(BaseModel):
    """One finished rendering, as something to download."""

    name: str
    level: str | None = None
    bytes: int


class FilesReply(BaseModel):
    files: list[FileReply]


class TrackReply(BaseModel):
    """One playable rendering, addressed by where it sits on disk."""

    song: str
    bank: str
    level: str | None = None
    name: str
    bytes: int


class LibraryReply(BaseModel):
    tracks: list[TrackReply]


class UserReply(BaseModel):
    email: str
    added_at: str
    added_by: str
    is_admin: bool


class UsersReply(BaseModel):
    users: list[UserReply]
    # So the panel can say "you" and can refuse to offer a revoke button for
    # an address it knows the server will not revoke.
    admins: list[str]


class GrantRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def _an_address_at_all(cls, value: str) -> str:
        email = value.strip().lower()
        # Deliberately shallow. The real check is Google's: a token has to
        # carry this address, verified, before it opens anything. Validating
        # harder here would reject legitimate addresses to no benefit.
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("that does not look like an email address")
        return email


def _job_payload(job: Job) -> JobReply:
    data = asdict(job)
    data["stage"] = job.stage.value
    data["settled"] = job.settled
    # The pasted arrangement can be enormous and nothing renders it back. It is
    # kept in the store for re-running, not shipped on every poll.
    data.pop("arrangement", None)
    return JobReply(**data)


def create_app(
    settings: Settings,
    runner: JobRunner,
    store: JobStore,
    users: UserStore,
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

    # The front end is served from somewhere else entirely, so the browser
    # will preflight. Origins are configured rather than "*", because "*" plus
    # credentials is the combination browsers refuse anyway.
    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.allowed_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    def principal(request: Request) -> Principal:
        header = request.headers.get("Authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        # Read per request, not captured at startup. The owner grants and
        # revokes from a browser, and a revocation that only took effect at the
        # next restart of a desktop service would be a revocation in name.
        # Admins are added rather than stored, so emptying the table cannot
        # lock the owner out of the panel that empties it.
        allowed = users.emails() | settings.admin_emails
        try:
            return verify(token, allowed, settings.google_client_id, verifier)
        except AuthError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    @app.get("/health")
    def health() -> HealthReply:
        """Open by design. Says nothing about songs or who may use this."""
        # Asked of the live allowlist rather than of Settings. The environment
        # variable only seeds the table once, so after a revoke the two
        # disagree, and this is the field a front end uses to decide whether to
        # offer sign-in at all. Reported from the sources the sign-in check
        # actually consults.
        can_sign_in = bool(users.emails() | settings.admin_emails)
        return HealthReply(status="ok",
                           auth_configured=bool(settings.google_client_id)
                           and can_sign_in,
                           busy=runner.busy)

    Caller = Annotated[Principal, Depends(principal)]

    def administrator(who: Caller) -> Principal:
        """An allowed caller who may also change who else is allowed.

        403 rather than 401: they proved who they are and it is not enough,
        which is a different answer from not proving it, and the front end
        shows a different thing for each.
        """
        if who.email not in settings.admin_emails:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "only an administrator may change the allowlist")
        return who

    Admin = Annotated[Principal, Depends(administrator)]

    @app.get("/banks")
    def list_banks(_: Caller) -> BanksReply:
        found = catalog(banks, settings.repo_root, standardised_suffix)
        return BanksReply(
            banks=[BankReply(**asdict(b), usable=b.usable) for b in found],
            # Said explicitly so the front end can show the empty state rather
            # than an enabled picker whose every option fails at render time.
            any_usable=any(b.usable for b in found),
            levels=list(levels),
            engines=list(_ENGINES),
        )

    @app.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
    def submit(body: SubmitBody, who: Caller) -> JobReply:
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
    def history(_: Caller, limit: int = 50) -> HistoryReply:
        capped = max(1, min(limit, 200))
        return HistoryReply(jobs=[_job_payload(j) for j in store.recent(capped)])

    @app.get("/jobs/{job_id}")
    def one(job_id: str, _: Caller) -> JobReply:
        live = runner.current
        if live is not None and live.id == job_id:
            return _job_payload(live)
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such run")
        return _job_payload(job)

    def _finished_files(job: Job) -> list[Path]:
        """The renderings a job produced, or nothing if it produced none."""
        if not job.output_dir:
            return []
        folder = Path(job.output_dir)
        if not folder.is_dir():
            return []
        return sorted(p for p in folder.glob("*.mp3") if p.is_file())

    @app.get("/jobs/{job_id}/files")
    def files(job_id: str, _: Caller) -> FilesReply:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such run")
        return FilesReply(files=[
            FileReply(name=p.name, level=_level_of(p), bytes=p.stat().st_size)
            for p in _finished_files(job)
        ])

    @app.get("/jobs/{job_id}/files/{name}")
    def one_file(job_id: str, name: str, _: Caller):
        """Hand back one rendering.

        The name is matched against the files the job actually produced rather
        than joined onto a directory. Joining is how this kind of route becomes
        a way to read any file on the machine: `..%2f..%2f` and a path outside
        the output folder. Comparing against a listing cannot leave the folder,
        whatever the caller sends, so the guard is the shape of the code rather
        than a check that can be forgotten.
        """
        from fastapi.responses import FileResponse

        job = store.get(job_id)
        if job is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such run")
        for path in _finished_files(job):
            if path.name == name:
                return FileResponse(path, media_type="audio/mpeg",
                                    filename=path.name)
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "that run produced no such file")

    def _library_tracks() -> list[tuple[str, str, Path]]:
        """Every rendering on this machine, as (song, bank, path).

        Read off the disk rather than out of the job table on purpose. Most of
        what is in `output/` was rendered from the command line, long before
        the edge existed, and a playlist that only knew about jobs would show a
        fraction of the library and look broken. The directory is the truth;
        deleting a file is how the owner takes something out of the playlist.
        """
        root = settings.repo_root / "output"
        if not root.is_dir():
            return []
        found = []
        for song_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            for bank_dir in sorted(p for p in song_dir.iterdir() if p.is_dir()):
                for path in sorted(bank_dir.glob("*.mp3")):
                    if path.is_file():
                        found.append((song_dir.name, bank_dir.name, path))
        return found

    def _level_of(path: Path) -> str | None:
        """`<song>.<level>.mp3`, or `<song>.<level>.mimN.mp3` from the runs
        that wrote the whole ladder. None rather than a guess otherwise: a
        wrong label on a track is worse than an unlabelled one."""
        parts = path.stem.split(".")
        if len(parts) < 2:
            return None
        level = parts[-1]
        if level.startswith("mim") and len(parts) >= 3:
            level = parts[-2]
        return level

    @app.get("/library")
    def library(_: Caller) -> LibraryReply:
        return LibraryReply(tracks=[
            TrackReply(song=song, bank=bank, level=_level_of(path),
                       name=path.name, bytes=path.stat().st_size)
            for song, bank, path in _library_tracks()
        ])

    @app.get("/library/{song}/{bank}/{name}")
    def track(song: str, bank: str, name: str, _: Caller):
        """One rendering, to play or to save.

        Contained by resolving the path and checking it is still inside the
        output directory, rather than by searching the listing for a match.
        The listing is the safer-looking option and is the wrong one here: a
        browser playing audio issues range requests, so streaming one song
        would walk every rendering on the machine several times over, and
        there are already more than a thousand of them.

        resolve() is what makes the check sound. It normalises `..` and
        follows symlinks first, so the comparison is against where the path
        really lands rather than how it was spelled.
        """
        from fastapi.responses import FileResponse

        root = (settings.repo_root / "output").resolve()
        candidate = (root / song / bank / name).resolve()
        if (not candidate.is_relative_to(root)
                or candidate.suffix.lower() != ".mp3"
                or not candidate.is_file()):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such track")
        return FileResponse(candidate, media_type="audio/mpeg",
                            filename=candidate.name)

    def _users_reply() -> UsersReply:
        """The allowlist as the panel wants it, shared by the two routes that
        answer with it rather than one route calling the other."""
        return UsersReply(
            users=[UserReply(email=u.email, added_at=u.added_at,
                             added_by=u.added_by,
                             is_admin=u.email in settings.admin_emails)
                   for u in users.all()],
            admins=sorted(settings.admin_emails),
        )

    @app.get("/users")
    def list_users(_: Admin) -> UsersReply:
        return _users_reply()

    @app.post("/users", status_code=status.HTTP_201_CREATED)
    def grant(body: GrantRequest, who: Admin) -> UserReply:
        from datetime import datetime

        now = datetime.now(UTC).isoformat(timespec="seconds")
        users.add(body.email, added_by=who.email, at=now)
        return UserReply(email=body.email, added_at=now, added_by=who.email,
                         is_admin=body.email in settings.admin_emails)

    @app.delete("/users/{email}")
    def revoke(email: str, _: Admin) -> UsersReply:
        target = email.strip().lower()
        # An admin's access does not come from this table, so removing the row
        # would report success and change nothing. Refusing says why.
        if target in settings.admin_emails:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "that address is an administrator, set in this machine's own"
                " configuration; it cannot be revoked from here")
        if not users.remove(target):
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                "that address was not on the list")
        return _users_reply()

    @app.post("/jobs/{job_id}/cancel")
    def cancel(job_id: str, _: Caller) -> CancelReply:
        live = runner.current
        if live is None or live.id != job_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "that run is not the one going")
        if not runner.cancel():
            raise HTTPException(status.HTTP_409_CONFLICT, "that run had already finished")
        current = runner.current
        if current is not None:
            store.save(current)
        return CancelReply(cancelled=True)

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
    now = datetime.now(UTC).isoformat(timespec="seconds")
    store.reconcile(now)

    # Same database, same schema, one connection. The allowlist moved out of
    # the environment so it can be edited while the service runs; the variable
    # still seeds it the first time, so a machine that had one keeps working
    # without anybody being told to do something.
    users = open_users(store.connection)
    users.seed(settings.allowed_emails, at=now)

    runner = JobRunner(on_update=store.save)

    def fetch_song(url: str) -> Path:
        return prepare(url, settings.repo_root / "input")

    return create_app(
        prepare_song=fetch_song,
        settings=settings,
        runner=runner,
        store=store,
        users=users,
        banks=dict(pipeline_config.BANKS),
        standardised_suffix=pipeline_config.STD_SUFFIX,
        levels=tuple(pipeline_config.PLAY_LEVELS),
    )
