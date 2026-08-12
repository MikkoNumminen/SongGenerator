"""Who may use this edge, and who may decide that.

Two lists, deliberately kept apart.

The allowlist is a table, so the owner can grant and revoke from a browser
while the service keeps running. It used to be an environment variable read
once at startup, which meant letting somebody in was a file edit and a restart
on a desktop that is often off.

Admins are not in that table. They come from the environment and are always
allowed. The panel's whole job is editing the allowlist, so an admin stored
there could be removed through the panel, and the one account that can fix it
would be the account that just lost access. Keeping them out makes that
impossible rather than merely discouraged.

Addresses are lowercased everywhere. Google hands back a verified address and
`auth.decide` lowercases before it compares, so anything stored in a different
case would silently never match.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


#: The library everybody starts with, and the only one a new address gets.
#: It is not a bank on this machine; it is a folder of things chosen to be
#: shown to strangers, so granting it gives away nothing that was not put
#: there on purpose.
DEMO = "demo"

#: Everything this machine has, whatever that turns out to be. Stored rather
#: than expanded, so a bank added next week is included without anybody
#: revisiting a row. It is what addresses granted before libraries existed
#: carry, because they had everything and a migration must not quietly take
#: it away.
ALL = "*"


def parse_banks(raw: str) -> frozenset[str]:
    """The stored column as a set. Empty means demo, never everything."""
    names = {part.strip() for part in raw.split(",") if part.strip()}
    return frozenset(names) or frozenset({DEMO})


def join_banks(banks: frozenset[str] | set[str] | list[str]) -> str:
    """Back to the column. Sorted, so the same grant stores the same bytes."""
    cleaned = {str(b).strip() for b in banks if str(b).strip()}
    return ",".join(sorted(cleaned or {DEMO}))


@dataclass(frozen=True)
class AllowedUser:
    """A granted address, the trail of who granted it, and what it may see."""

    email: str
    added_at: str
    added_by: str
    banks: frozenset[str]
    #: Whether this address sees every run or only the ones it asked for.
    see_all_runs: bool


class UserStore:
    """The allowlist, as rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def emails(self) -> frozenset[str]:
        """Just the addresses, for the check on every request."""
        rows = self._conn.execute("SELECT email FROM allowed_emails").fetchall()
        return frozenset(str(r["email"]) for r in rows)

    def all(self) -> list[AllowedUser]:
        """Every grant, oldest first, for the panel."""
        rows = self._conn.execute(
            "SELECT email, added_at, added_by, banks, see_all_runs"
            " FROM allowed_emails ORDER BY added_at, email"
        ).fetchall()
        return [
            AllowedUser(email=str(r["email"]), added_at=str(r["added_at"]),
                        added_by=str(r["added_by"]),
                        banks=parse_banks(str(r["banks"])),
                        see_all_runs=bool(r["see_all_runs"]))
            for r in rows
        ]

    def banks_for(self, email: str) -> frozenset[str]:
        """What this address may see. Demo for anybody not on the list, which
        is nobody: the caller has already been checked against it."""
        row = self._conn.execute(
            "SELECT banks FROM allowed_emails WHERE email = ?",
            (email.strip().lower(),)
        ).fetchone()
        return parse_banks(str(row["banks"])) if row is not None else frozenset({DEMO})

    def sees_all_runs(self, email: str) -> bool:
        """Whether this address was granted every run. False for anybody not
        on the list, which is nobody: the caller is checked before this."""
        row = self._conn.execute(
            "SELECT see_all_runs FROM allowed_emails WHERE email = ?",
            (email.strip().lower(),)
        ).fetchone()
        return bool(row["see_all_runs"]) if row is not None else False

    def set_sees_all_runs(self, email: str, allowed: bool) -> bool:
        """Grant or withdraw it. False when the address is not on the list."""
        cur = self._conn.execute(
            "UPDATE allowed_emails SET see_all_runs = ? WHERE email = ?",
            (1 if allowed else 0, email.strip().lower()),
        )
        return cur.rowcount > 0

    def set_banks(self, email: str, banks: frozenset[str] | set[str] | list[str]) -> bool:
        """Change what an address may see. False when it is not on the list."""
        cur = self._conn.execute(
            "UPDATE allowed_emails SET banks = ? WHERE email = ?",
            (join_banks(banks), email.strip().lower()),
        )
        return cur.rowcount > 0

    def add(self, email: str, *, added_by: str, at: str,
            banks: frozenset[str] | set[str] | list[str] | None = None) -> bool:
        """Grant access. False when that address already had it.

        Idempotent rather than an error, because the panel's own list is what
        the caller was looking at, and two clicks on a slow connection should
        not read as a failure.
        """
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO allowed_emails"
            " (email, added_at, added_by, banks) VALUES (?, ?, ?, ?)",
            (email.strip().lower(), at, added_by.strip().lower(),
             join_banks(banks if banks is not None else {DEMO})),
        )
        return cur.rowcount > 0

    def remove(self, email: str) -> bool:
        """Revoke access. False when that address did not have it."""
        cur = self._conn.execute(
            "DELETE FROM allowed_emails WHERE email = ?", (email.strip().lower(),)
        )
        return cur.rowcount > 0

    _SEEDED = "allowlist_seeded_at"

    def seed(self, emails: frozenset[str], *, at: str) -> int:
        """Fill the list from the environment, once ever. Returns how many.

        Once ever, not "whenever the table is empty". Those differ in exactly
        the case that matters: revoke the last remaining address and the table
        is empty again, so the next start would seed it and the revocation
        would quietly undo itself. The variable on the desktop still names
        everybody it ever named, and nobody edits it after the first day.

        A test caught that, which is why it is a marker rather than a count.
        """
        done = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (self._SEEDED,)
        ).fetchone()
        if done is not None:
            return 0
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (self._SEEDED, at),
        )
        added = 0
        for email in sorted(emails):
            # The environment variable is the owner naming people they trust,
            # from before there was anything to choose between.
            if self.add(email, added_by="SONGGEN_ALLOWED_EMAILS", at=at,
                        banks={ALL}):
                added += 1
        return added


@dataclass(frozen=True)
class Invitation:
    """A link that admits exactly one account, to the demo library."""

    token: str
    created_at: str
    created_by: str
    expires_at: str
    used_at: str | None
    used_by: str | None

    def spent(self) -> bool:
        return self.used_at is not None


class InvitationStore:
    """One-time invitations, as rows.

    An invitation grants the demo library and nothing else, and that is not a
    parameter. A link that could be made to grant more would be a link worth
    stealing; this one is worth no more than the thing it admits you to.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, *, created_by: str, at: str, expires_at: str) -> Invitation:
        # 32 bytes from the system source. Guessing one is not a threat model
        # anybody needs to think about again.
        import secrets
        token = secrets.token_urlsafe(32)
        self._conn.execute(
            "INSERT INTO invitations"
            " (token, created_at, created_by, expires_at) VALUES (?, ?, ?, ?)",
            (token, at, created_by.strip().lower(), expires_at),
        )
        return Invitation(token=token, created_at=at,
                          created_by=created_by.strip().lower(),
                          expires_at=expires_at, used_at=None, used_by=None)

    def all(self) -> list[Invitation]:
        """Newest first: the panel is usually looking for the one just made."""
        rows = self._conn.execute(
            "SELECT token, created_at, created_by, expires_at, used_at, used_by"
            " FROM invitations ORDER BY created_at DESC, token"
        ).fetchall()
        return [Invitation(token=str(r["token"]), created_at=str(r["created_at"]),
                           created_by=str(r["created_by"]),
                           expires_at=str(r["expires_at"]),
                           used_at=r["used_at"], used_by=r["used_by"])
                for r in rows]

    def find(self, token: str) -> Invitation | None:
        rows = [i for i in self.all() if i.token == token]
        return rows[0] if rows else None

    def spend(self, token: str, *, by: str, at: str) -> bool:
        """Mark one used. False when it was already used or never existed.

        The condition is in the statement rather than in a read followed by a
        write, so two people opening the same link at the same moment cannot
        both be admitted.
        """
        cur = self._conn.execute(
            "UPDATE invitations SET used_at = ?, used_by = ?"
            " WHERE token = ? AND used_at IS NULL",
            (at, by.strip().lower(), token),
        )
        return cur.rowcount > 0

    def revoke(self, token: str) -> bool:
        """Withdraw an unused link. Spent ones are kept as a record."""
        cur = self._conn.execute(
            "DELETE FROM invitations WHERE token = ? AND used_at IS NULL",
            (token,),
        )
        return cur.rowcount > 0


def open_invitations(conn: sqlite3.Connection) -> InvitationStore:
    """An invitation store on an already-open connection."""
    return InvitationStore(conn)


def open_users(conn: sqlite3.Connection) -> UserStore:
    """A user store on an already-open connection, schema already applied."""
    return UserStore(conn)
