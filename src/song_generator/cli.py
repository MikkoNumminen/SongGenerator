"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

from . import __version__, arrange, audio_io, banks, config
from .analysis import analyse, report as analysis_report
from .detect import detect_vocal
from .mapping import (
    BankError,
    clean_slots,
    decide_shifts,
    load_bank,
    mimicry,
    mix as mix_buses,
    precompute_shifted,
    render,
    report as mapping_report,
    resolve_bank,
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
    p.add_argument("--rollback", action="store_true",
                   help="swap the takes for this song and bank with the ones "
                        "they replaced, and render nothing")
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
    p.add_argument("--ladder", action="store_true",
                   help="render every rung of MIMICRY_VARIANTS rather than the "
                        "two files a run writes by default")
    p.add_argument("--mix", type=float, default=None, metavar="0..1",
                   help="drive the raw proportion of shifted units instead, "
                        "overriding --mimicry")
    p.add_argument("--mix-mode", choices=["furthest", "random"], default=None,
                   help="which units keep their own pitch")
    p.add_argument("--engine", choices=["world", "rubberband"], default=config.SHIFT_ENGINE,
                   help="pitch/time engine")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def drives_its_own_shift(args: argparse.Namespace) -> bool:
    """Whether the run was told exactly what to shift, rather than a rung.

    All three of these name the shift themselves, so there is no ladder to
    walk and the rung does not go into the filename.
    """
    return args.no_shift or args.mix is not None or args.mimicry is not None


def mimicry_targets(args: argparse.Namespace) -> list[float | None]:
    """Which mimicry rungs one run walks.

    `[None]` is one render per level, at whatever `single_mimicry` decides,
    and its filename carries no rung. Anything else is the ladder, where the
    rung has to go into the name to tell the files apart.

    The ladder used to be the default, which meant every run wrote fourteen
    near-identical files per song per bank; two of them were listened to and
    the other twelve had to be found and deleted by hand afterwards. It is
    asked for by name now, and naming a single setting beats asking for it,
    because a command that names one rung must not write fourteen files.
    """
    if args.ladder and not drives_its_own_shift(args):
        return list(config.MIMICRY_VARIANTS)
    return [None]


def single_mimicry(args: argparse.Namespace) -> float | None:
    """The rung one render sings at, when the ladder was not asked for.

    Full mimicry unless told otherwise, which is the same thing the site asks
    for by passing `--mimicry 1`. That matters for the filename rather than
    only the sound: a default that rendered a rung the site does not name
    would write `song.wild.mim1p00.mp3` where the site writes `song.wild.mp3`,
    and one song would sit in the library twice under two names.

    None means the shift was named directly, by `--mix` or `--no-shift`, and
    there is no rung to solve for.
    """
    if args.no_shift or args.mix is not None:
        return None
    return args.mimicry if args.mimicry is not None else config.FULL_MIMICRY


def versioned_name(output: Path, label: str, tag: str | None = None) -> Path:
    """The filename for one rendered version: level, then mimicry rung.

    Every path a render writes goes through here, which is the point: the
    level went into the name at one of two sites and not the other, so two
    single-level runs of one song wrote the same names and the second
    silently replaced the first. One function cannot disagree with itself.

    The level always goes in. The guard against doubling it checks the name
    rather than counting anything, so an --output that already names a level
    is left alone.
    """
    stem = output.stem
    if label and not stem.endswith(f".{label}"):
        stem = f"{stem}.{label}"
    if tag is not None:
        stem = f"{stem}.mim{tag}"
    return output.with_name(f"{stem}{output.suffix}")


# Where a replaced rendering goes. A folder rather than a suffix on the name,
# because the songs page lists `<bank>/*.mp3` and a `<song>.wild.previous.mp3`
# would show up there as a second take called "previous". A directory inside
# the bank is not walked as a bank and not listed as a rendering.
PREVIOUS_DIR = "previous"


def keep_the_one_it_replaces(target: Path) -> Path | None:
    """Move an existing rendering aside before it is overwritten.

    A render used to write straight over the take that was there, so a run
    that came out worse than the last one had nothing to go back to. One
    generation is kept, per song, bank and level, which is what the naming
    already separates.

    Exactly one. The previous file is replaced rather than accumulated,
    because two takes is a rollback and fifteen is the situation this repo
    just deleted seven gigabytes of.

    Nothing here deletes a rendering: the current take is moved, never
    removed, and the older backup it lands on is the only thing that goes.
    A render can therefore never cost more than the take before last, and
    never silently.

    Returns where it was put, or None when there was nothing to keep.
    """
    if not target.is_file():
        return None
    kept = target.parent / PREVIOUS_DIR / target.name
    kept.parent.mkdir(parents=True, exist_ok=True)
    # replace() rather than rename(): on Windows rename refuses to overwrite,
    # so the second re-render of a song would raise instead of rotating.
    target.replace(kept)
    return kept


def restore_the_previous(target: Path) -> Path | None:
    """Swap a rendering with the take it replaced. The rollback itself.

    A swap rather than a move, so the take being rolled back from becomes the
    new backup. Pressing this twice returns to where it started, which is what
    somebody comparing two takes by ear will do, and neither one is ever the
    thing that gets thrown away.

    Returns the restored file, or None when there is nothing kept for it.
    """
    kept = target.parent / PREVIOUS_DIR / target.name
    if not kept.is_file():
        return None
    if not target.is_file():
        # Nothing to swap with: the current take was deleted by hand, so this
        # is a plain restore.
        target.parent.mkdir(parents=True, exist_ok=True)
        kept.replace(target)
        return target
    spare = kept.with_suffix(kept.suffix + ".swapping")
    target.replace(spare)
    kept.replace(target)
    spare.replace(kept)
    return target


def output_path(explicit: Path | None, song: Path, bank: str) -> Path:
    """Where a run writes, with every song in a folder of its own and every
    bank in a folder inside that.

    A run writes fourteen files and there are a dozen songs, so flat that is
    nearly two hundred sorted by name, interleaving every song's levels and
    rungs. The song name stays in the filename as well, so a file dragged out
    of its folder still says what it is.

    Banks get the same treatment for the same reason, one level down. The
    same song sung from two banks is twenty-eight files whose names differ in
    nothing at all, so without the folder the second bank's render silently
    replaces the first. The folder is named for what --bank was given, or for
    the directory itself when --words-dir pointed somewhere directly.
    """
    base = explicit or Path("output") / f"{song.stem}.mp3"
    return base.parent / base.stem / bank / base.name


def _rollback(args) -> int:
    """Put the previous takes back for one song and bank.

    Every level at once, because that is how they were rendered: a run writes
    conservative and wild together, so a rollback that did one of them would
    leave a pair from two different runs and no way to tell by looking.
    """
    # The same two lines the render itself uses to decide where it writes.
    # Anything else would roll back a folder the render never touches.
    bank_name = args.words_dir.name if args.words_dir else args.bank
    out = output_path(args.output, args.input, bank_name)

    restored = []
    for candidate in sorted(out.parent.glob("*.mp3")):
        if restore_the_previous(candidate) is not None:
            restored.append(candidate)

    if not restored:
        print(f"error: nothing kept to roll back to in {out.parent}",
              file=sys.stderr)
        return EXIT_ERROR
    for path in restored:
        print(f"  rolled back {path}")
    print(f"\n  {len(restored)} restored. Running this again puts them back, "
          f"because the swap keeps both takes.")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.rollback:
        # Before anything expensive. Rolling back needs neither stems nor a
        # bank nor a GPU, and asking for them would make the one command you
        # reach for when a render went wrong the slowest one there is.
        return _rollback(args)

    if not args.input.is_file():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return EXIT_ERROR

    # The name outputs are filed under: the chosen bank, or the directory
    # itself when --words-dir bypasses the bank table.
    bank_name = args.words_dir.name if args.words_dir else args.bank
    output = output_path(args.output, args.input, bank_name)
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
    # A bank may sit at its own level against the bed. A speaking voice
    # needs more than a shouted one to be heard over a band. banks resolves
    # a standardised tier back to the bank beside it, so --words-dir pointed
    # at either finds the same declaration.
    # This is also where a malformed bank.json is refused: banks validates
    # the whole file on every read, so catching its refusal here turns it
    # into an error with the error exit code rather than a traceback.
    try:
        bus_lufs = banks.mix_for(words_dir).get("word_bus_lufs")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
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
    levels: list[str | None]
    if args.arrangement:
        levels = [None]
    elif args.play:
        levels = [args.play]
    else:
        levels = list(config.PLAY_BOTH_LEVELS)

    targets = mimicry_targets(args)
    single = targets == [None]
    written: list[tuple[Path, str, float, int]] = []

    for level in levels:
        try:
            if level is None:
                # The arrangement belongs to the bank it was rendered from,
                # and the bank decides what words exist: a bank cut with
                # build_bank --raw calls every unit "raw", which no
                # vocabulary holds, and its own log has to replay.
                described = arrange.load(
                    args.arrangement,
                    bank_words={w for u in units for w in u.words})
                # The bank's declaration travels into replay too, so a
                # sequence bank's own log comes back whole and paced rather
                # than re-pitched per syllable and cut to its slots.
                word_plan = arrange.realise(described, slots, units,
                                            bank_dir=words_dir)
                label = described.level or "replay"
                if not args.json:
                    print(f"  arrangement replayed from {args.arrangement}")
            else:
                seed = args.seed if args.seed is not None else random.randrange(1, 1_000_000)
                word_plan, described, tries = arrange.build(
                    slots, units, level, seed,
                    song=args.input.stem, bank=str(singing_from),
                    # The directory the run was pointed at, tier or bank.
                    # banks resolves a tier back to the bank beside it, so
                    # the settings are always the bank's as declared: a
                    # standardised tier is a derivative of the bank, and
                    # reading settings from the tier made every one of them
                    # vanish the moment a tier was built or named.
                    bank_dir=words_dir)
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

        # The resynthesis is shared across the mimicry sweep: which units a
        # variant shifts is only a selection over the same shifted set.
        cache = None if args.no_shift else precompute_shifted(
            word_plan, config.SAMPLE_RATE, args.engine)

        for target in targets:
            if single:
                decide_shifts(word_plan, mix=0.0 if args.no_shift else args.mix,
                              mode=args.mix_mode, seed=args.seed,
                              target_mimicry=single_mimicry(args))
                path = versioned_name(output, label)
            else:
                decide_shifts(word_plan, mode=args.mix_mode, seed=args.seed,
                              target_mimicry=target)
                path = versioned_name(output, label,
                                      tag=f"{target:.2f}".replace(".", "p"))

            word_bus = render(word_plan, stems.instrumental.shape[1], config.SAMPLE_RATE,
                              shift=not args.no_shift, engine=args.engine, cache=cache)
            # Immediately before the write, so nothing can reach the encoder
            # without the take that was there being kept first.
            keep_the_one_it_replaces(path)
            audio_io.encode_mp3(path, mix_buses(word_bus, stems.instrumental,
                                                config.SAMPLE_RATE,
                                                word_bus_lufs=bus_lufs))
            written.append((path, label, mimicry(word_plan),
                            sum(1 for p in word_plan.placements if p.do_shift)))

        if not args.json:
            print(mapping_report(word_plan, units))
            print()

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
