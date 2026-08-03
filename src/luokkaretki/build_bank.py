"""Build the word bank from clips you have listened to and named.

    python -m luokkaretki.build_bank

Default workflow -- rename the files:

    1. python -m luokkaretki.extract_words <scene>     cuts words/candidates/
    2. Play them. Delete the junk. Rename the keepers after the word you
       heard: paska1.wav, paska2.wav, perse1.wav, paviaani_low.wav ...
    3. python -m luokkaretki.build_bank                reads the names

Anything still carrying its original c07__4syl__... name is ignored, so
"leave it alone" and "reject it" both work without deleting anything.

Alternative workflow -- a labels.tsv of timestamps, for when you would rather
adjust cut points than re-cut by hand:

    python -m luokkaretki.build_bank --labels words/labels.tsv

Either way the output is words/<word>_<variant>.wav plus words/words.json,
holding each clip's measured pitch, duration and syllable boundaries.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import audio_io, config
from .analysis import extract_f0, hz_to_midi, note_name
from .extract_words import cut, Candidate
from .util import resolve_device


@dataclass
class Row:
    word: str
    variant: str
    start_s: float
    end_s: float
    line_no: int


class LabelError(RuntimeError):
    pass


def read_labels(path: Path) -> list[Row]:
    if not path.is_file():
        raise LabelError(
            f"{path} not found. Run `python -m luokkaretki.extract_words <scene>` first."
        )

    rows: list[Row] = []
    # utf-8-sig, not utf-8: Notepad and PowerShell's Out-File both write a BOM,
    # which would otherwise turn the header's "word" into "﻿word" and fail
    # on the first line the user ever edits.
    for n, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = raw.split("\t")
        if parts[0].strip().lower() == "word":
            continue
        if len(parts) < 4:
            raise LabelError(f"{path}:{n}: expected at least 4 tab-separated columns, got {len(parts)}")

        word = parts[0].strip().lower()
        if word in ("?", "-", ""):
            continue
        if word not in config.WORD_SYLLABLES:
            raise LabelError(
                f"{path}:{n}: unknown word {word!r}. "
                f"Expected one of: {', '.join(config.WORD_SYLLABLES)}"
            )
        try:
            start_s, end_s = float(parts[2]), float(parts[3])
        except ValueError as exc:
            raise LabelError(f"{path}:{n}: start/end must be numbers ({exc})") from exc
        if end_s <= start_s:
            raise LabelError(f"{path}:{n}: end ({end_s}) must be after start ({start_s})")

        rows.append(Row(word, parts[1].strip(), start_s, end_s, n))
    return rows


@dataclass
class Named:
    """A candidate clip you have renamed after the word you heard in it."""
    path: Path
    word: str
    variant: str


def parse_name(stem: str) -> tuple[str, str] | None:
    """'paska1' -> ('paska', '1'). 'paviaani_low' -> ('paviaani', 'low').

    Accepts a bare word, a trailing number, or any separator-and-label. No bank
    word is a prefix of another, so a plain prefix match is unambiguous.
    """
    clean = stem.strip().lower()
    for word in config.WORD_SYLLABLES:
        if clean.startswith(word):
            return word, clean[len(word):].lstrip("_- .").strip() or ""
    return None


def scan_folder(folder: Path) -> tuple[list[Named], list[Path]]:
    """Split a candidate folder into renamed clips and still-unnamed ones."""
    named: list[Named] = []
    ignored: list[Path] = []

    for path in sorted(folder.glob("*.wav")):
        parsed = parse_name(path.stem)
        if parsed is None:
            ignored.append(path)
            continue
        named.append(Named(path, parsed[0], parsed[1]))

    return named, ignored


def syllable_boundaries(clip: np.ndarray, sr: int, n_syllables: int) -> list[float]:
    """Split points inside a clip, at the quietest dips between syllable nuclei.

    These are what make a multi-syllable word land its syllables on the melody's
    note onsets instead of drifting across them. Detected here, hand-correctable
    in words.json -- the detector is decent but a recording with a soft internal
    consonant will fool it, and the cost of being wrong is audible.
    """
    if n_syllables <= 1:
        return []

    import librosa
    from scipy.ndimage import uniform_filter1d
    from scipy.signal import find_peaks

    hop = 256
    mono = audio_io.to_mono(clip)
    env = 20 * np.log10(librosa.feature.rms(y=mono, frame_length=4 * hop, hop_length=hop)[0] + 1e-9)
    env = uniform_filter1d(env, size=max(1, int(round(config.SYLLABLE_SMOOTH_S * sr / hop))), mode="nearest")

    peaks, _ = find_peaks(
        env,
        distance=max(1, int(round(config.SYLLABLE_MIN_SEP_S * sr / hop))),
        prominence=config.SYLLABLE_PROMINENCE_DB,
    )
    wanted = n_syllables - 1
    if len(peaks) < 2:
        # Fall back to an even split rather than returning nothing: a wrong-ish
        # boundary still beats having none for a multi-syllable word.
        dur = mono.shape[0] / sr
        return [round(dur * i / n_syllables, 4) for i in range(1, n_syllables)]

    # Depth of each valley below the lower of the two peaks flanking it. A word
    # is known to have exactly n_syllables, so keep only the deepest wanted
    # valleys: envelope bumps from a rolled consonant or a vibrato dip
    # otherwise produce more boundaries than the word has syllables, and every
    # extra one drags a syllable onto the wrong note in stage 3.
    valleys = []
    for a, b in zip(peaks[:-1], peaks[1:]):
        idx = a + int(np.argmin(env[a:b]))
        depth = float(min(env[a], env[b]) - env[idx])
        valleys.append((depth, idx))

    if len(valleys) > wanted:
        valleys = sorted(valleys, reverse=True)[:wanted]
    elif len(valleys) < wanted:
        # Too few nuclei to split on: pad by evenly dividing the longest gap
        # left over, so the count always matches the word.
        edges = [0] + sorted(i for _, i in valleys) + [len(env)]
        while len(valleys) < wanted:
            widest = max(zip(edges[:-1], edges[1:]), key=lambda p: p[1] - p[0])
            mid = (widest[0] + widest[1]) // 2
            valleys.append((0.0, mid))
            edges = sorted(edges + [mid])

    return [round(float(i * hop / sr), 4) for _, i in sorted(valleys, key=lambda v: v[1])]


def measure(clip: np.ndarray, sr: int, device: str | None) -> tuple[float, float]:
    """(median midi pitch, duration seconds) for a clip."""
    mono = audio_io.to_mono(clip)
    hz, _, _ = extract_f0(mono, sr, device)
    voiced = hz[np.isfinite(hz)]
    midi = float(np.median(hz_to_midi(voiced))) if voiced.size else float("nan")
    return midi, mono.shape[0] / sr


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="luokkaretki.build_bank",
        description="Cut a filled-in labels.tsv into the word bank.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--candidates", type=Path, default=Path("words/candidates"),
                   help="folder of clips you have renamed after the word you heard")
    p.add_argument("--labels", type=Path, default=None,
                   help="use a labels.tsv of timestamps instead of renamed files")
    p.add_argument("--vocal", type=Path, default=None,
                   help="separated vocal wav, for --labels [default: newest under work/*/vocal.wav]")
    p.add_argument("--out", type=Path, default=Path("words"))
    p.add_argument("--device", default=None)
    return p


def _find_vocal(explicit: Path | None) -> Path:
    if explicit:
        if not explicit.is_file():
            raise LabelError(f"vocal not found: {explicit}")
        return explicit
    found = sorted(Path(config.WORK_DIR).glob("*/vocal.wav"), key=lambda p: p.stat().st_mtime)
    if not found:
        raise LabelError(
            "no separated vocal found under work/. "
            "Run `python -m luokkaretki.extract_words <scene>` first."
        )
    return found[-1]


def _collect(args, device) -> list[tuple[str, str, np.ndarray, dict]]:
    """(word, variant, clip, source-info) for everything to put in the bank."""
    if args.labels:
        rows = read_labels(args.labels)
        if not rows:
            raise LabelError(f"no labelled rows in {args.labels} -- every `word` is still '?'.")
        vocal = audio_io.read_wav(_find_vocal(args.vocal))
        print(f"  labels    {args.labels} ({len(rows)} labelled rows)\n")

        out = []
        for row in rows:
            cand = Candidate(i=0, start_s=row.start_s, end_s=row.end_s,
                             dur_s=row.end_s - row.start_s, n_syllables=0,
                             midi=float("nan"), rms_db=0.0)
            out.append((row.word, row.variant, cut(vocal, cand),
                        {"source_start_s": round(row.start_s, 3),
                         "source_end_s": round(row.end_s, 3)}))
        return out

    if not args.candidates.is_dir():
        raise LabelError(
            f"{args.candidates} not found. "
            "Run `python -m luokkaretki.extract_words <scene>` first."
        )

    named, ignored = scan_folder(args.candidates)
    print(f"  clips     {args.candidates}")
    print(f"  named     {len(named)} renamed, {len(ignored)} left unnamed (ignored)\n")
    if not named:
        raise LabelError(
            f"nothing in {args.candidates} is named after a bank word yet.\n"
            f"       Rename the keepers to e.g. paska1.wav, perse2.wav, "
            f"paviaani_low.wav\n"
            f"       (any of: {', '.join(config.WORD_SYLLABLES)})"
        )

    return [(n.word, n.variant, audio_io.read_wav(n.path), {"source_clip": n.path.name})
            for n in named]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    device = resolve_device(args.device)

    try:
        items = _collect(args, device)
    except LabelError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    seen: dict[str, int] = {}
    bank: dict[str, dict] = {}

    for word, variant, clip, source in items:
        seen[word] = seen.get(word, 0) + 1
        variant = variant or str(seen[word])
        name = f"{word}_{variant}.wav"
        while name in bank:  # two files that reduce to the same variant
            seen[word] += 1
            variant = str(seen[word])
            name = f"{word}_{variant}.wav"

        if clip.shape[1] < int(0.02 * config.SAMPLE_RATE):
            print(f"  skipped {name}: clip is too short to use")
            continue

        audio_io.write_wav(args.out / name, clip)
        midi, dur = measure(clip, config.SAMPLE_RATE, device)
        n_syl = config.WORD_SYLLABLES[word]
        bounds = syllable_boundaries(clip, config.SAMPLE_RATE, n_syl)

        bank[name] = {
            "word": word,
            "variant": variant,
            **source,
            "duration_s": round(dur, 4),
            "midi": round(midi, 2) if np.isfinite(midi) else None,
            "note": note_name(int(round(midi))) if np.isfinite(midi) else None,
            "syllables": n_syl,
            "syllable_bounds_s": bounds,
        }
        note = bank[name]["note"] or "?"
        print(f"  {name:<24} {dur * 1000:5.0f}ms  {note:<5} "
              f"{n_syl} syl, bounds at {bounds}")

    if not bank:
        return 1

    words_json = args.out / "words.json"
    if words_json.is_file():
        existing = json.loads(words_json.read_text(encoding="utf-8"))
        # Keep any hand-corrected syllable boundaries rather than stamping over
        # them -- correcting those by ear is the whole reason the file is
        # editable, and silently discarding that work would be worse than
        # refusing to rebuild.
        for name, entry in bank.items():
            prior = existing.get(name)
            if prior and prior.get("syllable_bounds_s") and prior.get("hand_corrected"):
                entry["syllable_bounds_s"] = prior["syllable_bounds_s"]
                entry["hand_corrected"] = True
        existing.update(bank)
        bank = existing

    words_json.write_text(json.dumps(bank, indent=2, ensure_ascii=False), encoding="utf-8")

    by_word: dict[str, int] = {}
    for entry in bank.values():
        by_word[entry["word"]] = by_word.get(entry["word"], 0) + 1

    print(f"\n  bank      {words_json}")
    print("  " + ", ".join(f"{w}: {n}" for w, n in sorted(by_word.items())))
    missing = [w for w in config.WORD_SYLLABLES if w not in by_word]
    if missing:
        print(f"  still missing: {', '.join(missing)}")
    print("\n  Rerunnable: rename or delete more clips and run this again. Existing")
    print("  entries are updated in place, so the bank grows as you work through them.")
    print("\n  Syllable boundaries above are detected. To correct one by ear, edit")
    print("  syllable_bounds_s in words.json and add \"hand_corrected\": true so a")
    print("  later rebuild keeps your values.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
