"""Who may use this edge, and who may say so.

The allowlist moved out of the environment and into the database so the owner
can grant access from a browser without editing a file on a desktop that is
often off. That makes it something a request can change, so what a request may
change is the whole subject here.

No network and no Google: the verifier is a stand-in, exactly as in
test_main.py, so these are checks on rules rather than on a sign-in.
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.jobs import JobRunner
from app.main import create_app
from app.store import open_store
from app.users import open_users
from fastapi.testclient import TestClient

CLIENT_ID = "1234.apps.googleusercontent.com"
ADMIN = "owner@example.invalid"
GUEST = "friend@example.invalid"
STRANGER = "nobody@example.invalid"

BANKS = {"curated": "words_hq"}
LEVELS = ("conservative", "wild")
AT = "2026-01-01T00:00:00+00:00"


def _verifier(email: str):
    def verify(token: str, client_id: str) -> dict[str, object]:
        return {"iss": "https://accounts.google.com", "aud": CLIENT_ID,
                "email": email, "email_verified": True, "name": "Somebody"}
    return verify


def _app(tmp_path: Path, as_who: str, *, admins=frozenset({ADMIN}),
         seeded=frozenset({ADMIN})):
    settings = Settings(
        repo_root=tmp_path,
        database_path=tmp_path / "jobs.sqlite3",
        allowed_emails=seeded,
        google_client_id=CLIENT_ID,
        allowed_origins=(),
        admin_emails=admins,
    )
    store = open_store(settings.database_path)
    users = open_users(store.connection)
    users.seed(settings.allowed_emails, at=AT)
    app = create_app(
        settings=settings, runner=JobRunner(on_update=store.save),
        store=store, users=users, banks=BANKS, standardised_suffix=".std",
        levels=LEVELS, verifier=_verifier(as_who),
        prepare_song=lambda url: tmp_path / "song.mp4",
    )
    return TestClient(app), users


AUTH = {"Authorization": "Bearer whatever"}


class TestGranting:
    def test_an_admin_can_let_somebody_in_and_they_are_in_at_once(self, tmp_path):
        """The point of the table. Granted access has to work without the
        service being restarted, or it is not a panel, it is a note to self."""
        admin, users = _app(tmp_path, ADMIN)

        assert admin.post("/users", json={"email": GUEST}, headers=AUTH).status_code == 201

        # A second app over the same database is the next request arriving.
        guest, _ = _app(tmp_path, GUEST, seeded=frozenset())
        assert guest.get("/banks", headers=AUTH).status_code != 401

    def test_revoking_shuts_the_door_again(self, tmp_path):
        admin, users = _app(tmp_path, ADMIN)
        admin.post("/users", json={"email": GUEST}, headers=AUTH)

        assert admin.delete(f"/users/{GUEST}", headers=AUTH).status_code == 200

        guest, _ = _app(tmp_path, GUEST, seeded=frozenset())
        assert guest.get("/banks", headers=AUTH).status_code == 401

    def test_granting_twice_is_not_an_error(self, tmp_path):
        """Two clicks on a slow connection are not a failure to report."""
        admin, _ = _app(tmp_path, ADMIN)

        admin.post("/users", json={"email": GUEST}, headers=AUTH)
        again = admin.post("/users", json={"email": GUEST}, headers=AUTH)

        assert again.status_code == 201

    def test_the_address_is_stored_lowercased(self, tmp_path):
        """Google hands back a lowercased verified address and the check
        compares exactly, so a capital letter here would grant nothing."""
        admin, users = _app(tmp_path, ADMIN)

        admin.post("/users", json={"email": "Friend@Example.Invalid"}, headers=AUTH)

        assert GUEST in users.emails()


class TestOnlyAnAdminDecides:
    def test_an_allowed_guest_cannot_grant(self, tmp_path):
        """The difference between using the service and running it."""
        admin, _ = _app(tmp_path, ADMIN)
        admin.post("/users", json={"email": GUEST}, headers=AUTH)

        guest, _ = _app(tmp_path, GUEST, seeded=frozenset())
        answer = guest.post("/users", json={"email": STRANGER}, headers=AUTH)

        assert answer.status_code == 403

    def test_an_allowed_guest_cannot_read_the_list(self, tmp_path):
        admin, _ = _app(tmp_path, ADMIN)
        admin.post("/users", json={"email": GUEST}, headers=AUTH)

        guest, _ = _app(tmp_path, GUEST, seeded=frozenset())

        assert guest.get("/users", headers=AUTH).status_code == 403

    def test_a_stranger_is_refused_before_the_admin_question_arises(self, tmp_path):
        """401, not 403: they have not shown they are anybody."""
        stranger, _ = _app(tmp_path, STRANGER, seeded=frozenset())

        assert stranger.get("/users", headers=AUTH).status_code == 401


class TestTheOwnerCannotBeLockedOut:
    def test_an_admin_is_allowed_without_being_on_the_list(self, tmp_path):
        """Admins come from the machine's own configuration. An empty table is
        a fresh install, not a locked door."""
        admin, users = _app(tmp_path, ADMIN, seeded=frozenset())

        assert users.emails() == frozenset()
        assert admin.get("/users", headers=AUTH).status_code == 200

    def test_an_admin_cannot_be_revoked_through_the_panel(self, tmp_path):
        """It would report success and change nothing, since their access does
        not come from the table. Refusing says why instead."""
        admin, _ = _app(tmp_path, ADMIN)

        answer = admin.delete(f"/users/{ADMIN}", headers=AUTH)

        assert answer.status_code == 409
        assert "administrator" in answer.json()["detail"]

    def test_revoking_somebody_who_was_never_there_is_a_404(self, tmp_path):
        admin, _ = _app(tmp_path, ADMIN)

        assert admin.delete(f"/users/{STRANGER}", headers=AUTH).status_code == 404


class TestSeeding:
    def test_the_environment_fills_an_empty_list_once(self, tmp_path):
        _, users = _app(tmp_path, ADMIN, seeded=frozenset({GUEST}))

        assert GUEST in users.emails()

    def test_seeding_never_resurrects_a_revoked_address(self, tmp_path):
        """The variable on the desktop still names everybody it ever named. If
        seeding ran on every start, a revocation would last until the next
        restart and then quietly undo itself."""
        admin, users = _app(tmp_path, ADMIN, seeded=frozenset({GUEST}))
        admin.delete(f"/users/{GUEST}", headers=AUTH)

        users.seed(frozenset({GUEST}), at=AT)

        assert GUEST not in users.emails()
