"""Fetch a song from a URL into input/, keeping the video and its origin.

    python -m song_generator.fetch "https://example.com/watch?v=abc123"

A separate command on purpose. The renderer never takes a URL, because the
network must stay out of the render path: a render should not be able to fail
because a site changed its layout overnight. Fetching happens once, here, and
everything downstream reads the file.

Two jobs beyond the convenience of not downloading by hand:

1. **The full file is kept, video included.** The plan for a rendered song is
   to cut the original music video to fit it, and that needs the video at the
   resolution the site holds. Several early songs were downloaded as
   convenience files at 426x238 and are useless for that. The pipeline takes
   the audio it needs out of the mp4 as it always has.

2. **The origin is recorded, twice.** Nothing else in this repo does, and 21
   of the 23 indexed songs have no known address today. The download embeds
   the page URL into the file itself (in the `comment` tag, so ffprobe
   recovers it from the file alone), and a row is appended to
   `input/SOURCES.md` so the index fills itself for everything fetched from
   now on.

The filename is the slug. `util.slugify` of the input filename names the
work/ directory and keys everything the tool knows about a song, and a title
fetched from the web can contain every character Windows forbids. So the
target name is decided here, from the slugified title, before anything is
downloaded, and the site's own spelling never touches the filesystem. An
illegal character in a derived filename once made a write throw and silently
abandoned an entire source; this path cannot produce one.

An existing target is never overwritten and never duplicated with a "(1)"
name. It is reported as already present and returned as-is, so fetching the
same address twice is idempotent rather than destructive. Two different
pages can slugify to the same name; when the index already records a
different address for the slug, the fetch flags the conflict and records
nothing, instead of pairing one song's file with another song's address.

The GUI-facing surface is `fetch()`, which returns a `FetchResult` rather
than printing, and `main()` is a thin argparse wrapper over it. `--json`
emits the same fields the dataclass carries.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import fmt_duration, slugify

EXIT_OK = 0
EXIT_ERROR = 2

SOURCES_NAME = "SOURCES.md"

# Matches the hand-written table in input/SOURCES.md column for column, so
# appended rows and hand-added rows are the same shape.
SOURCES_TABLE_HEADER = "| Name | Local file | Address |"

SOURCES_PREAMBLE = """\
# Where each song came from

Private index, one row per song: the slug the tool keys on, the local file,
and the address it came from. Lives beside the audio in a gitignored
directory, so cloning the repo publishes none of it. Rows are appended by
`python -m song_generator.fetch` and by hand; `unknown` means nobody has
written the address down yet.

## Songs

"""

# Best video plus best audio, merged. Resolution matters: the point of
# keeping the video is cutting it to fit the rendered song later, and a
# convenience download at 426x238 cannot be cut into anything.
_FORMAT = "bestvideo*+bestaudio/best"


class FetchError(Exception):
    """The fetch failed in a way the caller should report, not crash on."""


@dataclass(frozen=True)
class FetchResult:
    """What a fetch produced, shaped for a GUI rather than for stdout.

    `width` and `height` are None when the source had no video stream, and
    `duration_s` is None on the rare page that does not state one.
    `already_present` means the target existed and nothing was downloaded;
    `path` then points at the existing file. `conflicting_url` is the
    address the index already records for the slug when it differs from
    `url`: the file on disk belongs to that recorded address, two titles
    merely slugified to the same name, and nothing was downloaded or
    recorded.
    """

    path: Path
    slug: str
    title: str
    uploader: str
    url: str
    duration_s: float | None
    width: int | None
    height: int | None
    already_present: bool
    conflicting_url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "slug": self.slug,
            "title": self.title,
            "uploader": self.uploader,
            "url": self.url,
            "duration_s": self.duration_s,
            "width": self.width,
            "height": self.height,
            "already_present": self.already_present,
            "conflicting_url": self.conflicting_url,
        }


# Which YouTube client to ask as, in order, and why there is more than one.
#
# The default is best: it is what yt-dlp picks for itself and it offers the
# high resolutions _FORMAT wants. But YouTube serves some videos nothing at all
# through it -- the page loads and only storyboards come back, so the failure
# reads as "This video is not available" when the video is fine and a browser
# plays it happily. Measured on three children's songs in a row.
#
# Asking as the Android app gets those, at 360p with audio rather than at the
# best available. That is a real loss for cutting the video afterwards and no
# loss at all for the singing, which is the part this pipeline needs, so it is
# a fallback rather than the default: try for quality, settle for existing.
_CLIENTS: tuple[dict[str, Any], ...] = (
    {},
    {"extractor_args": {"youtube": {"player_client": ["android"]}}},
)


def _probe(url: str) -> dict[str, Any]:
    """Ask the site what the URL holds, without downloading. Network."""
    import yt_dlp

    last: Exception | None = None
    for client in _CLIENTS:
        opts = {"quiet": True, "no_warnings": True, "noplaylist": True,
                "format": _FORMAT, **client}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            return dict(info or {})
        except Exception as exc:
            last = exc
    raise last if last else FetchError(f"could not read {url}")


def _has_media(info: dict[str, Any]) -> bool:
    """Whether anything in this page's formats is actually a song.

    Storyboards are the thumbnail grids every YouTube page carries, and they
    are formats like any other, so "it returned formats" is not the same as
    "there is something to download".
    """
    for fmt in info.get("formats") or []:
        if fmt.get("protocol") == "mhtml" or fmt.get("ext") == "mhtml":
            continue
        if fmt.get("acodec", "none") != "none" or fmt.get("vcodec", "none") != "none":
            return True
    return False


def _probe_without_format_filter(url: str) -> dict[str, Any]:
    """Ask what formats exist at all, rather than which one to take. Network.

    Separate from _probe in two ways that both matter here. No format filter,
    because _FORMAT fails selection before the formats can be looked at, and
    the formats are the question. And the web client, because the default one
    gives up before reporting any.
    """
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extractor_args": {"youtube": {"player_client": ["web"]}},
        # Omitting a format is not the same as not selecting one: yt-dlp then
        # applies its own default and raises "Requested format is not
        # available" on exactly the pages this exists to describe, which is
        # how the first version of this silently never fired.
        "ignore_no_formats_error": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return dict(ydl.extract_info(url, download=False) or {})


def _diagnose(url: str, exc: Exception) -> str:
    """A truer sentence than the one yt-dlp hands back, where there is one.

    "This video is not available" covers two different situations and reads
    like the first: the page is gone, or the page is fine and YouTube is
    withholding every playable stream from a non-browser client. Told the
    first when it is the second, somebody edits the address, tries the same
    link again, and concludes the tool is broken. It is not; it is being
    refused.

    The default client cannot tell them apart, because it fails before it
    reports any formats. The web client extracts the page and answers with
    storyboards alone, which is the signal. It costs one extra request, only
    ever on the path that has already failed.
    """
    generic = f"could not read {url}: {exc}"
    try:
        info = _probe_without_format_filter(url)
    except Exception:
        return generic

    if info and not _has_media(info):
        return (f"{url} loads, but the site offered this tool no audio or "
                f"video for it, only thumbnails. No change to the address "
                f"helps. A browser can still play it, so saving the audio "
                f"another way and passing that file works.")
    return generic


def _download(url: str, target: Path) -> None:
    """Download best video plus audio, merged to mp4 at `target`. Network.

    The page URL is embedded into the file's own metadata, so the file
    carries its origin even if the index row is lost. It survives only as
    the `comment` tag: yt-dlp writes the URL to both `purl` and `comment`,
    but ffmpeg's mp4 muxer has no mapping for `purl` and silently drops it,
    and every file here is merged to mp4. yt-dlp downloads to `.part` files
    and renames on completion, so an interrupted run never leaves a
    truncated file at the final name.
    """
    import yt_dlp

    # The same fallback the probe makes, for the same reason. Without it a
    # video that probed only because the Android client answered would fail
    # here instead, which is a worse place to fail: after the caller has been
    # told the title, the duration and where the file is going.
    last: Exception | None = None
    for client in _CLIENTS:
        opts = {
            "format": _FORMAT,
            "merge_output_format": "mp4",
            # The extension placeholder is required; merging rewrites it to mp4.
            "outtmpl": str(target.with_suffix("")) + ".%(ext)s",
            "noplaylist": True,
            "postprocessors": [{"key": "FFmpegMetadata"}],
            "quiet": True,
            "no_warnings": True,
            **client,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            return
        except Exception as exc:
            last = exc
    if last:
        raise last


def recorded_address(slug: str, sources: Path) -> str | None:
    """The address the index already holds for `slug`, or None.

    `unknown` counts as None: it is the documented placeholder for an
    address nobody has written down, not an address that could contradict
    a probed one.
    """
    if not sources.is_file():
        return None
    for line in sources.read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith(f"| `{slug}` |"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[2] and cells[2] != "unknown":
            return cells[2]
        return None
    return None


def record_source(slug: str, local: Path, address: str, sources: Path) -> bool:
    """Append one row to the sources index; never a duplicate.

    Returns True when a row was added. The row goes after the last existing
    table row, not at the end of the file, because the real index carries
    prose sections below its table and a row appended at EOF would land
    outside the table it belongs to. A file that does not exist yet is
    created with its header.
    """
    row = f"| `{slug}` | `{local}` | {address} |"

    if not sources.is_file():
        sources.write_text(
            SOURCES_PREAMBLE + SOURCES_TABLE_HEADER + "\n|---|---|---|\n" + row + "\n",
            encoding="utf-8",
        )
        return True

    text = sources.read_text(encoding="utf-8")
    if f"| `{slug}` |" in text:
        return False

    lines = text.splitlines()
    last_row = max(
        (i for i, line in enumerate(lines) if line.lstrip().startswith("|")),
        default=None,
    )
    if last_row is None:
        lines += ["", SOURCES_TABLE_HEADER, "|---|---|---|", row]
    else:
        lines.insert(last_row + 1, row)
    sources.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def fetch(url: str, out_dir: str | Path = "input") -> FetchResult:
    """Fetch one song into `out_dir` and record where it came from.

    Returns a FetchResult either way: freshly downloaded, or already present
    and left untouched. Raises FetchError when the site refuses, the address
    is a playlist rather than one song, or the download produced nothing.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    try:
        info = _probe(url)
    except FetchError:
        raise
    except Exception as exc:  # yt-dlp raises its own hierarchy; wrap it once.
        raise FetchError(_diagnose(url, exc)) from exc

    if info.get("_type") == "playlist":
        raise FetchError(
            f"{url} is a playlist, not one song; give the song's own page")

    title = str(info.get("title") or "").strip()
    slug = slugify(title or url)
    target = out / f"{slug}.mp4"
    address = str(info.get("webpage_url") or url)
    uploader = str(info.get("uploader") or info.get("channel") or "")
    duration = info.get("duration")
    width, height = info.get("width"), info.get("height")

    already = target.exists()
    conflict: str | None = None
    if already:
        # Two different pages can slugify to the same name. When the index
        # already ties this slug to another address, the file on disk is
        # that other song, and pairing it with this address would
        # misattribute both.
        recorded = recorded_address(slug, out / SOURCES_NAME)
        if recorded is not None and recorded != address:
            conflict = recorded
    if not already:
        try:
            _download(url, target)
        except Exception as exc:
            raise FetchError(f"download failed for {url}: {exc}") from exc
        if not target.is_file():
            raise FetchError(
                f"download reported success but {target} does not exist")

    result = FetchResult(
        path=target,
        slug=slug,
        title=title,
        uploader=uploader,
        url=address,
        duration_s=float(duration) if duration is not None else None,
        width=int(width) if width is not None else None,
        height=int(height) if height is not None else None,
        already_present=already,
        conflicting_url=conflict,
    )
    if conflict is None:
        # Recorded even when the file was already there: the index row may
        # be the missing half, and this call knows the address.
        record_source(slug, target, address, out / SOURCES_NAME)
    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="song_generator.fetch",
        description="Fetch a song from a URL into input/, keeping the video "
                    "and recording where it came from.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("url", help="the song's page address")
    p.add_argument("-o", "--out", type=Path, default=Path("input"),
                   help="where the file and the sources index live")
    p.add_argument("--json", action="store_true",
                   help="print the result as JSON (the FetchResult fields)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        result = fetch(args.url, out_dir=args.out)
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    conflicted = result.conflicting_url is not None
    if conflicted:
        # The name is taken by another song. The usual advice, delete the
        # file to fetch again, would destroy that song, so it is withheld
        # and the exit code says the fetch did not happen.
        print(f"warning: {result.path} is already taken by another song",
              file=sys.stderr)
        print(f"  recorded address   {result.conflicting_url}",
              file=sys.stderr)
        print(f"  requested address  {result.url}", file=sys.stderr)
        print("  two titles share one slug; nothing was downloaded or "
              "recorded, and deleting the file would lose the recorded "
              "song", file=sys.stderr)

    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
        return EXIT_ERROR if conflicted else EXIT_OK

    if result.already_present:
        print(f"  already here  {result.path}")
        if not conflicted:
            print("  nothing downloaded; delete the file first to fetch it again")
    else:
        print(f"  fetched   {result.path}")
    print(f"  title     {result.title}")
    if result.uploader:
        print(f"  uploader  {result.uploader}")
    if result.duration_s is not None:
        print(f"  length    {fmt_duration(result.duration_s)}")
    if result.width and result.height:
        print(f"  video     {result.width}x{result.height}")
    print(f"  source    {result.url}")
    if not conflicted:
        print(f"  recorded  {args.out / SOURCES_NAME}")
    return EXIT_ERROR if conflicted else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
