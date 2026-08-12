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
from app.users import open_invitations, open_users
from fastapi.testclient import TestClient

CLIENT_ID = "1234.apps.googleusercontent.com"
ADMIN = "owner@example.invalid"
GUEST = "friend@example.invalid"
STRANGER = "nobody@example.invalid"

BANKS = {"ppbank": "words_hq"}
LEVELS = ("conservative", "wild")
AT = "2026-01-01T00:00:00+00:00"


def _verifier(email: str):
    def verify(token: str, client_id: str) -> dict[str, object]:
        return {"iss": "https://accounts.google.com", "aud": CLIENT_ID,
                "email": email, "email_verified": True, "name": "Somebody"}
    return verify


def _app(tmp_path: Path, as_who: str, *, admins=frozenset({ADMIN}),
         seeded=frozenset({ADMIN}), banks=None):
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
    invitations = open_invitations(store.connection)
    users.seed(settings.allowed_emails, at=AT)
    app = create_app(
        settings=settings, runner=JobRunner(on_update=store.save),
        store=store, users=users, invitations=invitations, banks=banks or BANKS, standardised_suffix=".std",
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


class TestHealthTellsTheTruth:
    """`auth_configured` decides whether a front end offers sign-in at all.

    It used to be read off the environment variable, which only seeds the
    table once. After a revoke the two disagree, and the field would claim
    somebody could sign in when the live list said otherwise.
    """

    def test_an_empty_live_list_with_no_admin_reports_unconfigured(self, tmp_path):
        # Revoked by a real administrator, then read back by an edge that has
        # none: the list is empty and the variable still names somebody.
        client, _ = _app(tmp_path, ADMIN, seeded=frozenset({GUEST}))
        assert client.delete(f"/users/{GUEST}", headers=AUTH).status_code == 200

        # A second app over the same database is the next request arriving.
        fresh, _ = _app(tmp_path, ADMIN, admins=frozenset(), seeded=frozenset())

        assert fresh.get("/health").json()["auth_configured"] is False

    def test_an_administrator_alone_is_enough(self, tmp_path):
        client, _ = _app(tmp_path, ADMIN, seeded=frozenset())

        assert client.get("/health").json()["auth_configured"] is True


class TestServingATrack:
    """The library serves audio off disk, so the containment check is the
    whole security of the route."""

    def _track(self, tmp_path, name="song.conservative.mp3"):
        out = tmp_path / "output" / "a_song" / "ppbank"
        out.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(b"not really an mp3")
        return out / name

    def test_a_rendering_is_served(self, tmp_path):
        self._track(tmp_path)
        client, _ = _app(tmp_path, ADMIN)

        answer = client.get(
            "/library/a_song/ppbank/song.conservative.mp3", headers=AUTH)

        assert answer.status_code == 200
        assert answer.content == b"not really an mp3"

    def test_climbing_out_of_the_output_directory_is_refused(self, tmp_path):
        """The whole point of resolving before comparing. A name that walks up
        and back down must not reach a file the route was never meant to
        serve."""
        secret = tmp_path / "secret.mp3"
        secret.write_bytes(b"not for you")
        self._track(tmp_path)
        client, _ = _app(tmp_path, ADMIN)

        for attempt in ("..%2f..%2fsecret.mp3", "..%2F..%2Fsecret.mp3"):
            answer = client.get(
                f"/library/a_song/ppbank/{attempt}", headers=AUTH)
            assert answer.status_code == 404, attempt
            assert b"not for you" not in answer.content

    def test_only_renderings_are_served(self, tmp_path):
        """Containment alone would happily hand over anything inside output/."""
        out = tmp_path / "output" / "a_song" / "ppbank"
        out.mkdir(parents=True, exist_ok=True)
        (out / "notes.txt").write_text("private", encoding="utf-8")
        client, _ = _app(tmp_path, ADMIN)

        answer = client.get("/library/a_song/ppbank/notes.txt", headers=AUTH)

        assert answer.status_code == 404

    def test_a_stranger_gets_no_audio(self, tmp_path):
        self._track(tmp_path)
        client, _ = _app(tmp_path, STRANGER, seeded=frozenset())

        answer = client.get(
            "/library/a_song/ppbank/song.conservative.mp3", headers=AUTH)

        assert answer.status_code == 401


class TestWhatAnAddressMaySee:
    """A new address is a stranger. It gets the demo library and nothing else
    until somebody says otherwise."""

    def _rendering(self, tmp_path, bank="ppbank", song="a_song"):
        out = tmp_path / "output" / song / bank
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{song}.conservative.mp3").write_bytes(b"real one")
        return out

    def _demo(self, tmp_path, song="a_demo_song"):
        out = tmp_path / "output-demo" / song
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{song}.wild.mp3").write_bytes(b"demo one")
        return out

    def test_a_new_address_gets_the_demo_library_only(self, tmp_path):
        admin, _ = _app(tmp_path, ADMIN)
        made = admin.post("/users", json={"email": GUEST}, headers=AUTH)

        assert made.status_code == 201
        assert made.json()["banks"] == ["demo"]

    def test_the_demo_library_is_a_folder_of_its_own(self, tmp_path):
        """Not a flag on the real renderings. What a stranger may hear is a
        thing somebody put there, never a thing somebody forgot to hide."""
        self._rendering(tmp_path)
        self._demo(tmp_path)
        admin, _ = _app(tmp_path, ADMIN)
        admin.post("/users", json={"email": GUEST}, headers=AUTH)

        guest, _ = _app(tmp_path, GUEST, seeded=frozenset({ADMIN}))
        tracks = guest.get("/library", headers=AUTH).json()["tracks"]

        assert [t["bank"] for t in tracks] == ["demo"]
        assert tracks[0]["song"] == "a_demo_song"

    def test_a_demo_address_cannot_fetch_a_rendering_it_was_not_granted(
            self, tmp_path):
        """Absent from the listing is not the same as refused. The route has
        to check, or the listing is only a suggestion."""
        self._rendering(tmp_path)
        admin, _ = _app(tmp_path, ADMIN)
        admin.post("/users", json={"email": GUEST}, headers=AUTH)

        guest, _ = _app(tmp_path, GUEST)
        answer = guest.get(
            "/library/a_song/ppbank/a_song.conservative.mp3", headers=AUTH)

        assert answer.status_code == 404
        assert b"real one" not in answer.content

    def test_granting_a_bank_shows_its_renderings(self, tmp_path):
        self._rendering(tmp_path)
        admin, _ = _app(tmp_path, ADMIN)
        admin.post("/users", json={"email": GUEST}, headers=AUTH)

        admin.put(f"/users/{GUEST}/banks", json={"banks": ["ppbank"]},
                  headers=AUTH)

        guest, _ = _app(tmp_path, GUEST)
        tracks = guest.get("/library", headers=AUTH).json()["tracks"]
        assert [t["bank"] for t in tracks] == ["ppbank"]

    def test_a_bank_this_machine_does_not_have_is_not_granted(self, tmp_path):
        """A row naming a bank that is not here would look like access to
        something and mean nothing until a bank of that name turned up."""
        admin, _ = _app(tmp_path, ADMIN)
        admin.post("/users", json={"email": GUEST,
                                   "banks": ["ppbank", "not_a_bank"]},
                   headers=AUTH)

        listed = admin.get("/users", headers=AUTH).json()
        row = next(u for u in listed["users"] if u["email"] == GUEST)
        assert row["banks"] == ["ppbank"]
        assert listed["grantable"] == ["demo", "ppbank"]

    def test_an_administrator_sees_everything_without_a_row_saying_so(
            self, tmp_path):
        self._rendering(tmp_path)
        self._demo(tmp_path)
        admin, _ = _app(tmp_path, ADMIN)

        tracks = admin.get("/library", headers=AUTH).json()["tracks"]

        assert {t["bank"] for t in tracks} == {"ppbank", "demo"}
        row = next(u for u in admin.get("/users", headers=AUTH).json()["users"]
                   if u["email"] == ADMIN)
        assert row["banks"] == ["demo", "ppbank"]

    def test_an_administrator_cannot_be_narrowed_from_the_panel(self, tmp_path):
        """The account that could widen it again is the one being narrowed."""
        admin, _ = _app(tmp_path, ADMIN)

        answer = admin.put(f"/users/{ADMIN}/banks", json={"banks": ["demo"]},
                           headers=AUTH)

        assert answer.status_code == 409

    def test_asking_for_nothing_leaves_the_demo_library(self, tmp_path):
        """An empty set is somebody clearing every box, which must not read as
        "everything" and must not lock the address out of the one library it
        started with."""
        admin, _ = _app(tmp_path, ADMIN)
        admin.post("/users", json={"email": GUEST, "banks": ["ppbank"]},
                   headers=AUTH)

        admin.put(f"/users/{GUEST}/banks", json={"banks": []}, headers=AUTH)

        row = next(u for u in admin.get("/users", headers=AUTH).json()["users"]
                   if u["email"] == GUEST)
        assert row["banks"] == ["demo"]


class TestUpgradingADatabaseThatPredatesLibraries:
    """Everybody already on the list had everything, because there was nothing
    to choose between. The upgrade must not read as a revocation."""

    def _old_shaped_db(self, tmp_path):
        """A database as it was written before the column existed."""
        import sqlite3
        path = tmp_path / "jobs.sqlite3"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE allowed_emails ("
                     " email TEXT PRIMARY KEY, added_at TEXT NOT NULL,"
                     " added_by TEXT NOT NULL)")
        conn.execute("INSERT INTO allowed_emails VALUES (?, ?, ?)",
                     (GUEST, AT, ADMIN))
        conn.commit()
        conn.close()
        return path

    def test_an_address_from_before_keeps_everything(self, tmp_path):
        self._old_shaped_db(tmp_path)
        out = tmp_path / "output" / "a_song" / "ppbank"
        out.mkdir(parents=True)
        (out / "a_song.wild.mp3").write_bytes(b"still theirs")

        guest, _ = _app(tmp_path, GUEST, seeded=frozenset({ADMIN}))
        tracks = guest.get("/library", headers=AUTH).json()["tracks"]

        assert [t["bank"] for t in tracks] == ["ppbank"]

    def test_an_address_added_after_the_upgrade_still_starts_at_demo(
            self, tmp_path):
        """The backfill is for rows that already existed, not for the column's
        default. A new address is still a stranger."""
        self._old_shaped_db(tmp_path)
        admin, _ = _app(tmp_path, ADMIN)

        made = admin.post("/users", json={"email": STRANGER}, headers=AUTH)

        assert made.json()["banks"] == ["demo"]

    def test_a_bank_added_later_is_included_without_touching_the_row(
            self, tmp_path):
        """What they hold is "everything", not a list copied at upgrade time."""
        self._old_shaped_db(tmp_path)
        for bank in ("ppbank", "later_bank"):
            out = tmp_path / "output" / "a_song" / bank
            out.mkdir(parents=True)
            (out / "a_song.wild.mp3").write_bytes(b"x")

        settings_banks = {"ppbank": "words_hq", "later_bank": "words_later"}
        guest, _ = _app(tmp_path, GUEST, seeded=frozenset({ADMIN}),
                        banks=settings_banks)
        tracks = guest.get("/library", headers=AUTH).json()["tracks"]

        assert {t["bank"] for t in tracks} == {"ppbank", "later_bank"}


class TestWhoseRunIsWhose:
    """A run carries the song's name, the bank it used and the files it made.

    Without this the library grant is decoration: an address holding the demo
    alone could list every run ever and fetch what those runs produced, which
    is the same audio the library refuses it.
    """

    def _a_run(self, tmp_path, by, *, song="a_song", bank="ppbank"):
        from app.jobs import Job, Stage
        out = tmp_path / "output" / song / bank
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{song}.wild.mp3").write_bytes(b"their rendering")
        return Job(id=f"job-{by}", created_at=AT, requested_by=by,
                   source_url="https://example.invalid/x", bank=bank,
                   stage=Stage.DONE, song=song, output_dir=str(out))

    def _with_run(self, tmp_path, as_who, job):
        client, users = _app(tmp_path, as_who)
        # The store the app was built around is the one on that connection.
        from app.store import open_store
        open_store(tmp_path / "jobs.sqlite3").save(job)
        return client, users

    def test_the_history_shows_only_your_own_runs(self, tmp_path):
        mine = self._a_run(tmp_path, GUEST, song="mine")
        theirs = self._a_run(tmp_path, ADMIN, song="theirs")
        admin, _ = _app(tmp_path, ADMIN)
        admin.post("/users", json={"email": GUEST}, headers=AUTH)
        from app.store import open_store
        store = open_store(tmp_path / "jobs.sqlite3")
        store.save(mine)
        store.save(theirs)

        guest, _ = _app(tmp_path, GUEST)
        seen = guest.get("/jobs", headers=AUTH).json()["jobs"]

        assert [j["song"] for j in seen] == ["mine"]

    def test_somebody_elses_run_is_not_readable(self, tmp_path):
        theirs = self._a_run(tmp_path, ADMIN, song="theirs")
        admin, _ = _app(tmp_path, ADMIN)
        admin.post("/users", json={"email": GUEST}, headers=AUTH)
        from app.store import open_store
        open_store(tmp_path / "jobs.sqlite3").save(theirs)

        guest, _ = _app(tmp_path, GUEST)

        assert guest.get(f"/jobs/{theirs.id}", headers=AUTH).status_code == 404
        assert guest.get(f"/jobs/{theirs.id}/files",
                         headers=AUTH).status_code == 404

    def test_somebody_elses_rendering_is_not_downloadable(self, tmp_path):
        """The route the library grant would otherwise be walked around."""
        theirs = self._a_run(tmp_path, ADMIN, song="theirs")
        admin, _ = _app(tmp_path, ADMIN)
        admin.post("/users", json={"email": GUEST}, headers=AUTH)
        from app.store import open_store
        open_store(tmp_path / "jobs.sqlite3").save(theirs)

        guest, _ = _app(tmp_path, GUEST)
        answer = guest.get(f"/jobs/{theirs.id}/files/theirs.wild.mp3",
                           headers=AUTH)

        assert answer.status_code == 404
        assert b"their rendering" not in answer.content

    def test_an_administrator_still_sees_every_run(self, tmp_path):
        mine = self._a_run(tmp_path, GUEST, song="mine")
        from app.store import open_store
        admin, _ = _app(tmp_path, ADMIN)
        open_store(tmp_path / "jobs.sqlite3").save(mine)

        seen = admin.get("/jobs", headers=AUTH).json()["jobs"]

        assert [j["song"] for j in seen] == ["mine"]


class TestSeeingEverybodysRuns:
    """Off by default and granted deliberately. A run names a song somebody
    chose to make, which is more personal than the list of what exists."""

    def _runs(self, tmp_path):
        from app.jobs import Job, Stage
        from app.store import open_store
        store = open_store(tmp_path / "jobs.sqlite3")
        for by, song in ((GUEST, "theirs"), (ADMIN, "mine")):
            store.save(Job(id=f"job-{song}", created_at=AT, requested_by=by,
                           source_url="https://example.invalid/x",
                           bank="ppbank", stage=Stage.DONE, song=song))

    def test_a_new_address_sees_only_its_own(self, tmp_path):
        admin, _ = _app(tmp_path, ADMIN)
        made = admin.post("/users", json={"email": GUEST}, headers=AUTH)

        assert made.json()["see_all_runs"] is False

    def test_granting_it_shows_everybodys(self, tmp_path):
        admin, _ = _app(tmp_path, ADMIN)
        admin.post("/users", json={"email": GUEST}, headers=AUTH)
        self._runs(tmp_path)

        admin.put(f"/users/{GUEST}/runs", json={"see_all_runs": True},
                  headers=AUTH)

        guest, _ = _app(tmp_path, GUEST)
        seen = guest.get("/jobs", headers=AUTH).json()["jobs"]
        assert sorted(j["song"] for j in seen) == ["mine", "theirs"]

    def test_withdrawing_it_takes_them_away_again(self, tmp_path):
        admin, _ = _app(tmp_path, ADMIN)
        admin.post("/users", json={"email": GUEST}, headers=AUTH)
        self._runs(tmp_path)
        admin.put(f"/users/{GUEST}/runs", json={"see_all_runs": True},
                  headers=AUTH)

        admin.put(f"/users/{GUEST}/runs", json={"see_all_runs": False},
                  headers=AUTH)

        guest, _ = _app(tmp_path, GUEST)
        seen = guest.get("/jobs", headers=AUTH).json()["jobs"]
        assert [j["song"] for j in seen] == ["theirs"]

    def test_an_administrator_cannot_have_it_taken_away(self, tmp_path):
        admin, _ = _app(tmp_path, ADMIN)

        answer = admin.put(f"/users/{ADMIN}/runs",
                           json={"see_all_runs": False}, headers=AUTH)

        assert answer.status_code == 409


class TestLookingAtOnePersonsRuns:
    """A convenience for somebody who can already see all of them, never a way
    to see more."""

    def _runs(self, tmp_path):
        from app.jobs import Job, Stage
        from app.store import open_store
        store = open_store(tmp_path / "jobs.sqlite3")
        for by, song in ((GUEST, "theirs"), (ADMIN, "mine")):
            store.save(Job(id=f"job-{song}", created_at=AT, requested_by=by,
                           source_url="https://example.invalid/x",
                           bank="ppbank", stage=Stage.DONE, song=song))

    def test_an_administrator_can_narrow_to_one_address(self, tmp_path):
        admin, _ = _app(tmp_path, ADMIN)
        self._runs(tmp_path)

        seen = admin.get(f"/jobs?requested_by={GUEST}",
                         headers=AUTH).json()["jobs"]

        assert [j["song"] for j in seen] == ["theirs"]

    def test_the_filter_cannot_show_what_the_check_refuses(self, tmp_path):
        """Naming somebody else's address must return nothing rather than
        their runs."""
        admin, _ = _app(tmp_path, ADMIN)
        admin.post("/users", json={"email": GUEST}, headers=AUTH)
        self._runs(tmp_path)

        guest, _ = _app(tmp_path, GUEST)
        seen = guest.get(f"/jobs?requested_by={ADMIN}",
                         headers=AUTH).json()["jobs"]

        assert seen == []


class TestInvitations:
    """A link that admits exactly one account, to the demo library.

    It is the only route that lets in somebody not already on the allowlist,
    so what it does not skip matters as much as what it does.
    """

    def test_only_an_administrator_can_make_one(self, tmp_path):
        admin, _ = _app(tmp_path, ADMIN)
        admin.post("/users", json={"email": GUEST}, headers=AUTH)

        guest, _ = _app(tmp_path, GUEST)

        assert guest.post("/invitations", headers=AUTH).status_code == 403

    def test_redeeming_admits_the_address_google_verified(self, tmp_path):
        """Never one the caller supplies, or a link could be redeemed on
        somebody else's behalf."""
        admin, _ = _app(tmp_path, ADMIN)
        token = admin.post("/invitations", headers=AUTH).json()["token"]

        # A stranger: not seeded, not granted, not an administrator.
        stranger, _ = _app(tmp_path, STRANGER, seeded=frozenset({ADMIN}))
        answer = stranger.post(f"/invitations/{token}/accept", headers=AUTH)

        assert answer.status_code == 200
        assert answer.json() == {"email": STRANGER, "banks": ["demo"]}

    def test_it_grants_the_demo_library_and_nothing_else(self, tmp_path):
        admin, _ = _app(tmp_path, ADMIN)
        out = tmp_path / "output" / "a_song" / "ppbank"
        out.mkdir(parents=True)
        (out / "a_song.wild.mp3").write_bytes(b"not for a stranger")
        token = admin.post("/invitations", headers=AUTH).json()["token"]

        stranger, _ = _app(tmp_path, STRANGER, seeded=frozenset({ADMIN}))
        stranger.post(f"/invitations/{token}/accept", headers=AUTH)

        after, _ = _app(tmp_path, STRANGER, seeded=frozenset({ADMIN}))
        tracks = after.get("/library", headers=AUTH).json()["tracks"]
        assert tracks == []

    def test_one_registration_only(self, tmp_path):
        admin, _ = _app(tmp_path, ADMIN)
        token = admin.post("/invitations", headers=AUTH).json()["token"]
        first, _ = _app(tmp_path, STRANGER, seeded=frozenset({ADMIN}))
        first.post(f"/invitations/{token}/accept", headers=AUTH)

        second, _ = _app(tmp_path, GUEST, seeded=frozenset({ADMIN}))
        answer = second.post(f"/invitations/{token}/accept", headers=AUTH)

        assert answer.status_code == 404

    def test_a_link_nobody_issued_is_refused(self, tmp_path):
        stranger, _ = _app(tmp_path, STRANGER, seeded=frozenset({ADMIN}))

        answer = stranger.post("/invitations/made-up/accept", headers=AUTH)

        assert answer.status_code == 404

    def test_redeeming_without_a_google_token_is_refused(self, tmp_path):
        """The invitation says a stranger may join, not that anybody may
        claim to be anyone."""
        admin, _ = _app(tmp_path, ADMIN)
        token = admin.post("/invitations", headers=AUTH).json()["token"]

        stranger, _ = _app(tmp_path, STRANGER, seeded=frozenset({ADMIN}))
        answer = stranger.post(f"/invitations/{token}/accept")

        assert answer.status_code == 401

    def test_an_expired_link_stops_working(self, tmp_path):
        from app.store import open_store
        from app.users import open_invitations
        admin, _ = _app(tmp_path, ADMIN)
        token = admin.post("/invitations", headers=AUTH).json()["token"]
        conn = open_store(tmp_path / "jobs.sqlite3").connection
        conn.execute("UPDATE invitations SET expires_at = ?",
                     ("2000-01-01T00:00:00+00:00",))
        conn.commit()

        stranger, _ = _app(tmp_path, STRANGER, seeded=frozenset({ADMIN}))
        answer = stranger.post(f"/invitations/{token}/accept", headers=AUTH)

        assert answer.status_code == 404

    def test_an_unused_link_can_be_withdrawn(self, tmp_path):
        admin, _ = _app(tmp_path, ADMIN)
        token = admin.post("/invitations", headers=AUTH).json()["token"]

        admin.delete(f"/invitations/{token}", headers=AUTH)

        stranger, _ = _app(tmp_path, STRANGER, seeded=frozenset({ADMIN}))
        assert stranger.post(f"/invitations/{token}/accept",
                             headers=AUTH).status_code == 404

    def test_two_links_are_not_the_same_link(self, tmp_path):
        admin, _ = _app(tmp_path, ADMIN)

        first = admin.post("/invitations", headers=AUTH).json()["token"]
        second = admin.post("/invitations", headers=AUTH).json()["token"]

        assert first != second
        assert len(first) > 20


class TestOpeningYourOwnLink:
    """Somebody already allowed in gains nothing from a link, so spending one
    on them burns it for nobody. Checking that a link works by opening it is
    the obvious thing to do, and it used to be what destroyed it."""

    def test_an_existing_member_does_not_spend_it(self, tmp_path):
        admin, _ = _app(tmp_path, ADMIN)
        token = admin.post("/invitations", headers=AUTH).json()["token"]

        # The owner opens their own link to see whether it works.
        opened = admin.post(f"/invitations/{token}/accept", headers=AUTH)
        assert opened.status_code == 200

        # It still admits the person it was meant for.
        stranger, _ = _app(tmp_path, STRANGER, seeded=frozenset({ADMIN}))
        answer = stranger.post(f"/invitations/{token}/accept", headers=AUTH)
        assert answer.status_code == 200
        assert answer.json()["banks"] == ["demo"]

    def test_it_does_not_narrow_somebody_who_already_has_more(self, tmp_path):
        """The grant is 'demo', and an existing member has at least that."""
        admin, _ = _app(tmp_path, ADMIN)
        admin.post("/users", json={"email": GUEST, "banks": ["ppbank"]},
                   headers=AUTH)
        token = admin.post("/invitations", headers=AUTH).json()["token"]

        guest, _ = _app(tmp_path, GUEST)
        guest.post(f"/invitations/{token}/accept", headers=AUTH)

        row = next(u for u in admin.get("/users", headers=AUTH).json()["users"]
                   if u["email"] == GUEST)
        assert row["banks"] == ["ppbank"]
