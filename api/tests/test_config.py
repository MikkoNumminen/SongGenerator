"""Settings, and the shapes of misconfiguration worth naming.

The interesting cases are the ones where a wrong value would not raise. An
allowlist that silently parses to empty locks everybody out; one that keeps a
stray space matches nobody. Both look like working configuration from the
outside, so both are asserted here.
"""

from __future__ import annotations

from pathlib import Path

from app.config import load_settings


def test_the_defaults_point_at_this_repository():
    """The edge runs on the machine that holds the pipeline and its audio.
    There is no deployment where those live apart."""
    settings = load_settings({})

    assert (settings.repo_root / "src" / "song_generator").is_dir()


def test_the_database_sits_with_the_pipeline_working_data():
    """Beside `work/`, which is gitignored already. It is machine state, and a
    stray commit of a job history would carry song titles and local paths."""
    settings = load_settings({})

    assert settings.database_path.parent.name == "work"


def test_an_allowlist_is_split_trimmed_and_lowercased():
    """Addresses get pasted into an env var by hand, with whatever spacing and
    capitalisation. A list that matched nobody because of a space would look
    exactly like a list that was working."""
    settings = load_settings({
        "SONGGEN_ALLOWED_EMAILS": " Owner@Example.Invalid , second@example.invalid ",
    })

    assert settings.allowed_emails == frozenset(
        {"owner@example.invalid", "second@example.invalid"})


def test_an_empty_allowlist_stays_empty_rather_than_becoming_one_blank_entry():
    """`"".split(",")` is `[""]`, and an allowlist holding one empty string
    would be non-empty, so `auth_configured` would claim sign-in was possible."""
    settings = load_settings({"SONGGEN_ALLOWED_EMAILS": ""})

    assert settings.allowed_emails == frozenset()
    assert settings.auth_configured is False


def test_auth_needs_both_a_client_and_a_list():
    """Either half missing means nobody can sign in, and the front end should
    be told that rather than showing a sign-in that cannot work."""
    only_client = load_settings({"SONGGEN_GOOGLE_CLIENT_ID": "abc.apps.googleusercontent.com"})
    only_list = load_settings({"SONGGEN_ALLOWED_EMAILS": "owner@example.invalid"})
    both = load_settings({
        "SONGGEN_GOOGLE_CLIENT_ID": "abc.apps.googleusercontent.com",
        "SONGGEN_ALLOWED_EMAILS": "owner@example.invalid",
    })

    assert only_client.auth_configured is False
    assert only_list.auth_configured is False
    assert both.auth_configured is True


def test_origins_are_split_the_same_way():
    settings = load_settings({
        "SONGGEN_ALLOWED_ORIGINS": "https://a.example , https://b.example",
    })

    assert settings.allowed_origins == ("https://a.example", "https://b.example")


def test_no_origins_configured_is_an_empty_tuple_not_a_blank_one():
    """An empty entry would be sent to the browser as an origin of "", which
    matches nothing and is harder to notice than no CORS at all."""
    assert load_settings({}).allowed_origins == ()


def test_everything_can_be_pointed_somewhere_else():
    settings = load_settings({
        "SONGGEN_REPO_ROOT": "/somewhere/else",
        "SONGGEN_DATABASE_PATH": "/tmp/jobs.sqlite3",
    })

    assert settings.repo_root == Path("/somewhere/else")
    assert settings.database_path == Path("/tmp/jobs.sqlite3")
