"""Settings from a file, so they outlive the shell that started the service."""

from __future__ import annotations

from app.config import load_settings, read_env_file


def _write(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


class TestReadingTheFile:
    def test_a_missing_file_is_not_an_error(self, tmp_path):
        """A clone that has never been configured still starts."""
        assert read_env_file(tmp_path / "nothing-here") == {}

    def test_comments_and_blank_lines_are_skipped(self, tmp_path):
        path = _write(tmp_path, "# who may administer this\n\nA=1\n")

        assert read_env_file(path) == {"A": "1"}

    def test_quotes_are_how_a_value_holds_a_space(self, tmp_path):
        path = _write(tmp_path, 'A="one, two"\nB=\'three\'\nC=bare\n')

        assert read_env_file(path) == {"A": "one, two", "B": "three",
                                       "C": "bare"}

    def test_a_value_may_hold_an_equals_sign(self, tmp_path):
        path = _write(tmp_path, "A=x=y=z\n")

        assert read_env_file(path) == {"A": "x=y=z"}


class TestWhichSourceWins:
    def test_the_file_supplies_what_the_environment_does_not(self, tmp_path):
        path = _write(tmp_path, "SONGGEN_GOOGLE_CLIENT_ID=from-the-file\n")

        settings = load_settings(env={}, env_file=path)

        assert settings.google_client_id == "from-the-file"

    def test_the_environment_wins(self, tmp_path):
        """A value exported for one run is meant to apply to that run, and a
        file that overrode it would make the override do nothing."""
        path = _write(tmp_path, "SONGGEN_GOOGLE_CLIENT_ID=from-the-file\n")

        settings = load_settings(
            env={"SONGGEN_GOOGLE_CLIENT_ID": "from-the-shell"}, env_file=path)

        assert settings.google_client_id == "from-the-shell"

    def test_lists_read_the_same_from_either_source(self, tmp_path):
        path = _write(
            tmp_path,
            'SONGGEN_ADMIN_EMAILS="Owner@Example.invalid, friend@example.invalid"\n'
            "SONGGEN_ALLOWED_ORIGINS=https://a.invalid,https://b.invalid\n")

        settings = load_settings(env={}, env_file=path)

        assert settings.admin_emails == frozenset(
            {"owner@example.invalid", "friend@example.invalid"})
        assert settings.allowed_origins == ("https://a.invalid",
                                            "https://b.invalid")

    def test_a_configured_edge_reports_itself_configured(self, tmp_path):
        path = _write(tmp_path,
                      "SONGGEN_GOOGLE_CLIENT_ID=an-id\n"
                      "SONGGEN_ADMIN_EMAILS=owner@example.invalid\n")

        assert load_settings(env={}, env_file=path).auth_configured is True


class TestNotLeakingThisMachineIntoATest:
    def test_an_explicit_environment_is_the_whole_environment(self, tmp_path):
        """Otherwise a caller describing an empty environment is handed
        whatever happens to be configured on the machine, and a test passes or
        fails depending on whose machine it runs on. Three did."""
        real = tmp_path / ".env"
        real.write_text("SONGGEN_GOOGLE_CLIENT_ID=from-this-machine\n",
                        encoding="utf-8")

        # No file named, and an environment given: the file is not consulted.
        assert load_settings(env={}).google_client_id == ""
        # Named explicitly: it is.
        assert load_settings(env={}, env_file=real).google_client_id == (
            "from-this-machine")
