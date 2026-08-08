"""Turning a link into a file, and the two answers that are not success.

No network: the fetcher is injected. What matters here is that a repeat
request works, and that a slug collision is refused rather than quietly
rendering somebody else's song.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from app.songs import SongError, prepare


@dataclass
class _Result:
    path: Path
    already_present: bool = False
    conflicting_url: str | None = None


def _fetcher(result: _Result):
    def fetch(url: str, out_dir: Path) -> _Result:
        return result
    return fetch


def test_a_fetched_song_comes_back_as_a_path(tmp_path):
    song = tmp_path / "song.mp4"
    song.write_bytes(b"x")

    got = prepare("https://example.invalid/watch?v=a", tmp_path,
                  _fetcher(_Result(path=song)))

    assert got == song


def test_a_song_already_here_is_not_an_error(tmp_path):
    """The same link asked for twice should render twice. Refusing the second
    would make re-running a song at different settings impossible."""
    song = tmp_path / "song.mp4"
    song.write_bytes(b"x")

    got = prepare("https://example.invalid/watch?v=a", tmp_path,
                  _fetcher(_Result(path=song, already_present=True)))

    assert got == song


def test_a_slug_collision_is_refused_and_names_the_other_address(tmp_path):
    """Two different videos whose titles slugify the same. The file on disk
    belongs to the other one, so rendering it would make a song out of audio
    nobody asked for."""
    song = tmp_path / "song.mp4"
    song.write_bytes(b"x")
    other = "https://example.invalid/watch?v=THEOTHER"

    with pytest.raises(SongError) as refused:
        prepare("https://example.invalid/watch?v=a", tmp_path,
                _fetcher(_Result(path=song, already_present=True,
                                 conflicting_url=other)))

    assert other in str(refused.value)


def test_a_fetch_failure_becomes_a_readable_refusal(tmp_path):
    """The pipeline's own error already says why: a playlist address, a
    removed video, no network. It is passed through rather than replaced."""
    def angry(url: str, out_dir: Path):
        raise RuntimeError("that link is a playlist, not a video")

    with pytest.raises(SongError, match="playlist"):
        prepare("https://example.invalid/list", tmp_path, angry)


def test_a_success_that_left_no_file_is_caught(tmp_path):
    """Better than handing the pipeline a path to nothing and letting it fail
    minutes later with a message about a missing input."""
    with pytest.raises(SongError, match="no file"):
        prepare("https://example.invalid/x", tmp_path,
                _fetcher(_Result(path=tmp_path / "never-written.mp4")))
