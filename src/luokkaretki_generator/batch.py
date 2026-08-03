"""Render many songs in one command.

    python -m luokkaretki_generator.batch "input/*.mp4"
    python -m luokkaretki_generator.batch "input/*.mp4" --mimicry 0.45

This is the part that genuinely wanted automating, and it is a script rather
than an agent because nothing in it needs judgement: the inputs are a glob, the
work is deterministic, and the only decision -- whether a result sounds good --
cannot be made by anything without ears.

One failure does not end the batch. A song that comes back Mode B, or one whose
separation dies, is recorded and the rest continue.
"""

from __future__ import annotations

import argparse
import glob
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Result:
    name: str
    ok: bool = False
    mode_b: bool = False
    seconds: float = 0.0
    units: int = 0
    slots: str = ""
    mimicry: float = 0.0
    error: str = ""


def expand(patterns: list[str]) -> list[Path]:
    found: list[Path] = []
    for pattern in patterns:
        hits = [Path(p) for p in glob.glob(pattern)]
        if hits:
            found.extend(sorted(hits))
        elif Path(pattern).is_file():
            found.append(Path(pattern))
        else:
            print(f"  warning: nothing matched {pattern!r}", file=sys.stderr)

    seen, out = set(), []
    for p in found:
        key = p.resolve()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="luokkaretki_generator.batch",
        description="Render many songs in one go.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("songs", nargs="+", help="files or globs, e.g. 'input/*.mp4'")
    p.add_argument("-o", "--out", type=Path, default=Path("output"))
    p.add_argument("--mimicry", type=float, default=None,
                   help="one file per song at this setting, instead of the full sweep")
    p.add_argument("--bank", default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--continue-on-error", action="store_true", default=True,
                   help="kept for clarity; the batch always continues")
    return p


def main(argv: list[str] | None = None) -> int:
    from .cli import main as render_one

    args = build_parser().parse_args(argv)
    songs = expand(args.songs)
    if not songs:
        print("error: no songs matched", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"  {len(songs)} songs -> {args.out.resolve()}\n")

    results: list[Result] = []
    for i, song in enumerate(songs, start=1):
        print(f"  [{i:>3}/{len(songs)}] {song.name}", flush=True)
        started = time.perf_counter()
        result = Result(name=song.name)

        argv_one = [str(song), "--rows", "0",
                    "-o", str(args.out / f"{song.stem}.mp3")]
        if args.mimicry is not None:
            argv_one += ["--mimicry", str(args.mimicry)]
        if args.bank:
            argv_one += ["--bank", args.bank]
        if args.seed is not None:
            argv_one += ["--seed", str(args.seed)]

        try:
            code = render_one(argv_one)
            result.ok = code == 0
            result.mode_b = code == 3
            if not result.ok and not result.mode_b:
                result.error = f"exit {code}"
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            traceback.print_exc(file=sys.stderr)

        result.seconds = time.perf_counter() - started
        results.append(result)

    done = [r for r in results if r.ok]
    refused = [r for r in results if r.mode_b]
    failed = [r for r in results if not r.ok and not r.mode_b]

    print(f"\n  {len(done)} rendered, {len(refused)} refused as Mode B, "
          f"{len(failed)} failed")
    print(f"  {sum(r.seconds for r in results) / 60:.1f} minutes total\n")

    for r in results:
        mark = "ok " if r.ok else ("B  " if r.mode_b else "ERR")
        note = "" if r.ok else ("  no vocals to borrow" if r.mode_b else f"  {r.error}")
        print(f"    {mark} {r.seconds:6.1f}s  {r.name}{note}")

    if refused:
        print("\n  Mode B songs have no vocal to borrow the melody from, so they are")
        print("  refused rather than botched. See docs/TODO.md.")
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
