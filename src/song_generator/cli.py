"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

from . import __version__, arrange, audio_io, config
from .analysis import analyse, report as analysis_report
from .detect import detect_vocal
from .mapping import (
    BankError, clean_slots, decide_shifts, load_bank, mimicry, plan_words,
    precompute_shifted, render, resolve_bank, mix as mix_buses,
    report as mapping_report,
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
drew the line -- the thresholds are all in src/song_generator/config.py under
"STAGE 1b".\
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="song_generator",
        description="Replace a song's vocals with sung Finnish word samples.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input", type=Path, help="input song (mp3, or anything ffmpeg reads)")
    p.add_argument("-o", "--output", type=Path, default=None,
                   help="base name for the output. The level and the mimicry "
                        "setting are added to it, so one run writes "
                        "<name>.<level>.mim<N>.mp3 "
                        "[default: output/<input stem>.song_generator.mp3]")
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
    p.add_argument("--raw-clips", action="store_true",
                   help="sing from the recorded clips even when a standardised "
                        "tier exists beside them")
    p.add_argument("--bare-syllables", action="store_true",
                   help="let lone syllables be sung on their own, not just used to "
                        "spell words (the pre-words-only behaviour)")
    p.add_argument("--seed", type=int, default=None,
                   help="arrangement seed [default: a new one each run, so every "
                        "run plays differently; it is printed and logged]")
    p.add_argument("--play", default=None, choices=sorted(config.PLAY_LEVELS),
                   help="render only this level [default: every level in "
                        "PLAY_BOTH_LEVELS, so both are there to choose between]")
    p.add_argument("--arrangement", type=Path, default=None,
                   help="replay an arrangement from a log file instead of "
                        "making a new one; edit the file to change what is sung")
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


def output_path(explicit: Path | None, song: Path) -> Path:
    """Where a run writes, with every song in a folder of its own.

    A run writes fourteen files and there are a dozen songs, so flat that is
    nearly two hundred sorted by name, interleaving every song's levels and
    rungs. The song name stays in the filename as well, so a file dragged out
    of its folder still says what it is.
    """
    base = explicit or Path("output") / f"{song.stem}.mp3"
    return base.parent / base.stem / base.name


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.input.is_file():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return EXIT_ERROR

    output = output_path(args.output, args.input)
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
    singing_from, standardised = resolve_bank(
        words_dir, prefer_standardised=not args.raw_clips)
    try:
        # --bare-syllables travels as an argument, never as a config write: a
        # module global set here outlives this run, and batch renders many
        # songs in one process, so every later song would inherit it.
        units = load_bank(words_dir, prefer_standardised=not args.raw_clips,
                          singable_only=False,
                          place_bare_syllables=True if args.bare_syllables else None)
        if not args.json:
            how = "standardised" if standardised else "as recorded"
            print(f"  bank      {args.bank} ({singing_from}, {how})")
    except BankError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    slots, merged, split = clean_slots([n.__dict__ for n in analysis.notes])

    cannot_say = arrange.unreachable_words(units)
    if cannot_say and not args.json:
        print(f"  BANK      holds no clip saying: {', '.join(cannot_say)}")

    # Both levels, every time. Which one is funnier is a listening decision, so
    # a run that produced one of them and offered the other had not finished
    # the job. They are separate arrangements with separate seeds, and each
    # writes its own log, so either can be brought back on its own.
    if args.arrangement:
        levels = [None]
    elif args.play:
        levels = [args.play]
    else:
        levels = list(config.PLAY_BOTH_LEVELS)

    single = args.no_shift or args.mix is not None or args.mimicry is not None
    targets = [None] if single else list(config.MIMICRY_VARIANTS)
    written: list[tuple[Path, str, float, int]] = []
    last_plan = None

    for level in levels:
        try:
            if level is None:
                described = arrange.load(args.arrangement)
                word_plan = arrange.realise(described, slots, units)
                label = described.level or "replay"
                if not args.json:
                    print(f"  arrangement replayed from {args.arrangement}")
            else:
                seed = args.seed if args.seed is not None else random.randrange(1, 1_000_000)
                word_plan, described, tries = arrange.build(
                    slots, units, level, seed,
                    song=args.input.stem, bank=str(singing_from))
                saved = arrange.save(described, work)
                label = level
                if not args.json:
                    redrawn = "" if tries == 1 else f", redrawn {tries - 1}x for coverage"
                    print(f"  play      {level}, seed {described.seed}{redrawn}")
                    print(f"  words     {saved}")
        except arrange.ArrangementError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_ERROR

        # Only what a redraw could have found. A word no clip contains is
        # already reported once against the bank, and repeating it per level
        # said the same thing three times while burying the case that matters:
        # a word the bank HAS and this arrangement happened to miss.
        missing = [w for w in described.missing() if w not in cannot_say]
        if missing and not args.json:
            print(f"  MISSING   {label} never says: {', '.join(missing)}")
        word_plan.merged, word_plan.split = merged, split
        last_plan = word_plan

        # The resynthesis is shared across the mimicry sweep: which units a
        # variant shifts is only a selection over the same shifted set.
        cache = None if args.no_shift else precompute_shifted(
            word_plan, config.SAMPLE_RATE, args.engine)

        for target in targets:
            if single:
                decide_shifts(word_plan, mix=0.0 if args.no_shift else args.mix,
                              mode=args.mix_mode, seed=args.seed,
                              target_mimicry=args.mimicry)
                stem = f"{output.stem}.{label}" if len(levels) > 1 else output.stem
                path = output.with_name(f"{stem}{output.suffix}")
            else:
                decide_shifts(word_plan, mode=args.mix_mode, seed=args.seed,
                              target_mimicry=target)
                tag = f"{target:.2f}".replace(".", "p")
                # The level goes in the name only when there is more than one
                # to tell apart. Appending it unconditionally doubled it onto
                # an --output that already named a level.
                stem = f"{output.stem}.{label}" if len(levels) > 1 else output.stem
                path = output.with_name(f"{stem}.mim{tag}{output.suffix}")

            word_bus = render(word_plan, stems.instrumental.shape[1], config.SAMPLE_RATE,
                              shift=not args.no_shift, engine=args.engine, cache=cache)
            audio_io.encode_mp3(path, mix_buses(word_bus, stems.instrumental,
                                                config.SAMPLE_RATE))
            written.append((path, label, mimicry(word_plan),
                            sum(1 for p in word_plan.placements if p.do_shift)))

        if not args.json:
            print(mapping_report(word_plan, units))
            print()

    word_plan = last_plan

    if not args.json:
        if len(written) == 1:
            print(f"  wrote     {written[0][0]}")
        else:
            print(f"  wrote {len(written)} versions to {output.parent.resolve()}")
            print()
            print("    level         mimicry   units singing   file")
            for path, label, got, singing in written:
                note = "  <- ignores the tune" if got <= 0 else ""
                print(f"    {label:<12}   {got:.2f}      {singing:>3}"
                      f"      {path.name}{note}")
        print(f"  analysis  {work / 'analysis.json'}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
