"""Turn a filled-in labels.tsv into the word bank.

    python -m luokkaretki.build_bank

Reads words/labels.tsv, cuts each labelled row out of the separated vocal, and
writes words/<word>_<variant>.wav along with words/words.json holding each
clip's measured pitch, duration and syllable boundaries.

Re-runnable: rows already built are rewritten from the current times, so
adjusting a start/end in labels.tsv and running again just updates that clip.
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
    if len(peaks) < 2:
        # Fall back to an even split rather than returning nothing: a wrong-ish
        # boundary still beats having none for a multi-syllable word.
        dur = mono.shape[0] / sr
        return [round(dur * i / n_syllables, 4) for i in range(1, n_syllables)]

    bounds = []
    for a, b in zip(peaks[:-1], peaks[1:]):
        valley = a + int(np.argmin(env[a:b]))
        bounds.append(round(float(valley * hop / sr), 4))
    return bounds


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
    p.add_argument("--labels", type=Path, default=Path("words/labels.tsv"))
    p.add_argument("--vocal", type=Path, default=None,
                   help="separated vocal wav [default: the newest under work/*/vocal.wav]")
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    device = resolve_device(args.device)

    try:
        rows = read_labels(args.labels)
        vocal_path = _find_vocal(args.vocal)
    except LabelError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not rows:
        print(f"  no labelled rows in {args.labels} -- every `word` is still '?'.")
        print("  Fill some in and run again.")
        return 1

    vocal = audio_io.read_wav(vocal_path)
    args.out.mkdir(parents=True, exist_ok=True)
    print(f"  vocal     {vocal_path}")
    print(f"  labels    {args.labels} ({len(rows)} labelled rows)\n")

    seen: dict[str, int] = {}
    bank: dict[str, dict] = {}

    for row in rows:
        seen[row.word] = seen.get(row.word, 0) + 1
        variant = row.variant or str(seen[row.word])
        name = f"{row.word}_{variant}.wav"

        cand = Candidate(i=0, start_s=row.start_s, end_s=row.end_s,
                         dur_s=row.end_s - row.start_s, n_syllables=0,
                         midi=float("nan"), rms_db=0.0)
        clip = cut(vocal, cand)
        if clip.shape[1] < int(0.02 * config.SAMPLE_RATE):
            print(f"  skipped {name}: region is too short after trimming")
            continue

        path = audio_io.write_wav(args.out / name, clip)
        midi, dur = measure(clip, config.SAMPLE_RATE, device)
        n_syl = config.WORD_SYLLABLES[row.word]
        bounds = syllable_boundaries(clip, config.SAMPLE_RATE, n_syl)

        bank[name] = {
            "word": row.word,
            "variant": variant,
            "source_start_s": round(row.start_s, 3),
            "source_end_s": round(row.end_s, 3),
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
    print("\n  Syllable boundaries above are detected. To correct one by ear, edit")
    print("  syllable_bounds_s in words.json and add \"hand_corrected\": true so a")
    print("  later rebuild keeps your values.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
