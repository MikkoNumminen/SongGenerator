"""Cut individual sung word clips out of a source scene, ready for the bank.

    python -m luokkaretki_generator.extract_words D:\\path\\scene.mp4

Separates the vocal first (any music under the singing would otherwise ride
along into every clip), finds the sung regions, counts each one's syllable
nuclei and measures its pitch, then writes numbered candidates whose filenames
carry everything needed to label them by ear:

    c03__2syl__F3__1.42-1.98.wav

The syllable count does most of the work: the bank splits cleanly into
2-syllable words (paska, perse, pillu) and 4-syllable ones (pornolehti,
paviaani), so a candidate's count already halves the possibilities. Rename the
keepers to `<word>.wav` or `<word>_<variant>.wav` and drop them in words/.

Deliberately does not try to recognise which word was sung. Speech recognition
on singing is unreliable, the whole point of the bank is that these clips are
recognisable, and you can label twenty clips by ear faster and more accurately
than any local model could guess at them.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import audio_io, config
from .analysis import extract_f0, hz_to_midi, note_name
from .separate import separate
from .util import resolve_device, work_dir_for


@dataclass
class Candidate:
    i: int
    start_s: float
    end_s: float
    dur_s: float
    n_syllables: int
    midi: float
    rms_db: float
    path: Path | None = None

    @property
    def note(self) -> str:
        # "NA" rather than "?" because this goes into a filename, and "?" is
        # illegal on Windows. A whole source was lost to that: one unpitched
        # clip made the write throw and the run abandoned the file.
        return note_name(int(round(self.midi))) if np.isfinite(self.midi) else "NA"

    @property
    def guesses(self) -> list[str]:
        return [w for w, n in config.WORD_SYLLABLES.items() if n == self.n_syllables]


@dataclass
class Thresholds:
    """Segmentation knobs, defaulted from config but overridable per run.

    Worth sweeping rather than guessing: how much silence a singer leaves
    between words varies enormously between a clipped delivery and a legato
    one, and one setting will not fit every scene.
    """
    silence_db: float = config.WORD_SILENCE_DB
    gap_s: float = config.WORD_GAP_S
    min_s: float = config.WORD_MIN_S


def _envelope_db(mono: np.ndarray, sr: int, hop: int) -> np.ndarray:
    import librosa

    rms = librosa.feature.rms(y=mono, frame_length=4 * hop, hop_length=hop)[0]
    return 20 * np.log10(rms + 1e-9)


def _active_regions(env_db: np.ndarray, hop_s: float, th: Thresholds) -> list[tuple[int, int]]:
    threshold = env_db.max() + th.silence_db
    active = env_db > threshold

    runs, start = [], None
    for i, a in enumerate(active):
        if a and start is None:
            start = i
        elif not a and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(active)))

    # Close short gaps: a plosive stop inside a word reads as silence and would
    # otherwise cut the word in half.
    gap_frames = max(1, int(round(th.gap_s / hop_s)))
    merged: list[list[int]] = []
    for a, b in runs:
        if merged and a - merged[-1][1] <= gap_frames:
            merged[-1][1] = b
        else:
            merged.append([a, b])

    min_frames = max(1, int(round(th.min_s / hop_s)))
    return [(a, b) for a, b in merged if b - a >= min_frames]


def _count_syllables(env_db: np.ndarray, hop_s: float) -> int:
    """Syllable nuclei = prominent peaks in the smoothed loudness envelope."""
    from scipy.ndimage import uniform_filter1d
    from scipy.signal import find_peaks

    width = max(1, int(round(config.SYLLABLE_SMOOTH_S / hop_s)))
    smooth = uniform_filter1d(env_db, size=width, mode="nearest")

    peaks, _ = find_peaks(
        smooth,
        distance=max(1, int(round(config.SYLLABLE_MIN_SEP_S / hop_s))),
        prominence=config.SYLLABLE_PROMINENCE_DB,
    )
    return max(1, len(peaks))


def find_candidates(
    vocal: np.ndarray,
    sr: int = config.SAMPLE_RATE,
    device: str | None = None,
    th: Thresholds | None = None,
    hz: np.ndarray | None = None,
    f0_hop_s: float | None = None,
) -> list[Candidate]:
    th = th or Thresholds()
    mono = audio_io.to_mono(vocal)
    hop = 256
    hop_s = hop / sr

    env_db = _envelope_db(mono, sr, hop)
    if hz is None or f0_hop_s is None:
        hz, _, f0_hop_s = extract_f0(mono, sr, device)

    out: list[Candidate] = []
    for a, b in _active_regions(env_db, hop_s, th):
        start_s, end_s = a * hop_s, b * hop_s

        f0_slice = hz[int(start_s / f0_hop_s): max(int(end_s / f0_hop_s), int(start_s / f0_hop_s) + 1)]
        voiced = f0_slice[np.isfinite(f0_slice)]
        midi = float(np.median(hz_to_midi(voiced))) if voiced.size else float("nan")

        out.append(Candidate(
            i=len(out) + 1,
            start_s=start_s,
            end_s=end_s,
            dur_s=end_s - start_s,
            n_syllables=_count_syllables(env_db[a:b], hop_s),
            midi=midi,
            rms_db=float(env_db[a:b].max()),
        ))
    return out


def cut(vocal: np.ndarray, cand: Candidate, sr: int = config.SAMPLE_RATE) -> np.ndarray:
    pad = config.WORD_PAD_S
    lo = max(0, int((cand.start_s - pad) * sr))
    hi = min(vocal.shape[1], int((cand.end_s + pad) * sr))
    clip = np.array(vocal[:, lo:hi], dtype=np.float32)

    fade = min(int(config.WORD_FADE_S * sr), clip.shape[1] // 2)
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        clip[:, :fade] *= ramp
        clip[:, -fade:] *= ramp[::-1]
    return clip


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="luokkaretki_generator.extract_words",
        description="Cut sung word clips out of a source scene into labelling candidates.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input", type=Path, help="source scene (mp4, mp3, wav -- anything ffmpeg reads)")
    p.add_argument("-o", "--out", type=Path, default=Path("words/candidates"),
                   help="where the candidate clips are written")
    p.add_argument("--separator", choices=["demucs", "roformer"], default=config.SEPARATOR)
    p.add_argument("--device", default=None)
    p.add_argument("--no-separate", action="store_true",
                   help="the source is already an isolated vocal; skip separation")
    p.add_argument("--force", action="store_true", help="re-separate instead of using the cache")
    p.add_argument("--silence-db", type=float, default=config.WORD_SILENCE_DB,
                   help="a region is sung while within this many dB of the loudest point")
    p.add_argument("--gap", type=float, default=config.WORD_GAP_S,
                   help="silences shorter than this do not split a region")
    p.add_argument("--min-dur", type=float, default=config.WORD_MIN_S,
                   help="regions shorter than this are discarded as noise")
    return p


LABELS_HEADER = [
    "# Fill in the `word` column by ear, then run:",
    "#     python -m luokkaretki_generator.build_bank",
    "#",
    "# word     one of: " + ", ".join(config.WORD_SYLLABLES),
    "#          leave as ? to skip the row, or use - to delete it from the bank",
    "# variant  optional label to tell several takes of the same word apart.",
    "#          Blank auto-numbers. You do NOT need to name the pitch -- the",
    "#          tool measures it and picks the nearest take to each target note.",
    "# start/end  seconds; adjust freely, these are only a first guess",
    "#",
    "# syl and pitch are measured, and are hints only. syl is approximate:",
    "# it counts envelope peaks, which over-counts a word with an internal bump.",
    "#",
    "word\tvariant\tstart\tend\tsyl\tpitch\tcandidate",
]


def write_labels(path: Path, candidates: list[Candidate]) -> Path:
    lines = list(LABELS_HEADER)
    for c in candidates:
        name = c.path.name if c.path else ""
        lines.append(f"?\t\t{c.start_s:.3f}\t{c.end_s:.3f}\t{c.n_syllables}\t{c.note}\t{name}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.input.is_file():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 2

    device = resolve_device(args.device)

    if args.no_separate:
        vocal = audio_io.decode(args.input)
        print(f"  source    {args.input.name} (treated as an isolated vocal)")
    else:
        work = work_dir_for(args.input)
        stems = separate(args.input, work, backend=args.separator, device=device, force=args.force)
        vocal = stems.vocal
        print(f"  source    {args.input.name}")
        print(f"  vocal     {'cached' if stems.cached else 'separated'} -> {work}")

    th = Thresholds(silence_db=args.silence_db, gap_s=args.gap, min_s=args.min_dur)
    candidates = find_candidates(vocal, config.SAMPLE_RATE, device, th=th)
    if not candidates:
        print("\n  no sung regions found. Try a lower --silence-db.")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    for c in candidates:
        name = f"c{c.i:02d}__{c.n_syllables}syl__{c.note}__{c.start_s:.2f}-{c.end_s:.2f}.wav"
        c.path = audio_io.write_wav(args.out / name, cut(vocal, c))

    two = sum(1 for c in candidates if c.n_syllables == 2)
    four = sum(1 for c in candidates if c.n_syllables == 4)

    print(f"\n  {len(candidates)} candidates -> {args.out}\n")
    print("   #   start    end    dur   syl   pitch   peak   likely")
    print("  " + "-" * 62)
    for c in candidates:
        guesses = "/".join(c.guesses) if c.guesses else "-"
        print(f"  {c.i:>3}  {c.start_s:6.2f} {c.end_s:6.2f} {c.dur_s * 1000:5.0f}ms "
              f"{c.n_syllables:>3}   {c.note:<5} {c.rms_db:6.1f}  {guesses}")

    print(f"\n  {two} two-syllable (paska / perse / pillu), "
          f"{four} four-syllable (pornolehti / paviaani), "
          f"{len(candidates) - two - four} other")

    labels = write_labels(args.out.parent / "labels.tsv", candidates)

    print(f"\n  Next: open {args.out} and play through the clips.")
    print("    - delete the ones that are junk or unusable")
    print("    - rename the keepers after the word you hear:")
    print("        paska1.wav   perse2.wav   paviaani_low.wav")
    print("      (a bare word, a trailing number, or _anything all work)")
    print("    - leave anything you are unsure about alone; unnamed clips are ignored")
    print("\n  Then:  python -m luokkaretki_generator.build_bank")
    print("\n  Several takes of the same word are wanted, not a problem: the tool")
    print("  picks whichever take is nearest each target note so it shifts less.")
    print("  You do not need to name pitches -- those are measured.")
    print(f"\n  ({labels} also written, if you would rather adjust cut points as")
    print("   timestamps than re-cut by hand: build_bank --labels words/labels.tsv)")
    print("\n  Which word is which has to come from you -- these are cut on silence")
    print("  and loudness, which finds sung regions but cannot tell them apart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
