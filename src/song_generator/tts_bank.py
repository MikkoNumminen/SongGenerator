"""Stage 0b: build a bank from synthesized single-word clips.

Every other bank in this project is cut from a found recording: somebody
sang or shouted the word once, and the clip is whatever they did. A
synthesized source is different in one way that matters musically. The
engine has no pitch control, so it hands back one take at whatever pitch it
felt like, and a bank of one pitch per word is the case `PREFER_NEAREST_SOURCE_PITCH`
was written to avoid.

So this module does what a recording session cannot do cheaply: it takes
each synthesized take as a root and transposes it across a chromatic
ladder, so the planner can pick a take that is already near the note it
needs. `docs/WORKFLOWS.md` puts the reason plainly -- "Takes at new pitches
raise the mimicry ceiling directly, by reducing how much has to be
octave-folded. Ten more takes at the same pitch as everything else change
nothing."

What this does NOT do is invent musical decisions. The melody, the timing
and the target notes still come from the original singer exactly as before;
only the word audio is synthetic. See the closing section of AGENTS.md.

The ladder is built with Rubber Band rather than the render-time default of
WORLD, because a ladder is made of large shifts by construction and
SHIFT_ENGINE's own note records that WORLD "starts to sound vocoded" there.

Input is a manifest written by the synthesis side, which lives in another
repository because it needs a TTS engine this one deliberately does not
depend on. This module only reads wavs and a json index; it has no
knowledge of how they were made.

Usage:

    .\\.venv\\Scripts\\python.exe -m song_generator.tts_bank \\
        --roots ..\\AudiobookMaker\\.local\\word_bank \\
        --out words_tts

Then index the result the ordinary way:

    .\\.venv\\Scripts\\python.exe -m song_generator.build_bank \\
        --candidates words_tts_fi\\candidates --out words_tts_fi
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

from . import audio_io, config
from .build_bank import measure
from .pitchshift import Segment, render_unit
from .util import resolve_device

# The synthesis side stamps this into its manifest. Refusing an unknown
# format beats guessing at a layout that changed underneath us.
ROOTS_FORMAT = "audiobookmaker-word-bank/1"
ROOTS_MANIFEST = "roots.json"


class TtsBankError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------


def load_roots(roots_dir: Path) -> list[dict]:
    """Read the synthesis manifest and return its root entries."""
    path = roots_dir / ROOTS_MANIFEST
    if not path.is_file():
        raise TtsBankError(
            f"{path} not found.\n"
            f"    --roots must point at the directory holding "
            f"{ROOTS_MANIFEST}, written by the synthesis side."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    fmt = data.get("format")
    if fmt != ROOTS_FORMAT:
        raise TtsBankError(
            f"{path} is format {fmt!r}, expected {ROOTS_FORMAT!r}."
        )
    roots = data.get("roots", [])
    if not roots:
        raise TtsBankError(f"{path} lists no roots.")
    return roots


# ---------------------------------------------------------------------------
# naming
# ---------------------------------------------------------------------------


def ladder_steps() -> list[int]:
    span = int(config.TTS_LADDER_SEMITONES)
    step = max(1, int(config.TTS_LADDER_STEP))
    return list(range(-span, span + 1, step))


def variant_label(midi: int, expression: str) -> str:
    """The variant half of a clip name: a padded midi note plus a mood.

    Two constraints, both from `parse_phrase`:

    - It must not start with anything the bank vocabulary knows, or the
      greedy matcher eats part of the label. Leading with a digit is the
      simplest guarantee, and zero-padding keeps a directory listing in
      pitch order.
    - It must contain no separator character. `_SEPARATORS` includes "-"
      and "_", so neither may appear here even though `_VARIANT_RE` would
      accept them.

    Filenames end up on Windows, where an unsanitised measurement once
    wrote a literal "?" and lost a whole source, so this refuses anything
    that is not plain ASCII alphanumerics rather than trusting its callers.
    """
    label = f"{midi:03d}{expression}"
    if not (label.isascii() and label.isalnum()):
        raise TtsBankError(
            f"variant {label!r} is not usable in a filename. The expression "
            f"name must be ASCII letters and digits only."
        )
    return label


def clip_name(word: str, midi: int, expression: str) -> str:
    return f"{word}_{variant_label(midi, expression)}.wav"


# ---------------------------------------------------------------------------
# transposition
# ---------------------------------------------------------------------------


def shift_clip(mono: np.ndarray, sr: int, semitones: float,
               engine: str | None = None) -> np.ndarray:
    """Transpose a whole clip, keeping its length.

    One segment covering the entire clip, with the output duration equal to
    the source duration so `clamp_stretch` resolves to 1.0 and nothing is
    time-stretched. `glide` is off because there is no neighbouring syllable
    to slide into: this is one clip moved bodily, not a word being fitted to
    a melody.
    """
    duration = mono.shape[0] / sr
    if duration <= 0:
        return mono
    segment = Segment(
        src_start_s=0.0,
        src_end_s=duration,
        out_start_s=0.0,
        out_dur_s=duration,
        semitones=float(semitones),
        glide=False,
    )
    engine = engine or config.TTS_BANK_SHIFT_ENGINE
    return render_unit(mono, sr, [segment], duration, engine=engine)


# ---------------------------------------------------------------------------
# safety
# ---------------------------------------------------------------------------


def refuse_curated_destination(out_dir: Path, force: bool) -> None:
    """Never write into a bank somebody curated by hand.

    `recut_bank --out` once defaulted onto `words_hq` and would have
    overwritten eighteen hand-named recordings. AGENTS.md requires every new
    tool that writes clips to carry the same refusal, and to check again at
    write time rather than only at startup, since a clip can be renamed into
    a folder mid-run.
    """
    if force:
        return
    if not out_dir.is_dir():
        return

    # Clips are the evidence, not the name. A bank is hand work because
    # somebody named its clips by ear, and being listed in BANKS says nothing
    # about that: registering the name before the first build is the ordinary
    # way to set a new bank up, and refusing that would refuse the documented
    # workflow. A directory holding wavs is the case worth stopping, whether
    # or not it is registered.
    existing = sorted(out_dir.rglob("*.wav"))
    if not existing:
        return

    registered = {Path(p).resolve() for p in config.BANKS.values()}
    what = ("a bank registered in config.BANKS"
            if out_dir.resolve() in registered else "this directory")
    raise TtsBankError(
        f"{out_dir} is {what} and already holds {len(existing)} wav(s), "
        f"the first being {existing[0].name}.\n"
        f"    A clip with no review prefix is hand-confirmed by ear and "
        f"cannot be regenerated. Pick an empty directory, or pass --force "
        f"if this bank is entirely machine-written."
    )


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def build_ladder(roots_dir: Path, out_root: Path, language: str | None,
                 device: str | None, force: bool,
                 dry_run: bool = False) -> dict:
    """Expand every root into a chromatic ladder of pre-named clips."""
    roots = load_roots(roots_dir)
    if language:
        roots = [r for r in roots if r.get("language") == language]
        if not roots:
            raise TtsBankError(f"no roots for language {language!r}")

    steps = ladder_steps()
    by_language: dict[str, list[dict]] = {}
    for root in roots:
        by_language.setdefault(root.get("language", "xx"), []).append(root)

    written = 0
    skipped: list[str] = []
    per_bank: dict[str, int] = {}

    for lang, entries in sorted(by_language.items()):
        out_dir = Path(f"{out_root}_{lang}")
        if not dry_run:
            refuse_curated_destination(out_dir, force)
        candidates = out_dir / "candidates"

        for entry in entries:
            wav_path = roots_dir / entry["file"]
            if not wav_path.is_file():
                skipped.append(f"{entry['file']}: file missing")
                continue

            # read_wav resamples to config.SAMPLE_RATE when the file
            # disagrees, which is the whole 24 kHz -> 44.1 kHz conversion.
            clip = audio_io.read_wav(wav_path)
            root_midi, duration = measure(clip, config.SAMPLE_RATE, device)

            if not math.isfinite(root_midi):
                # An unpitched root cannot be laddered: there is no centre to
                # move away from, and its measured note would go into a
                # filename. Say so rather than writing a clip named "nan".
                skipped.append(
                    f"{entry['file']}: no measurable pitch, cannot ladder"
                )
                continue

            mono = audio_io.to_mono(clip)
            centre = int(round(root_midi))
            word = entry["word"]
            expression = entry["expression"]

            for k in steps:
                midi = centre + k
                if not 0 <= midi <= 127:
                    skipped.append(
                        f"{word}/{expression}: step {k:+d} lands on midi "
                        f"{midi}, outside the usable range"
                    )
                    continue
                name = clip_name(word, midi, expression)
                if dry_run:
                    written += 1
                    continue
                shifted = shift_clip(mono, config.SAMPLE_RATE, float(k))
                audio_io.write_wav(candidates / name, shifted,
                                   config.SAMPLE_RATE)
                written += 1
                per_bank[out_dir.name] = per_bank.get(out_dir.name, 0) + 1

            if not dry_run:
                print(f"  {word}/{expression}: {len(steps)} clips "
                      f"around midi {centre} ({duration:.2f}s)", flush=True)

    return {"written": written, "skipped": skipped, "banks": per_bank,
            "steps": len(steps)}


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Build a word bank from synthesized single-word clips.",
    )
    p.add_argument("--roots", required=True, type=Path,
                   help=f"directory holding {ROOTS_MANIFEST} and the root wavs")
    p.add_argument("--out", required=True, type=Path,
                   help="bank directory prefix; the language is appended, so "
                        "--out words_tts writes words_tts_fi and words_tts_en")
    p.add_argument("--language", default=None,
                   help="only build this language's roots")
    p.add_argument("--device", default=None,
                   help="torch device for pitch measurement (default: auto)")
    p.add_argument("--force", action="store_true",
                   help="write even if the destination already holds clips")
    p.add_argument("--dry-run", action="store_true",
                   help="report what would be written without writing it")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    device = resolve_device(args.device)

    try:
        report = build_ladder(args.roots, args.out, args.language, device,
                              args.force, args.dry_run)
    except TtsBankError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    verb = "would write" if args.dry_run else "wrote"
    print(f"\n{verb} {report['written']} clip(s), "
          f"{report['steps']} pitches per root")
    for bank, count in sorted(report["banks"].items()):
        print(f"  {bank}: {count}")

    # An index entry is a claim that the file exists, and a dropped entry
    # silently removes a word from every render, so anything excluded is
    # named here rather than left to be noticed later.
    for line in report["skipped"]:
        print(f"  skipped: {line}")

    if not args.dry_run:
        print("\nIndex each bank next:")
        for bank in sorted(report["banks"]):
            print(f"  python -m song_generator.build_bank "
                  f"--candidates {bank}\\candidates --out {bank}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
