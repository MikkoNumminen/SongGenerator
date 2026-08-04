"""Cut what comes straight after a shout: the EEE PAVIAANI problem.

    python -m song_generator.successors

A shout and the word it introduces are one gesture, but silence-based cutting
splits them, because there IS a gap between the held vowel and the word. That
is why paviaani was so hard to find: every take of it had been severed from the
"eee" that announces it, exactly as pornolehti was severed into por + nolehti.

Rather than hunt for the word across hundreds of clips, this takes every
shout-shaped clip and re-cuts the source around it:

    EEE_then__<source>__<time>.wav      the shout plus whatever follows it
    THEN_<source>__<time>.wav           just what follows, on its own

Keeping the pair whole is the better prize. The transition from a held shout
into the first syllable of a word cannot be rebuilt by butting two recordings
together, and that transition is most of what makes the phrase land.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import audio_io, config

SPAN_RE = re.compile(r"__(\d+\.\d+)-(\d+\.\d+)")
SOURCE_RE = re.compile(r"__([A-Za-z0-9]+)__c\d+__")

# How much to take after the shout ends. Long enough for a four-syllable word
# sung slowly, short enough not to drag in the next phrase.
FOLLOW_S = 2.2
LEAD_PAD_S = 0.05


@dataclass
class Shout:
    path: Path
    source: str
    start_s: float
    end_s: float


def find_work_vocal(source: str, work_root: Path) -> Path | None:
    """Map a clip's short source tag back to its separated vocal."""
    for candidate in (f"pilluvittu{source}", source, f"pilluvittu{source.lower()}"):
        vocal = work_root / candidate.lower() / "vocal.wav"
        if vocal.is_file():
            return vocal
    matches = [d for d in work_root.iterdir()
               if d.is_dir() and d.name.lower().endswith(source.lower())]
    for d in matches:
        if (d / "vocal.wav").is_file():
            return d / "vocal.wav"
    return None


def parse_clip(path: Path) -> Shout | None:
    span = SPAN_RE.search(path.stem)
    source = SOURCE_RE.search(path.stem)
    if not span or not source:
        return None
    return Shout(path=path, source=source.group(1),
                 start_s=float(span.group(1)), end_s=float(span.group(2)))


def is_shout_named(name: str) -> bool:
    low = name.lower()
    return "shout" in low or "__eee" in low or low.startswith("eee")


def fade(clip: np.ndarray, sr: int) -> np.ndarray:
    clip = np.array(clip, dtype=np.float32)
    n = min(int(config.WORD_FADE_S * sr), clip.shape[1] // 2)
    if n > 0:
        ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
        clip[:, :n] *= ramp
        clip[:, -n:] *= ramp[::-1]
    return clip


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="song_generator.successors",
        description="Re-cut the audio following each shout, to recover shout+word pairs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--folder", type=Path, default=Path("words/candidates"))
    p.add_argument("--work", type=Path, default=Path(config.WORK_DIR))
    p.add_argument("--follow", type=float, default=FOLLOW_S)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.folder.is_dir():
        print(f"error: {args.folder} not found", file=sys.stderr)
        return 2

    shouts = []
    for path in sorted(args.folder.glob("*.wav")):
        if not is_shout_named(path.name):
            continue
        parsed = parse_clip(path)
        if parsed:
            shouts.append(parsed)

    if not shouts:
        print("  no shout-shaped clips carrying source timings were found.")
        return 1

    print(f"  {len(shouts)} shouts to follow up\n")

    sr = config.SAMPLE_RATE
    vocals: dict[str, np.ndarray | None] = {}
    made = missing = 0

    for shout in shouts:
        if shout.source not in vocals:
            found = find_work_vocal(shout.source, args.work)
            vocals[shout.source] = audio_io.read_wav(found) if found else None
        vocal = vocals[shout.source]
        if vocal is None:
            missing += 1
            continue

        total = vocal.shape[1] / sr
        lead = max(0.0, shout.start_s - LEAD_PAD_S)
        after_end = min(total, shout.end_s + args.follow)
        if after_end <= shout.end_s + 0.15:
            continue

        pair = vocal[:, int(lead * sr):int(after_end * sr)]
        tail = vocal[:, int(shout.end_s * sr):int(after_end * sr)]

        stamp = f"{shout.source}__{shout.start_s:.2f}-{after_end:.2f}"
        audio_io.write_wav(args.folder / f"EEE_then__{stamp}.wav", fade(pair, sr))
        audio_io.write_wav(args.folder / f"THEN_{stamp}.wav", fade(tail, sr))
        made += 1

    print(f"  folder    {args.folder.resolve()}")
    print(f"  {made} shout-and-after pairs written"
          + (f", {missing} skipped (source vocal not found)" if missing else ""))
    print()
    print("  EEE_then__*  the shout plus what follows -- listen to these first.")
    print("  THEN_*       only what follows, if the pair is not usable whole.")
    print()
    print("  If you hear it, keep the pair whole and name it:")
    print("      EEE_then__26__12.30-15.10.wav   ->   eeepaviaani1.wav")
    print("  eeepaviaani parses as eee + paviaani, five slots in one clip, with")
    print("  the real transition into the word intact. Splicing a separate shout")
    print("  onto a separate word cannot reproduce that.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
