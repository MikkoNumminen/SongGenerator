"""Collapse the mined candidate tree into one flat folder for reviewing.

    python -m song_generator.flatten

Mining writes one subfolder per source, which is fine for the machine and
useless for a person: reviewing means opening fifty folders. This puts every
clip in one place and tags the ones nobody has confirmed yet.

    TODO_bravo__kirby2__c07__1.42-1.98.wav      a guess, unconfirmed
    TODO_shout__muumit__c11__3.20-3.80.wav      a held shout, unidentified
    TODO_4syl__uutiset__c03__0.50-1.10.wav      four syllables, no guess
    bravo1.wav                                  confirmed by you

Removing the TODO_ prefix IS the act of confirming a clip. Nothing tagged can
reach the bank: "TODO_..." does not parse as a bank word, so an unreviewed
guess is structurally incapable of being built into the word bank, however
confident the recogniser was about it.

Sorting the folder by name groups clips by what they probably are, so all the
likely bravo sit together, all the shouts sit together, and so on.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import config
from .build_bank import parse_phrase

TODO = "TODO_"
SPAN_RE = re.compile(r"(c\d+)__.*?__(\d+\.\d+-\d+\.\d+)$")
MAYBE_RE = re.compile(r"^maybe-([a-zåäö]+)__(.*)$", re.IGNORECASE)
HINT_RE = re.compile(r"^c\d+__([a-z0-9]+)__", re.IGNORECASE)


def describe(stem: str) -> str:
    """What this clip probably is, for the sortable part of the new name."""
    maybe = MAYBE_RE.match(stem)
    if maybe:
        return maybe.group(1).lower()

    parsed = parse_phrase(stem)
    if parsed is not None:
        return "-".join(parsed[0])

    hint = HINT_RE.match(stem)
    if hint:
        return hint.group(1).lower()
    return "unknown"


def source_tag(folder_name: str) -> str:
    """Shorten the source folder name; they all share a long common prefix."""
    prefix = config.SOURCE_NAME_PREFIX
    short = (re.sub(f"^{re.escape(prefix)}", "", folder_name, flags=re.IGNORECASE)
             if prefix else folder_name)
    return short or "orig"


def span_tag(stem: str) -> str:
    m = SPAN_RE.search(stem)
    return f"{m.group(1)}__{m.group(2)}" if m else stem[:40]


def flat_name(path: Path, source: str) -> str:
    stem = path.stem
    inner = MAYBE_RE.match(stem)
    if inner:
        stem_for_span = inner.group(2)
    else:
        stem_for_span = stem
    return f"{TODO}{describe(stem)}__{source_tag(source)}__{span_tag(stem_for_span)}.wav"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="song_generator.flatten",
        description="Collapse mined candidate subfolders into one reviewable folder.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--folder", type=Path, default=Path("words/candidates"))
    p.add_argument("--dry-run", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.folder
    if not root.is_dir():
        print(f"error: {root} not found", file=sys.stderr)
        return 2

    subfolders = [d for d in root.iterdir() if d.is_dir()]
    moved = collisions = 0

    for folder in sorted(subfolders):
        for path in sorted(folder.glob("*.wav")):
            target = root / flat_name(path, folder.name)
            if target.exists():
                collisions += 1
                continue
            if args.dry_run:
                print(f"  {path.name}  ->  {target.name}")
            else:
                path.rename(target)
            moved += 1

    if not args.dry_run:
        for folder in subfolders:
            for junk in folder.glob("labels.tsv"):
                junk.unlink()
            try:
                folder.rmdir()
            except OSError:
                pass  # something unexpected inside; leave it alone

    kept = sorted(p for p in root.glob("*.wav") if not p.name.startswith(TODO))
    todo = sorted(root.glob(f"{TODO}*.wav"))

    print(f"\n  folder    {root.resolve()}")
    print(f"  {moved} clips flattened"
          + (f", {collisions} name collisions skipped" if collisions else ""))
    print(f"  {len(todo)} tagged {TODO} (not yet confirmed by you)")
    print(f"  {len(kept)} already named by you")

    groups: dict[str, int] = {}
    for p in todo:
        rest = p.name[len(TODO):]
        groups[rest.split("__")[0]] = groups.get(rest.split("__")[0], 0) + 1
    if groups:
        print("\n  tagged clips by best guess:")
        for label, n in sorted(groups.items(), key=lambda kv: -kv[1]):
            known = " (a bank word)" if label in config.WORD_SYLLABLES or "-" in label else ""
            print(f"    {n:>4}  {label}{known}")

    print(f"\n  Sort by name and the guesses group together. Rename a clip to")
    print(f"  confirm it -- dropping the {TODO} prefix is what makes it count:")
    print(f"      {TODO}bravo__kirby2__c07__1.42-1.98.wav   ->   bravo1.wav")
    print(f"  Anything still tagged is ignored by build_bank, so leaving a clip")
    print(f"  alone is always safe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
