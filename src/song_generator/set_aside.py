"""Set bare-syllable clips aside: keep them, stop using them.

    python -m song_generator.set_aside
    python -m song_generator.set_aside --restore

Syllables were worth trying -- they map onto a melody 1:1 and can spell words
that were never recorded intact -- but in practice they crowded out the words.
A clip of "pas" fills a slot as neatly as one of "bravo" and says nothing, and
a track full of them stops being about bravo, tango, delta, kilometer and aah
calculator.

THAT IS NO LONGER WHY THEY WOULD CROWD ANYTHING. The pool a song is chosen
from is filtered to whole words, so a bare syllable is never placed, and the
syllable clips now do the job they were always meant for: arrange.py cuts them
apart and spells words out of them that no recording contains.

So setting them aside costs spelling and buys nothing. On the current bank it
removes three clips and every spelling of one word with them. The command is
kept because a bank whose syllables really are junk still wants it, and
--restore still puts them back, but it now says what it would cost first.

So they are renamed rather than deleted:

    pas.wav   ->   SYL_pas.wav

SYL_ does not parse as a bank word, so those clips leave the bank without
anything being thrown away, and --restore puts them back. Identifying them by
ear was real work and it stays recorded in the name.

Shouts are exempt: aah is a genuine utterance, not a fragment of one, and it is
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
        prog="song_generator.set_aside",
        description="Keep syllable clips but take them out of the bank.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--folder", type=Path, default=Path("words/candidates"))
    p.add_argument("--restore", action="store_true", help="put them back into use")
    p.add_argument("--dry-run", action="store_true")
    return p


def _report_cost(folder: Path, going: set[str], dry_run: bool) -> None:
    """Which words would stop being spellable if these clips left.

    Worth saying out loud, because the reason this command exists stopped
    applying: syllables are no longer sung on their own, they are what makes a
    word the bank never recorded sayable at all.
    """
    index = folder / "words.json"
    if not index.is_file():
        return

    try:
        from .arrange import enrich
        from .mapping import load_bank
    except ImportError:  # pragma: no cover - only if the package is half-installed
        return

    def spellable(keep: set[str] | None) -> set[str]:
        import random

        units = load_bank(folder, prefer_standardised=False, singable_only=False)
        if keep is not None:
            units = [u for u in units if u.name in keep]
        pool = enrich(units, config.PLAY_DEFAULT_LEVEL, random.Random(0))
        return {u.words[0] for u in pool if u.name.startswith("spelled:")}

    try:
        everything = {p.name for p in folder.glob("*.wav")}
        before = spellable(None)
        after = spellable(everything - going)
    except Exception:  # pragma: no cover - a warning must never break the command
        return

    lost = sorted(before - after)
    if lost:
        would = "would stop" if dry_run else "have stopped"
        print(f"\n  COST      these words {would} being spellable: "
              f"{', '.join(lost)}")
        print("            they exist only as syllables in the clips above. "
              "--restore undoes this.")


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

    if moved and not args.restore:
        _report_cost(folder, {before for before, _ in moved}, args.dry_run)

    if not args.restore:
        in_use = [p for p in sorted(folder.glob("*.wav"))
                  if not p.name.startswith(("AI_", "TODO_", "EEE_then__", "THEN_", SET_ASIDE))]
        print(f"\n  {len(in_use)} clips remain in use:")
        for p in in_use:
            print(f"    {p.name}")
        print(f"\n  {SET_ASIDE}* are recognised and kept, just not sung.")
        print("  Put them back at any time with --restore.")

    print("\n  Then:  python -m song_generator.build_bank")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
