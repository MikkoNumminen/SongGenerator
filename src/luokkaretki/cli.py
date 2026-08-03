"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from . import __version__, audio_io, config
from .analysis import analyse, report as analysis_report
from .detect import detect_vocal
from .mapping import (
    BankError, clean_slots, decide_shifts, load_bank, mimicry, plan_words,
    precompute_shifted, render, mix as mix_buses, report as mapping_report,
)
from .separate import SeparationError, separate
from .util import fmt_duration, resolve_device, work_dir_for

EXIT_OK = 0
EXIT_ERROR = 2
EXIT_MODE_B = 3

MODE_B_MESSAGE = """\
This song has no lead vocal to borrow from, so it is a MODE B song -- and Mode B
is not supported yet.

Mode A works by stealing every musical decision from the original singer: when
each syllable starts, how long it lasts, and what note it lands on. With no
vocal there is nothing to steal, and the tool would have to invent all three
against the backing track. That is composition rather than signal processing,
and doing it badly sounds obviously mechanical, so it is deliberately not
attempted rather than attempted and botched.

See docs/TODO.md for the full write-up of what Mode B would take.

If you believe this song DOES have vocals, the numbers above show which test
drew the line -- the thresholds are all in src/luokkaretki/config.py under
"STAGE 1b".\
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="luokkaretki",
        description="Replace a song's vocals with sung Finnish word samples.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input", type=Path, help="input song (mp3, or anything ffmpeg reads)")
    p.add_argument("-o", "--output", type=Path, default=None,
                   help="output mp3 [default: output/<input stem>.luokkaretki.mp3]")
    p.add_argument("--separator", choices=["demucs", "roformer"], default=config.SEPARATOR,
                   help="source separation backend")
    p.add_argument("--device", default=None, help="torch device, e.g. cuda or cpu [default: autodetect]")
    p.add_argument("--work-dir", type=Path, default=Path(config.WORK_DIR),
                   help="where stems and analysis are cached")
    p.add_argument("--force", action="store_true", help="ignore cached stems and separate again")
    p.add_argument("--json", action="store_true", help="print the analysis report as JSON")
    p.add_argument("--slim", action="store_true",
                   help="omit the raw F0 contour from analysis.json (stage 4 needs it)")
    p.add_argument("--rows", type=int, default=12, help="how many extracted notes to print")
    p.add_argument("--bank", default=config.DEFAULT_BANK, choices=sorted(config.BANKS),
                   help="which prebuilt bank to sing with")
    p.add_argument("--words-dir", type=Path, default=None,
                   help="a bank directory directly, overriding --bank")
    p.add_argument("--seed", type=int, default=None,
                   help="word choice seed [default: WORD_ROTATION_SEED in config.py]")
    p.add_argument("--no-words", action="store_true",
                   help="stop after analysis and write only the instrumental")
    p.add_argument("--no-shift", action="store_true",
                   help="place clips at their own recorded pitch (the step 3 sound)")
    p.add_argument("--mimicry", type=float, default=None, metavar="0..1",
                   help="how closely the words track the original singing; the tool "
                        "solves for the shift this song needs [default: MIMICRY]")
    p.add_argument("--mix", type=float, default=None, metavar="0..1",
                   help="drive the raw proportion of shifted units instead, "
                        "overriding --mimicry")
    p.add_argument("--mix-mode", choices=["furthest", "random"], default=None,
                   help="which units keep their own pitch")
    p.add_argument("--engine", choices=["world", "rubberband"], default=config.SHIFT_ENGINE,
                   help="pitch/time engine")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.input.is_file():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return EXIT_ERROR

    output = args.output or Path("output") / f"{args.input.stem}.luokkaretki.mp3"
    work = work_dir_for(args.input, args.work_dir)
    device = resolve_device(args.device)

    try:
        mix = audio_io.decode(args.input)
        duration = mix.shape[1] / config.SAMPLE_RATE

        if not args.json:
            print(f"  song      {args.input.name}  ({fmt_duration(duration)})")
            print(f"  device    {device}")
            print(f"  separator {args.separator}", flush=True)

        t0 = time.perf_counter()
        stems = separate(args.input, work, backend=args.separator, device=device, force=args.force)
        elapsed = time.perf_counter() - t0

        if not args.json:
            how = "cached" if stems.cached else f"{elapsed:.1f}s"
            print(f"  stems     {how} -> {work}")

        report = detect_vocal(stems.vocal, mix, config.SAMPLE_RATE, device)

    except SeparationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except audio_io.AudioError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    payload = {
        "input": str(args.input),
        "duration_s": round(duration, 2),
        "work_dir": str(work),
        "separator": stems.backend,
        "device": device,
        **report.as_dict(),
    }
    (work / "detect.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if not args.json:
        print()
        print("  vocal presence")
        print(f"    stem loudness     {report.vocal_lufs:6.1f} LUFS")
        print(f"    mix loudness      {report.mix_lufs:6.1f} LUFS")
        print(f"    relative          {report.rel_lu:6.1f} LU     "
              f"(needs >= {config.VOCAL_PRESENT_REL_LU:.1f})")
        print(f"    voiced frames     {report.voiced_frac * 100:6.1f} %      "
              f"(needs >= {config.VOCAL_PRESENT_VOICED_FRAC * 100:.1f}, via {report.f0_backend})")
        print(f"    verdict           {'MODE A -- vocals present' if report.vocal_present else 'MODE B -- no vocals'}")
        print()

    if not report.vocal_present:
        if args.json:
            print(json.dumps({**payload, "mode": "B"}, indent=2))
        else:
            for reason in report.reasons:
                print(f"    - {reason}")
            print()
            print(MODE_B_MESSAGE)
        return EXIT_MODE_B

    analysis = analyse(stems.vocal, stems.instrumental, config.SAMPLE_RATE, device)
    analysis.to_json(work / "analysis.json", include_f0=not args.slim)

    if args.json:
        durations = [n.dur_s for n in analysis.notes]
        print(json.dumps({
            **payload,
            "mode": "A",
            "tempo_bpm": round(analysis.tempo_bpm, 2),
            "n_beats": len(analysis.beats_s),
            "n_notes": len(analysis.notes),
            "n_phrases": len(analysis.phrases),
            "median_note_ms": round(float(np.median(durations)) * 1000, 1) if durations else None,
            "analysis_json": str(work / "analysis.json"),
        }, indent=2))
    else:
        print(analysis_report(analysis, max_rows=args.rows))
        print()

    if args.no_words:
        audio_io.encode_mp3(output, stems.instrumental)
        if not args.json:
            print(f"  wrote     {output}  (instrumental only, --no-words)")
        return EXIT_OK

    words_dir = args.words_dir or Path(config.BANKS[args.bank])
    try:
        units = load_bank(words_dir)
        if not args.json:
            print(f"  bank      {args.bank} ({words_dir})")
    except BankError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    slots, merged, split = clean_slots([n.__dict__ for n in analysis.notes])
    word_plan = plan_words(slots, units, seed=args.seed)
    word_plan.merged, word_plan.split = merged, split

    single = args.no_shift or args.mix is not None or args.mimicry is not None
    targets = [None] if single else list(config.MIMICRY_VARIANTS)

    # The resynthesis is shared: which units a variant shifts is only a
    # selection over the same shifted set, so the whole sweep costs barely
    # more than one render.
    cache = None if args.no_shift else precompute_shifted(
        word_plan, config.SAMPLE_RATE, args.engine)

    written: list[tuple[Path, float, int]] = []
    for target in targets:
        if single:
            decide_shifts(word_plan, mix=0.0 if args.no_shift else args.mix,
                          mode=args.mix_mode, seed=args.seed,
                          target_mimicry=args.mimicry)
            path = output
        else:
            decide_shifts(word_plan, mode=args.mix_mode, seed=args.seed,
                          target_mimicry=target)
            tag = f"{target:.2f}".replace(".", "p")
            path = output.with_name(f"{output.stem}.mim{tag}{output.suffix}")

        word_bus = render(word_plan, stems.instrumental.shape[1], config.SAMPLE_RATE,
                          shift=not args.no_shift, engine=args.engine, cache=cache)
        audio_io.encode_mp3(path, mix_buses(word_bus, stems.instrumental,
                                            config.SAMPLE_RATE))
        written.append((path, mimicry(word_plan),
                        sum(1 for p in word_plan.placements if p.do_shift)))

    mixed = None

    if not args.json:
        print(mapping_report(word_plan, units))
        print()
        if len(written) == 1:
            print(f"  wrote     {written[0][0]}")
        else:
            print(f"  wrote {len(written)} versions to {output.parent.resolve()}")
            print()
            print("    mimicry   units singing   file")
            for path, got, singing in written:
                note = "  <- ignores the tune" if got <= 0 else ""
                print(f"      {got:.2f}      {singing:>3}/{len(word_plan.placements):<3}"
                      f"      {path.name}{note}")
        print(f"  analysis  {work / 'analysis.json'}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
