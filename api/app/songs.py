"""Turning a link into a file on disk the pipeline can read.

Thin over the pipeline's own fetch command, which already downloads a song,
keeps the video, writes the source address into the file, and records the row
in the index. None of that is repeated here.

What this adds is the edge's answer to the two outcomes a caller has to be told
apart from success:

- The file was already there, which is not an error. The same link asked for
  twice should render twice, not refuse the second time.
- Two different videos whose titles slugify to the same name. The file on disk
  belongs to the other one, so rendering it would quietly make a song from
  audio nobody asked for. That is refused, loudly, with both addresses named.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol


class SongError(Exception):
    """The link could not become a file. The message is safe to show."""


class _Fetched(Protocol):
    """The part of the pipeline's FetchResult this module reads.

    Only what is actually read. `already_present` is deliberately absent: a
    song already on disk is handled by doing nothing about it, so declaring
    the field would tie this to a name it never consults.

    Read-only members, because that is what this module needs and because a
    frozen dataclass cannot satisfy a protocol that declares settable ones.
    """

    @property
    def path(self) -> Path: ...

    @property
    def conflicting_url(self) -> str | None: ...


def prepare(url: str, out_dir: Path,
            fetcher: Callable[..., Any] | None = None) -> Path:
    """Get the song for `url` onto disk and return where it landed.

    `fetcher` is injected so this can be exercised without a network, and so
    the pipeline is imported only when it is really wanted.
    """
    if fetcher is None:
        # Imported here rather than at module level so this package can be
        # imported, and most of it tested, without the pipeline on the path.
        from song_generator.fetch import fetch

        fetcher = fetch

    try:
        result: _Fetched = fetcher(url, out_dir)
    except Exception as exc:
        # Includes the pipeline's own FetchError, which already carries a
        # readable reason: a playlist address, a removed video, no network.
        raise SongError(str(exc)) from exc

    if result.conflicting_url:
        raise SongError(
            "that link's title matches a song already here, but a different "
            f"one: the file belongs to {result.conflicting_url}. Rename or "
            "remove it before fetching this."
        )

    if not result.path.is_file():
        raise SongError("the fetch reported success but left no file")

    return result.path
