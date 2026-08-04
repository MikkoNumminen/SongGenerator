"""Everything you need to diagnose or tune, in one command.

    python -m song_generator.doctor
    python -m song_generator.doctor --song input/musicHyva.mp4

Written because the alternative was worse. Diagnosing a bad-sounding render
meant a dozen separate commands and a throwaway script each time -- what is in
the bank, what pitches it covers, how the slots came out, why a word never
appears. Each answer is cheap to compute and expensive to ask for one at a time.

For an agent this is the difference between one tool call and twenty. For a
person it is the difference between remembering twenty commands and one.

Nothing here changes anything. It only looks.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from . import config
from .analysis import note_name
from .mapping import BankError, clean_slots, find_climaxes, group_phrases, load_bank


def _bar(n: int, width: int = 28) -> str:
    return "#" * min(n, width)


def report_environment() -> None:
    print("ENVIRONMENT")
    try:
        import torch
        cuda = torch.cuda.is_available()
        name = torch.cuda.get_device_name(0) if cuda else "-"
        print(f"  torch {torch.__version__}, cuda={cuda}, gpu={name}")
    except ImportError:
        print("  torch not installed")

    import shutil
    print(f"  ffmpeg: {'found' if shutil.which('ffmpeg') else 'MISSING -- winget install Gyan.FFmpeg'}")

    for name, path in config.BANKS.items():
        exists = (Path(path) / "words.json").is_file()
        mark = "ok" if exists else "not built"
        star = " (default)" if name == config.DEFAULT_BANK else ""
        print(f"  bank '{name}': {mark}{star}")


def report_bank(bank_name: str) -> list | None:
    print(f"\nBANK '{bank_name}'")
    try:
        units = load_bank(Path(config.BANKS[bank_name]))
    except BankError as exc:
        print(f"  {exc}")
        return None

    singable = [u for u in units if not u.is_climax]
    climax = [u for u in units if u.is_climax]
    shouts = [u for u in units if u.is_bare_shout]

    print(f"  {len(units)} units: {len(singable)} ordinary, {len(climax)} climax-only, "
          f"{len(shouts)} bare shouts")

    words = Counter(w for u in units for w in u.words)
    print("  words:   " + ", ".join(f"{w} x{n}" for w, n in words.most_common()))

    lengths = Counter(u.syllables for u in units)
    print("  lengths: " + ", ".join(f"{s} syl x{n}" for s, n in sorted(lengths.items())))

    missing = [w for w in config.WORD_SYLLABLES if w not in words]
    if missing:
        print(f"  MISSING: {', '.join(missing)}")

    # Pitch coverage decides how much has to be folded -- but only the coverage
    # of units that actually get shifted counts. Reporting the whole bank once
    # made this look far healthier than it was: the spread came almost entirely
    # from shouts, which are never shifted, and from climax units usable only at
    # peaks. The ordinary units doing most of the singing sat inside a fifth.
    ordinary = [u for u in units if not u.is_bare_shout and not u.is_climax]

    def coverage(group: list, label: str) -> None:
        p = np.array([u.midi for u in group if u.midi is not None])
        if not p.size:
            print(f"  {label:<34} none")
            return
        print(f"  {label:<34} {len(p):>3} units  "
              f"{note_name(int(round(p.min())))}-{note_name(int(round(p.max())))}"
              f"  spread {p.max() - p.min():.1f} st")

    print("\n  pitch coverage")
    coverage(units, "whole bank")
    coverage([u for u in units if u.is_bare_shout], "  bare shouts (never shifted)")
    coverage([u for u in units if u.is_climax], "  climax-only (peaks only)")
    coverage(ordinary, "  ORDINARY -- what usually places")

    pitches = np.array([u.midi for u in ordinary if u.midi is not None])
    if pitches.size:
        print("\n  ordinary units by pitch:")
        hist = Counter(int(round(p)) for p in pitches)
        for midi in sorted(hist):
            print(f"    {note_name(midi):<5} {_bar(hist[midi])} {hist[midi]}")
        if pitches.max() - pitches.min() < 12:
            print("\n    Narrow. These sit inside an octave, so any song ranging wider")
            print("    is octave-folded however cleverly units are chosen -- selection")
            print("    cannot invent a pitch the bank does not have. Only more takes")
            print("    of WORDS at new pitches raise the ceiling. More shouts do not:")
            print("    they are never shifted, so their spread is decorative.")

    smallest = min((u.syllables for u in climax), default=None)
    if smallest:
        print(f"\n  smallest climax unit: {smallest} syllables")
        print(f"    a phrase shorter than this cannot hold one, and will not be")
        print(f"    chosen as a peak however loud or high it is")
    return units


def report_song(path: Path, units: list | None) -> None:
    work = Path(config.WORK_DIR) / path.stem.lower().replace(" ", "_")
    analysis_path = work / "analysis.json"
    print(f"\nSONG {path.name}")
    if not analysis_path.is_file():
        matches = sorted(Path(config.WORK_DIR).glob("*/analysis.json"))
        print(f"  no analysis yet. Run it once, or try: "
              f"{[m.parent.name for m in matches][:5]}")
        return

    data = json.loads(analysis_path.read_text(encoding="utf-8"))
    notes = data["notes"]
    slots, merged, split = clean_slots(notes)
    groups = group_phrases(slots)

    print(f"  {data['duration_s']:.0f}s, {data['tempo_bpm']:.0f} BPM")
    print(f"  {len(notes)} notes -> {len(slots)} slots "
          f"({merged} blips merged, {split} held notes split)")
    print(f"  {len(groups)} phrases, sizes "
          f"min {min(len(g) for g in groups)} / median "
          f"{int(np.median([len(g) for g in groups]))} / max {max(len(g) for g in groups)}")

    midis = np.array([n["midi"] for n in notes])
    print(f"  melody {note_name(int(round(midis.min())))}-"
          f"{note_name(int(round(midis.max())))} "
          f"({midis.max() - midis.min():.1f} semitones)")

    if not units:
        return

    smallest = min((u.syllables for u in units if u.is_climax), default=None)
    if smallest:
        eligible = [i for i, g in enumerate(groups) if len(g) >= smallest]
        peaks = find_climaxes(groups, min_slots=smallest)
        print(f"\n  climax phrases: {len(peaks)} chosen from {len(eligible)} long enough "
              f"(of {len(groups)})")
        if not eligible:
            print(f"    NONE are long enough to hold a {smallest}-syllable unit.")
            print("    paviaani cannot appear in this song. Either shorten the climax")
            print("    units or raise MAX_SYLLABLE_S so fewer held notes get split.")

    # What the melody will actually demand of this bank.
    sources = np.array([u.midi for u in units if u.midi is not None])
    if sources.size:
        wanted = np.array([n["midi"] for n in notes])
        raw = np.abs(wanted[:, None] - sources[None, :]).min(axis=1)
        folded = float((raw > config.SHIFT_CAP_SEMITONES).mean())
        print(f"\n  predicted shift: median {np.median(raw):.1f} semitones, "
              f"{folded * 100:.0f}% would need octave folding")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="song_generator.doctor",
        description="Print everything needed to diagnose or tune, in one command.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--song", type=Path, default=None,
                   help="also report on this song's extracted melody")
    p.add_argument("--bank", default=config.DEFAULT_BANK, choices=sorted(config.BANKS))
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report_environment()
    units = report_bank(args.bank)
    if args.song:
        report_song(args.song, units)
    else:
        analysed = sorted(Path(config.WORK_DIR).glob("*/analysis.json"))
        if analysed:
            print(f"\nANALYSED SONGS ({len(analysed)}) -- pass --song to inspect one")
            for a in analysed[:12]:
                print(f"  {a.parent.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
