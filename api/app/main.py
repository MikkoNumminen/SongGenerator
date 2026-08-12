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
from .users import ALL, DEMO, UserStore, open_users

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


#: Where the demo library lives, beside `output/` on the same machine.
DEMO_DIR = "output-demo"


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
    #: Which libraries this address may see. An administrator's is every one
    #: there is, which is why it is reported rather than stored.
    banks: list[str]
    #: Whether this address sees every run or only the ones it asked for.
    see_all_runs: bool


class BanksGrantRequest(BaseModel):
    banks: list[str]


class RunsVisibilityRequest(BaseModel):
    see_all_runs: bool


class UsersReply(BaseModel):
    users: list[UserReply]
    #: Everything that can be granted, so the panel can offer the boxes
    #: without knowing what this machine happens to hold.
    grantable: list[str]
    # So the panel can say "you" and can refuse to offer a revoke button for
    # an address it knows the server will not revoke.
    admins: list[str]


class GrantRequest(BaseModel):
    email: str
    #: Left out means the demo library and nothing else. A new address is a
    #: stranger until somebody says otherwise, so the default is the safe one
    #: rather than whatever the panel last had on screen.
    banks: list[str] | None = None

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
            allow_methods=["GET", "POST", "PUT", "DELETE"],
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

    def grantable_names() -> list[str]:
        """Everything that can be granted: the demo library, then the banks
        this machine actually holds."""
        return [DEMO, *sorted(banks)]

    def granted_to(who: Principal) -> frozenset[str]:
        """Which libraries this caller may see.

        An administrator gets all of them, computed rather than stored: the
        panel edits the table, and an admin whose access came from a row could
        be narrowed through the panel by the only account that could widen it
        again.
        """
        if who.email in settings.admin_emails:
            return frozenset(grantable_names())
        held = users.banks_for(who.email)
        # Expanded here rather than at the row, so a bank added next week is
        # included without anybody revisiting a grant.
        if ALL in held:
            return frozenset(grantable_names())
        return held

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
    def list_banks(who: Caller) -> BanksReply:
        # Only what this caller may actually render with. Offering the rest
        # would be a picker whose options are refused on submit.
        may = granted_to(who)
        found = [b for b in catalog(banks, settings.repo_root,
                                    standardised_suffix)
                 if b.name in may]
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
        # Checked here as well as in the picker. The picker is a convenience;
        # this is the rule.
        if body.bank not in granted_to(who):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"you have not been granted the bank"
                                f" {body.bank!r}")
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

    def _sees_every_run(who: Principal) -> bool:
        """An administrator always. Anybody else only if granted it.

        Off by default and granted deliberately, because a run names a song
        somebody chose to make, which is a more personal thing than the list
        of what exists.
        """
        return (who.email in settings.admin_emails
                or users.sees_all_runs(who.email))

    def _own(job: Job | None, who: Principal) -> bool:
        """Whether this caller may look at this run.

        A run carries the song's name, the bank it used and the files it
        produced, so the runs somebody else asked for are somebody else's
        business. Without this the library grant is decoration: an address
        holding the demo alone could list every run ever and fetch what it
        produced, which is the same audio the library refuses it.
        """
        return job is not None and (
            _sees_every_run(who)
            or job.requested_by.strip().lower() == who.email.strip().lower())

    @app.get("/jobs")
    def history(who: Caller, limit: int = 50,
                requested_by: str | None = None) -> HistoryReply:
        """Runs this caller may see, optionally narrowed to one person.

        The filter is a convenience for somebody who can already see all of
        them, not a way to see more: it is applied on top of the same check,
        so naming an address you could not otherwise see returns nothing
        rather than that person's runs.
        """
        capped = max(1, min(limit, 200))
        wanted = requested_by.strip().lower() if requested_by else None
        return HistoryReply(jobs=[
            _job_payload(j) for j in store.recent(capped)
            if _own(j, who)
            and (wanted is None
                 or j.requested_by.strip().lower() == wanted)])

    @app.get("/jobs/{job_id}")
    def one(job_id: str, who: Caller) -> JobReply:
        live = runner.current
        if live is not None and live.id == job_id:
            if not _own(live, who):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "no such run")
            return _job_payload(live)
        job = store.get(job_id)
        if not _own(job, who):
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
    def files(job_id: str, who: Caller) -> FilesReply:
        job = store.get(job_id)
        if not _own(job, who):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such run")
        return FilesReply(files=[
            FileReply(name=p.name, level=_level_of(p), bytes=p.stat().st_size)
            for p in _finished_files(job)
        ])

    @app.get("/jobs/{job_id}/files/{name}")
    def one_file(job_id: str, name: str, who: Caller):
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
        if not _own(job, who):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such run")
        for path in _finished_files(job):
            if path.name == name:
                return FileResponse(path, media_type="audio/mpeg",
                                    filename=path.name)
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "that run produced no such file")

    def _library_tracks(granted: frozenset[str] | None = None) -> list[tuple[str, str, Path]]:
        """Every rendering on this machine, as (song, bank, path).

        Read off the disk rather than out of the job table on purpose. Most of
        what is in `output/` was rendered from the command line, long before
        the edge existed, and a playlist that only knew about jobs would show a
        fraction of the library and look broken. The directory is the truth;
        deleting a file is how the owner takes something out of the playlist.
        """
        found = []
        root = settings.repo_root / "output"
        if root.is_dir():
            for song_dir in sorted(p for p in root.iterdir() if p.is_dir()):
                for bank_dir in sorted(p for p in song_dir.iterdir() if p.is_dir()):
                    if granted is not None and bank_dir.name not in granted:
                        continue
                    for path in sorted(bank_dir.glob("*.mp3")):
                        if path.is_file():
                            found.append((song_dir.name, bank_dir.name, path))

        # The demo library is a folder of its own rather than a flag on these
        # renderings. What a stranger may hear is then a thing somebody put
        # there, not a thing somebody forgot to hide.
        if granted is None or DEMO in granted:
            demo_root = settings.repo_root / DEMO_DIR
            if demo_root.is_dir():
                for song_dir in sorted(p for p in demo_root.iterdir() if p.is_dir()):
                    for path in sorted(song_dir.glob("*.mp3")):
                        if path.is_file():
                            found.append((song_dir.name, DEMO, path))
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
    def library(who: Caller) -> LibraryReply:
        return LibraryReply(tracks=[
            TrackReply(song=song, bank=bank, level=_level_of(path),
                       name=path.name, bytes=path.stat().st_size)
            for song, bank, path in _library_tracks(granted_to(who))
        ])

    @app.get("/library/{song}/{bank}/{name}")
    def track(song: str, bank: str, name: str, who: Caller):
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

        # Checked before the path is built, so a library nobody granted is
        # not merely absent from the listing.
        if bank not in granted_to(who):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such track")

        if bank == DEMO:
            root = (settings.repo_root / DEMO_DIR).resolve()
            candidate = (root / song / name).resolve()
        else:
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
        every = grantable_names()
        return UsersReply(
            users=[UserReply(
                email=u.email, added_at=u.added_at, added_by=u.added_by,
                is_admin=u.email in settings.admin_emails,
                # An administrator sees everything by being one, so the panel
                # is told that rather than the row, which would show an admin
                # holding the demo library alone.
                banks=every if u.email in settings.admin_emails
                else sorted(u.banks),
                # An administrator sees every run by being one, so the panel
                # is told that rather than the row.
                see_all_runs=(u.email in settings.admin_emails
                              or u.see_all_runs))
                for u in users.all()],
            admins=sorted(settings.admin_emails),
            grantable=every,
        )

    @app.get("/users")
    def list_users(_: Admin) -> UsersReply:
        return _users_reply()

    @app.post("/users", status_code=status.HTTP_201_CREATED)
    def grant(body: GrantRequest, who: Admin) -> UserReply:
        from datetime import datetime

        now = datetime.now(UTC).isoformat(timespec="seconds")
        asked = _known(body.banks) if body.banks is not None else frozenset({DEMO})
        users.add(body.email, added_by=who.email, at=now, banks=asked)
        return UserReply(email=body.email, added_at=now, added_by=who.email,
                         is_admin=body.email in settings.admin_emails,
                         banks=sorted(users.banks_for(body.email)),
                         see_all_runs=users.sees_all_runs(body.email))

    def _known(asked: list[str]) -> frozenset[str]:
        """Only names this machine can actually offer.

        A grant for a bank that is not here would sit in the table looking
        like access to something, and mean nothing until a bank of that name
        happened to appear.
        """
        every = set(grantable_names())
        kept = {b.strip() for b in asked if b.strip() in every}
        return frozenset(kept) or frozenset({DEMO})

    @app.put("/users/{email}/runs")
    def set_runs_visibility(email: str, body: RunsVisibilityRequest,
                            _: Admin) -> UsersReply:
        target = email.strip().lower()
        if target in settings.admin_emails:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "that address is an administrator and already sees every run")
        if not users.set_sees_all_runs(target, body.see_all_runs):
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                "that address was not on the list")
        return _users_reply()

    @app.put("/users/{email}/banks")
    def set_banks(email: str, body: BanksGrantRequest, _: Admin) -> UsersReply:
        target = email.strip().lower()
        if target in settings.admin_emails:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "that address is an administrator and already sees everything")
        if not users.set_banks(target, _known(body.banks)):
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                "that address was not on the list")
        return _users_reply()

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
    def cancel(job_id: str, who: Caller) -> CancelReply:
        live = runner.current
        if live is None or live.id != job_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "that run is not the one going")
        # One machine takes one run at a time, so stopping somebody else's is
        # taking the machine off them.
        if not _own(live, who):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such run")
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
