"""Environment-driven configuration for the edge.

One frozen `Settings` read once at process start, so every module sees the same
world. Defaults point at this repository, because the edge runs on the machine
that holds the pipeline and its audio; there is no deployment where those live
apart.

Deliberately stdlib only, so it can be imported and unit-tested without pulling
in FastAPI, torch, or the pipeline itself.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# The repository root, from this file: api/app/config.py -> two parents up.
_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    """Everything the edge needs to know about its machine."""

    repo_root: Path
    database_path: Path
    allowed_emails: frozenset[str]
    google_client_id: str
    # Where the front end is served from. The browser preflights every call
    # because it is a different origin, and "*" plus credentials is the pairing
    # browsers refuse anyway, so these are named rather than wildcarded.
    allowed_origins: tuple[str, ...] = ()

    @property
    def auth_configured(self) -> bool:
        """False when sign-in cannot possibly succeed.

        Reported by /health rather than discovered at the first sign-in
        attempt: an edge started without an allowlist is misconfigured, not
        unauthorised, and the two need different messages.
        """
        return bool(self.google_client_id) and bool(self.allowed_emails)


def load_settings(env: dict[str, str] | None = None) -> Settings:
    """Read settings from the environment, falling back to this repository."""
    src = os.environ if env is None else env

    root = Path(src.get("SONGGEN_REPO_ROOT", str(_REPO_ROOT)))
    # Beside the pipeline's own working data rather than in the repo tree: it
    # is machine state, it is already gitignored there, and a stray commit of
    # a job history would carry song titles and local paths.
    default_db = root / "work" / "jobs.sqlite3"

    emails = {
        e.strip().lower()
        for e in src.get("SONGGEN_ALLOWED_EMAILS", "").split(",")
        if e.strip()
    }
    origins = tuple(
        o.strip() for o in src.get("SONGGEN_ALLOWED_ORIGINS", "").split(",")
        if o.strip()
    )
    return Settings(
        repo_root=root,
        allowed_origins=origins,
        database_path=Path(src.get("SONGGEN_DATABASE_PATH", str(default_db))),
        allowed_emails=frozenset(emails),
        google_client_id=src.get("SONGGEN_GOOGLE_CLIENT_ID", "").strip(),
    )
