"""Set bare-syllable clips aside: keep them, stop using them.

    python -m luokkaretki_generator.set_aside
    python -m luokkaretki_generator.set_aside --restore

Syllables were worth trying -- they map onto a melody 1:1 and can spell words
that were never recorded intact -- but in practice they crowd out the words. A
clip of "pas" fills a slot as neatly as one of "paska" and says nothing, and a
track full of them stops being about paska, perse, pillu, pornolehti and eee
paviaani.

So they are renamed rather than deleted:

    pas.wav   ->   SYL_pas.wav

SYL_ does not parse as a bank word, so those clips leave the bank without
anything being thrown away, and --restore puts them back. Identifying them by
ear was real work and it stays recorded in the name.

Shouts are exempt: eee is a genuine utterance, not a fragment of one, and it is
the only odd-length unit in the bank -- the single leftover slot an odd phrase
produces has nothing else to fill it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config
from .build_bank import parse_phrase

SET_ASIDE = "SYL_"


def is_bare_syllable(stem: str) -> bool:
    """True when a name is only syllables -- no whole word, no shout."""
    parsed = parse_phrase(stem)
    if parsed is None:
        return False
    words = parsed[0]
    return bool(words) and all(
        w not in config.WORD_SYLLABLES for w in words
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="luokkaretki_generator.set_aside",
        description="Keep syllable clips but take them out of the bank.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--folder", type=Path, default=Path("words/candidates"))
    p.add_argument("--restore", action="store_true", help="put them back into use")
    p.add_argument("--dry-run", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    folder = args.folder
    if not folder.is_dir():
        print(f"error: {folder} not found", file=sys.stderr)
        return 2

    moved: list[tuple[str, str]] = []

    if args.restore:
        for path in sorted(folder.glob(f"{SET_ASIDE}*.wav")):
            target = folder / path.name[len(SET_ASIDE):]
            if target.exists():
                continue
            moved.append((path.name, target.name))
            if not args.dry_run:
                path.rename(target)
    else:
        for path in sorted(folder.glob("*.wav")):
            if path.name.startswith(("AI_", "TODO_", "EEE_then__", "THEN_", SET_ASIDE)):
                continue
            if not is_bare_syllable(path.stem):
                continue
            target = folder / f"{SET_ASIDE}{path.name}"
            if target.exists():
                continue
            moved.append((path.name, target.name))
            if not args.dry_run:
                path.rename(target)

    verb = "restored" if args.restore else "set aside"
    print(f"\n  folder    {folder.resolve()}")
    print(f"  {len(moved)} clips {verb}")
    for before, after in moved:
        print(f"    {before:<28} ->  {after}")

    if not args.restore:
        in_use = [p for p in sorted(folder.glob("*.wav"))
                  if not p.name.startswith(("AI_", "TODO_", "EEE_then__", "THEN_", SET_ASIDE))]
        print(f"\n  {len(in_use)} clips remain in use:")
        for p in in_use:
            print(f"    {p.name}")
        print(f"\n  {SET_ASIDE}* are recognised and kept, just not sung.")
        print("  Put them back at any time with --restore.")

    print("\n  Then:  python -m luokkaretki_generator.build_bank")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
