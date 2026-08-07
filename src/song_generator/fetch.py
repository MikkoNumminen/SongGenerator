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
   the page URL into the file itself (yt-dlp writes it as the `purl` tag, so
   ffprobe recovers it from the file alone), and a row is appended to
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
same address twice is idempotent rather than destructive.

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
    `path` then points at the existing file.
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
        }


def _probe(url: str) -> dict[str, Any]:
    """Ask the site what the URL holds, without downloading. Network."""
    import yt_dlp

    opts = {"quiet": True, "noplaylist": True, "format": _FORMAT}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return dict(info or {})


def _download(url: str, target: Path) -> None:
    """Download best video plus audio, merged to mp4 at `target`. Network.

    The page URL is embedded into the file's own metadata (the `purl` tag),
    so the file carries its origin even if the index row is lost. yt-dlp
    downloads to `.part` files and renames on completion, so an interrupted
    run never leaves a truncated file at the final name.
    """
    import yt_dlp

    opts = {
        "format": _FORMAT,
        "merge_output_format": "mp4",
        # The extension placeholder is required; merging rewrites it to mp4.
        "outtmpl": str(target.with_suffix("")) + ".%(ext)s",
        "noplaylist": True,
        "postprocessors": [{"key": "FFmpegMetadata"}],
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])


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
        raise FetchError(f"could not read {url}: {exc}") from exc

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
    )
    # Recorded even when the file was already there: the index row may be
    # the missing half, and this call knows the address.
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

    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
        return EXIT_OK

    if result.already_present:
        print(f"  already here  {result.path}")
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
    print(f"  recorded  {args.out / SOURCES_NAME}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
