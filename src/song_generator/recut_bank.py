"""Rebuild the bank from cleaner separation, keeping every label.

    python -m song_generator.recut_bank

The clips were cut from Demucs stems, so whatever instrumental Demucs left
behind is baked into them -- the synthesiser tone under some words is not a
recording flaw but separation residue. Mel-Band Roformer scores around 11.4 SDR
on vocals against Demucs's 9.0, and that gap is largely this.

Cleaning the clips afterwards would be the wrong end to attack. A denoiser
cannot unmix two things a better separator never mixes, and speech-enhancement
models smooth away exactly the crack and rasp that make shouted singing funny.
So the clips are cut again, from better stems, over the identical time ranges.

Nothing needs re-listening. Every name, label and syllable boundary survives,
because only the audio underneath is replaced.

Provenance comes from two places:
  - most clips carry their source and timestamps in the name they were cut with
  - the rest were renamed by hand, and are located by cross-correlating their
    audio against each source's vocal, which is exact because they came from it
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import audio_io, config
from .util import resolve_device

SPAN_RE = re.compile(r"__([A-Za-z0-9]+)__(\d+\.\d+)-(\d+\.\d+)")

# Correlation runs on a decimated signal: 4 kHz is ample to locate a clip to
# within a few milliseconds and is ~11x cheaper than full rate.
PROBE_SR = 4000


@dataclass
class Origin:
    work_dir: Path
    start_s: float
    end_s: float
    how: str


def work_dirs() -> dict[str, Path]:
    """Short source tag -> its work directory."""
    out: dict[str, Path] = {}
    for d in sorted(Path(config.WORK_DIR).glob("*")):
        if not (d / "vocal.wav").is_file():
            continue
        out[d.name] = d
        prefix = config.SOURCE_NAME_PREFIX
        short = (re.sub(f"^{re.escape(prefix)}", "", d.name, flags=re.IGNORECASE)
                 if prefix else d.name)
        out.setdefault(short or d.name, d)
    return out


def from_name(source_clip: str, dirs: dict[str, Path]) -> Origin | None:
    m = SPAN_RE.search(source_clip or "")
    if not m:
        return None
    tag, a, b = m.group(1).lower(), float(m.group(2)), float(m.group(3))
    # A clip name carries the shortened source tag, so the full directory name
    # may still have the shared prefix in front of it.
    d = dirs.get(tag)
    if d is None and config.SOURCE_NAME_PREFIX:
        d = dirs.get(f"{config.SOURCE_NAME_PREFIX.lower()}{tag}")
    return Origin(d, a, b, "name") if d else None


def _decimate(mono: np.ndarray, sr: int) -> np.ndarray:
    """Band-limited downsample, so a slice matches wherever it was taken from.

    Taking every Nth sample instead would make the result depend on the phase
    of the starting index: a stem sampled from 0 and a clip sampled from its own
    0 land on different samples unless the offset happens to be a multiple of N,
    and the two then fail to correlate at all.

    Real music survives that because it is smooth at this rate and neighbouring
    samples are similar, which is why the naive version appeared to work. It was
    still costing precision, and it fails outright on anything less smooth.
    """
    from scipy.signal import resample_poly

    step = max(1, sr // PROBE_SR)
    x = resample_poly(np.asarray(mono, dtype=np.float64), 1, step)
    return x - x.mean()


def by_correlation(clip: np.ndarray, dirs: dict[str, Path],
                   cache: dict[Path, np.ndarray],
                   only: Path | None = None) -> Origin | None:
    """Find which source this clip came from, and exactly where in it.

    The clip is a verbatim slice of one of these stems, so the correct source
    correlates near 1.0 and nothing else comes close.

    Correlation decides the offset even when the filename already carries
    timestamps, because those timestamps are not always where the audio starts:
    clips cut by successors.py were padded 50 ms earlier than the name records.
    Trusting the name cut 50 ms off the front of every one of them, removing the
    attack that makes a shout a shout. A name is good evidence of WHICH source;
    it is not evidence of where.
    """
    probe = _decimate(audio_io.to_mono(clip), config.SAMPLE_RATE)
    probe_norm = float(np.linalg.norm(probe))
    if probe.size < 8 or probe_norm < 1e-9:
        return None

    search = [only] if only is not None else sorted(set(dirs.values()))
    best_score, best = -1.0, None
    for d in search:
        if d not in cache:
            cache[d] = _decimate(
                audio_io.to_mono(audio_io.read_wav(d / "vocal.wav")),
                config.SAMPLE_RATE)
        haystack = cache[d]
        if haystack.size <= probe.size:
            continue

        # Normalised cross-correlation: dividing by the energy of each window
        # makes the score a true similarity in 0..1, so it is comparable across
        # sources of different loudness. A verbatim slice scores near 1.
        #
        # Both halves must avoid the naive O(n*m) form. A three-minute source
        # against a one-second probe is ~840k x 6k multiplies, and there are
        # dozens of pairs -- brute force does not finish. FFT correlation and a
        # cumulative-sum energy window are both O(n log n) or better.
        from scipy.signal import correlate

        corr = correlate(haystack, probe, mode="valid", method="fft")

        squares = np.concatenate([[0.0], np.cumsum(haystack ** 2)])
        energy = np.sqrt(np.maximum(
            squares[probe.size:] - squares[:-probe.size], 0.0))

        n = min(corr.size, energy.size)
        score = corr[:n] / np.maximum(energy[:n] * probe_norm, 1e-9)

        i = int(np.argmax(score))
        if score[i] > best_score:
            step = max(1, config.SAMPLE_RATE // PROBE_SR)
            start = i * step / config.SAMPLE_RATE
            dur = clip.shape[1] / config.SAMPLE_RATE
            best_score, best = float(score[i]), Origin(d, start, start + dur, "correlation")

    return best if best_score > 0.6 else None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="song_generator.recut_bank",
        description="Re-cut the bank from better separation, keeping every label.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--bank", type=Path, default=Path("words"))
    p.add_argument("--out", type=Path, default=Path("words_hq"))
    p.add_argument("--stem", default="vocal_hq.wav",
                   help="filename of the better stem inside each work dir")
    p.add_argument("--dry-run", action="store_true",
                   help="report provenance only, cut nothing")
    p.add_argument("--overwrite", action="store_true",
                   help="allow writing over clips already in --out. Off, "
                        "because that directory may hold hand-named work")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    index = args.bank / "words.json"
    if not index.is_file():
        print(f"error: {index} not found", file=sys.stderr)
        return 2

    entries = json.loads(index.read_text(encoding="utf-8"))
    dirs = work_dirs()
    cache: dict[Path, np.ndarray] = {}

    print(f"  {len(entries)} clips, {len(set(dirs.values()))} sources available\n")

    found: dict[str, Origin] = {}
    for name, e in entries.items():
        path = args.bank / name
        if not path.is_file():
            continue

        # The name narrows the search to one source when it can. The offset
        # always comes from correlation, never from the name.
        hint = from_name(str(e.get("source_clip", "")), dirs)
        origin = by_correlation(audio_io.read_wav(path), dirs, cache,
                                only=hint.work_dir if hint else None)
        if origin is None and hint is not None:
            origin = by_correlation(audio_io.read_wav(path), dirs, cache)
        if origin:
            found[name] = origin
        print(f"  {'ok ' if origin else 'MISS'} {name:<40} "
              f"{origin.work_dir.name if origin else '-':<22} "
              f"{f'{origin.start_s:.2f}-{origin.end_s:.2f}' if origin else ''} "
              f"{origin.how if origin else ''}")

    print(f"\n  located {len(found)} of {len(entries)}")
    sources = sorted({o.work_dir.name for o in found.values()})
    print(f"  {len(sources)} sources need re-separating: {', '.join(sources)}")

    if args.dry_run:
        return 0

    # Checked before anything else that could stop the run, because "this would
    # destroy work you cannot get back" outranks "the stems are not ready".
    # Reporting the stems first hid it until someone fixed them and ran again.
    #
    # --out defaulted to the directory this tool created, back when nothing
    # else lived there. A bank gets hand-curated afterwards: clips renamed by
    # ear, new ones added, and none of that regenerable. Writing over it would
    # destroy exactly the work the repo says can never be recreated.
    existing = {p.name for p in args.out.glob("*.wav")} if args.out.is_dir() else set()
    clashes = sorted(n for n in found if n in existing)
    if clashes and not args.overwrite:
        print(f"\nerror: {len(clashes)} clips already exist in {args.out}, and "
              f"re-cutting would write over them:", file=sys.stderr)
        for name in clashes[:8]:
            print(f"           {name}", file=sys.stderr)
        if len(clashes) > 8:
            print(f"           ... and {len(clashes) - 8} more", file=sys.stderr)
        print("\n       Those may be hand-named recordings, which cannot be "
              "regenerated.\n"
              "       Pick an --out that does not exist yet, or pass --overwrite "
              "if you are\n"
              "       certain the clips there are this tool's own output.",
              file=sys.stderr)
        return 2

    missing = [s for s in sources if not (Path(config.WORK_DIR) / s / args.stem).is_file()]
    if missing:
        print(f"\n  {len(missing)} sources have no {args.stem} yet.")
        print("  Run the roformer pass first, then this again.")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    rebuilt = 0
    for name, origin in found.items():
        vocal = audio_io.read_wav(origin.work_dir / args.stem)
        lo = max(0, int(origin.start_s * config.SAMPLE_RATE))
        hi = min(vocal.shape[1], int(origin.end_s * config.SAMPLE_RATE))
        if hi <= lo:
            continue
        clip = np.array(vocal[:, lo:hi], dtype=np.float32)
        fade = min(int(config.WORD_FADE_S * config.SAMPLE_RATE), clip.shape[1] // 2)
        if fade > 0:
            ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
            clip[:, :fade] *= ramp
            clip[:, -fade:] *= ramp[::-1]
        audio_io.write_wav(args.out / name, clip)
        rebuilt += 1

    kept = {k: v for k, v in entries.items() if k in found}
    (args.out / "words.json").write_text(
        json.dumps(kept, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n  {rebuilt} clips re-cut into {args.out.resolve()}")
    print(f"  every name, label and syllable boundary preserved")
    print(f"\n  Compare:  song-generator.exe input\\song.mp4 --words-dir {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
