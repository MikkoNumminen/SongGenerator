"""Configuration for the edge, from a file and the environment.

One frozen `Settings` read once at process start, so every module sees the same
world. Defaults point at this repository, because the edge runs on the machine
that holds the pipeline and its audio; there is no deployment where those live
apart.

Settings used to come from the environment alone. That made them live in
whichever shell happened to start the service and nowhere else: the process
ran for a day, nothing on the machine recorded what it had been given, and
stopping it would have lost the client id, the administrators and the allowed
origins with no way to put them back. `api/.env` is the durable copy. The
environment still wins where both say something, so a one-off override is
still a one-off override.

Deliberately stdlib only, so it can be imported and unit-tested without pulling
in FastAPI, torch, or the pipeline itself.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# The repository root, from this file: api/app/config.py -> two parents up.
_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Beside the edge it configures, not at the repository root, because it is
#: the edge's own and somebody looking for it will look next to it.
ENV_FILE = _REPO_ROOT / "api" / ".env"


def read_env_file(path: Path) -> dict[str, str]:
    """`NAME=value` lines. Absent file means an empty answer, not an error.

    Deliberately small: no interpolation, no exports, no multi-line values.
    Anything that needed those would be a reason to reach for a library, and
    a settings file with six lines in it is not that.
    """
    found: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return found
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        value = value.strip()
        # Quotes are how somebody writes a value with a space in it, and are
        # not part of the value.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        found[name.strip()] = value
    return found


@dataclass(frozen=True)
class Settings:
    """Everything the edge needs to know about its machine."""

    repo_root: Path
    database_path: Path
    # The list this edge started with. It seeds the database's own list the
    # first time and is not consulted again, because the owner can change the
    # database from a browser and cannot change this without a restart.
    allowed_emails: frozenset[str]
    google_client_id: str
    # Where the front end is served from. The browser preflights every call
    # because it is a different origin, and "*" plus credentials is the pairing
    # browsers refuse anyway, so these are named rather than wildcarded.
    allowed_origins: tuple[str, ...] = ()
    # Always allowed, and the only accounts that may edit the allowlist. Kept
    # out of the database on purpose: the panel exists to edit that table, so
    # an admin stored there could be removed through the panel, and the one
    # account able to undo it would be the account that just lost access.
    #
    # Defaults to nobody. An edge that names no administrator has none, which
    # leaves the allowlist exactly as unchangeable as it was before this
    # existed, rather than quietly promoting whoever asks first.
    admin_emails: frozenset[str] = frozenset()

    @property
    def auth_configured(self) -> bool:
        """False when sign-in cannot possibly succeed.

        Reported by /health rather than discovered at the first sign-in
        attempt: an edge started without an allowlist is misconfigured, not
        unauthorised, and the two need different messages.
        """
        return bool(self.google_client_id) and bool(
            self.allowed_emails or self.admin_emails)


#: Distinguishes "the caller said nothing about a file" from "the caller said
#: there is no file". Only the first should reach for the default.
_UNSAID: object = object()


def load_settings(env: dict[str, str] | None = None,
                  env_file: Path | None | object = _UNSAID) -> Settings:
    """Read settings from the file and the environment, in that order.

    The environment wins. A value exported for one run is meant to apply to
    that run, and a file that overrode it would make the override silently
    do nothing.

    Passing `env` means "this mapping is the whole environment", so the file
    on this machine is not consulted unless one is named as well. Otherwise a
    caller describing an empty environment would still be handed whatever
    happened to be configured here, and a test would pass or fail depending on
    whose machine it ran on.
    """
    if env_file is _UNSAID:
        env_file = ENV_FILE if env is None else None
    from_file = read_env_file(env_file) if isinstance(env_file, Path) else {}
    src = dict(from_file)
    src.update(os.environ if env is None else env)

    root = Path(src.get("SONGGEN_REPO_ROOT", str(_REPO_ROOT)))
    # Beside the pipeline's own working data rather than in the repo tree: it
    # is machine state, it is already gitignored there, and a stray commit of
    # a job history would carry song titles and local paths.
    default_db = root / "work" / "jobs.sqlite3"

    def addresses(name: str) -> frozenset[str]:
        return frozenset(
            e.strip().lower() for e in src.get(name, "").split(",") if e.strip()
        )

    emails = addresses("SONGGEN_ALLOWED_EMAILS")
    admins = addresses("SONGGEN_ADMIN_EMAILS")
    origins = tuple(
        o.strip() for o in src.get("SONGGEN_ALLOWED_ORIGINS", "").split(",")
        if o.strip()
    )
    return Settings(
        repo_root=root,
        allowed_origins=origins,
        database_path=Path(src.get("SONGGEN_DATABASE_PATH", str(default_db))),
        allowed_emails=emails,
        admin_emails=admins,
        google_client_id=src.get("SONGGEN_GOOGLE_CLIENT_ID", "").strip(),
    )
