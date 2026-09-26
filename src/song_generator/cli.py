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
from . import turns as take
from .analysis import analyse, report as analysis_report
from .detect import detect_vocal
from .mapping import (
    BankError,
    Plan,
    clean_slots,
    swallow_slots,
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


def swallow_range(text: str) -> tuple[str | None, float, float]:
    """One --swallow value: "2-4", "3", or a voice's own, "keskisarja=2.4".

    Returns (voice or None, lo, hi) in words. Only the mean is used as the
    pace, so a range and its midpoint render the same; a range is accepted
    because that is how the words to swallow are naturally described.
    """
    voice, _, spec = text.rpartition("=")
    lo, _, hi = spec.partition("-")
    try:
        lo_f, hi_f = float(lo), float(hi or lo)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a word count, a range like 2-4, or VOICE=2.4,"
            f" got {text!r}") from None
    if not 0 < lo_f <= hi_f:
        raise argparse.ArgumentTypeError(f"expected 0 < LO <= HI, got {text!r}")
    return (voice or None), lo_f, hi_f


def swallow_words(args: argparse.Namespace, voice: str) -> float | None:
    """How many of the song's words this voice's bank words swallow, or None.

    A voice's own value wins over the one given for everybody, so one voice
    can be quickened without moving the other.
    """
    chosen = None
    for who, lo, hi in args.swallow or []:
        if who == voice or (who is None and chosen is None):
            chosen = (lo + hi) / 2
            if who == voice:
                break
    return chosen


def swallow_notes(words: float, units) -> float:
    """Words to swallow per bank word, as notes per bank syllable.

    The analysis finds notes, one per sung syllable, and the planner puts one
    bank syllable on each slot. So a bank word swallowing N words needs each
    of its syllables to take N * RAP_WORD_SYLLABLES notes, shared out over the
    syllables the bank's words have on average. Never under one note: a bank
    syllable cannot sound on part of one.
    """
    words_held = sum(len(u.words) for u in units)
    bank_syllables = (sum(u.syllables for u in units) / words_held
                      if words_held else 1.0)
    return max(1.0, words * config.RAP_WORD_SYLLABLES / bank_syllables)


def _number_word(value: float) -> str:
    return f"{value:g}".replace(".", "p")


def swallow_word(args: argparse.Namespace) -> str | None:
    """--swallow as it is spelled in a filename: swallow2-4, and a voice's
    own after it, swallow2-4-keskisarja2p4."""
    if not args.swallow:
        return None
    parts = []
    # Everybody's value first, then each voice's own in name order, so the
    # same request is one filename however its values were typed.
    for who, lo, hi in sorted(args.swallow, key=lambda s: (s[0] is not None,
                                                           s[0] or "")):
        span = _number_word(lo) if lo == hi else f"{_number_word(lo)}-{_number_word(hi)}"
        parts.append(f"{who}{span}" if who else span)
    return "swallow" + "-".join(parts)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="song_generator",
        description="Replace a song's vocals with sung Finnish word samples.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input", type=Path, help="input song (mp3, or anything ffmpeg reads)")
    p.add_argument("-o", "--output", type=Path, default=None,
                   help="base name for the output. The level is added to it, "
                        "so a run writes <name>.<level>.mp3, and anything "
                        "asked for specially is named too: --mimicry 0.6 "
                        "writes <name>.<level>.mim0p60.mp3 "
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
    p.add_argument("--bank", default=None, choices=sorted(config.BANKS),
                   help="which prebuilt bank to sing with")
    p.add_argument("--words-dir", type=Path, default=None,
                   help="a bank directory directly, overriding --bank")
    p.add_argument("--voices", nargs="+", default=None, metavar="BANK",
                   choices=sorted(config.BANKS),
                   help="sing from several banks, the voice changing wherever "
                        "the original singer does, in the order given; "
                        "replaces --bank [needs: pip install -e .[voices]]")
    p.add_argument("--swallow", type=swallow_range, nargs="+", default=None,
                   metavar="WORDS",
                   help="each bank word swallows this many of the original's "
                        "words, sounding across them and following their "
                        "tune, for rap, where one bank syllable per rapped "
                        "syllable is far too many words. 2-4 for everybody, "
                        "VOICE=2.4 for one voice of --voices: 2-4 "
                        "keskisarja=2.4 makes keskisarja a quarter quicker")
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
                        "solves for the shift this song needs [default: 1.0, "
                        "the melody whole]")
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


def refuse_contradicting_voices(parser: argparse.ArgumentParser,
                                args: argparse.Namespace) -> None:
    """--voices with anything that names one bank, or a single voice.

    Refused rather than resolved, for the reason --ladder is: whichever one
    lost would lose without a word. --words-dir points at one directory, and a
    replayed arrangement belongs to the one bank that wrote it; a multi-voice
    run writes one log per voice, and nothing replays them together.
    """
    if args.voices is None:
        return
    if len(set(args.voices)) < 2:
        parser.error("--voices takes turns between at least two different "
                     "banks; for one, use --bank")
    repeated = sorted({v for v in args.voices if args.voices.count(v) > 1})
    if repeated:
        # Turns go round the list, so a bank named twice lands on two turns
        # in a row wherever the list wraps, and that change of singer is
        # sung in one voice: the thing alternation exists to prevent.
        parser.error(f"--voices names {', '.join(repeated)} more than once")
    if args.bank is not None:
        parser.error("--voices names its banks itself, so it cannot be "
                     "combined with --bank, which names one")
    if args.words_dir is not None:
        parser.error("--voices names its banks from the bank table, so it "
                     "cannot be combined with --words-dir, which names one")
    if args.arrangement is not None:
        parser.error("--arrangement replays one bank's log, and a --voices "
                     "run writes one log per voice, so the two cannot be "
                     "combined")


def singing_names(args: argparse.Namespace) -> list[str]:
    """Who sings in this run: every voice, or the one bank, or the directory
    --words-dir points at. One definition, because the output folder, the
    --swallow check and the render all have to agree on it."""
    if args.voices:
        return list(args.voices)
    return [args.words_dir.name if args.words_dir
            else args.bank or config.DEFAULT_BANK]


def output_bank_name(args: argparse.Namespace) -> str:
    """The name outputs are filed under: the chosen bank, the directory itself
    when --words-dir bypasses the bank table, or every voice joined by "+" when
    several take turns, so a turn-taking render never lands in the folder of
    one of its banks and replaces that bank's own take."""
    return "+".join(singing_names(args))


def refuse_contradicting_swallow(parser: argparse.ArgumentParser,
                                 args: argparse.Namespace) -> None:
    """Two paces for one voice, or a pace for a voice that is not singing.

    Refused for the reason every contradiction here is: whichever value lost
    would lose without a word, and a pace given to a misspelt voice would
    leave that voice at the default while the filename claimed otherwise.
    """
    if not args.swallow:
        return
    everybody = [s for s in args.swallow if s[0] is None]
    if len(everybody) > 1:
        parser.error("--swallow takes one value for every voice; give a "
                     "voice its own as VOICE=WORDS")
    named = [s[0] for s in args.swallow if s[0] is not None]
    repeated = sorted({n for n in named if named.count(n) > 1})
    if repeated:
        parser.error(f"--swallow names {', '.join(repeated)} more than once")
    singing = set(singing_names(args))
    unknown = sorted(set(named) - singing)
    if unknown:
        parser.error(f"--swallow names {', '.join(unknown)}, which is not "
                     f"singing in this run ({', '.join(sorted(singing))})")


def arrange_voices(voices, voice_slots, turns, level: str, seed: int,
                   song: str):
    """Every voice's arrangement, and the one plan they sing together.

    Returns (plan, one Arrangement per voice, draws per voice, the voice of
    each placement). One voice is arrange.build and nothing more.

    Several voices are each arranged over the whole song from the one seed,
    and take_turns keeps each voice's placements inside its own turns. Each
    build is told which moments its voice sings, so its redraws and its
    relaxing of preferences for a missing word judge the coverage that will
    be heard, not coverage the other voice's turns then take away. The same
    seed brings the whole take back.

    The Arrangement returned per voice describes what that voice sings in the
    take and nothing else, so its log reads as what was heard.
    """
    n = len(voices)
    # A voice that owns no turn, when fewer turns were found than there are
    # voices, would be judged on nothing and spend every redraw on it.
    heard = {k % n for k in range(len(turns))} if n > 1 else {0}
    plans, whole, draws = [], [], []
    for v, (name, voice_dir, singing_from, units) in enumerate(voices):
        if v not in heard:
            silent = Plan()
            plans.append(silent)
            whole.append(arrange.describe(silent, song, str(singing_from),
                                          level, seed))
            draws.append(0)
            continue
        sings = None if n == 1 else (
            lambda t, v=v: take.voice_of(turns, n, t) == v)
        plan, described, tries = arrange.build(
            voice_slots[name], units, level, seed, song=song,
            bank=str(singing_from), bank_dir=voice_dir, sings=sings)
        plans.append(plan)
        whole.append(described)
        draws.append(tries)
    if n == 1:
        return plans[0], whole, draws, [0] * len(plans[0].placements)

    plan, owners = take.take_turns(
        plans, turns, [voice_slots[name] for name, *_ in voices])
    sung = [arrange.describe(
                Plan(placements=[p for p, o in zip(plan.placements, owners)
                                 if o == v]),
                song, whole[v].bank, level, whole[v].seed)
            for v in range(n)]
    return plan, sung, draws, owners


def refuse_other_grid(logged: float | None, current: float | None,
                      path: Path, logged_words: float | None = None) -> None:
    """A replayed log on a slot grid it was not made on.

    Replay anchors each line to the nearest slot and its recorded slot count,
    so the same log on a grid swallowed differently sings every word over a
    different number of notes. The log records its grid and replay rebuilds
    it; this is only asked when --swallow was given as well, and a value that
    disagrees with the log stops rather than winning.
    """
    same = (logged is None and current is None) or (
        logged is not None and current is not None
        and abs(logged - current) < 1e-3)
    if same:
        return
    made = ("unswallowed notes" if logged is None
            else f"{logged:.4f} notes per bank syllable")
    now = ("unswallowed notes" if current is None
           else f"{current:.4f} notes per bank syllable")
    if logged is None:
        advice = "It was made without --swallow; leave --swallow out."
    else:
        advice = "Leave --swallow out and the log's own grid is used."
        if logged_words is not None:
            advice += (f" It was made with --swallow {logged_words:g}; if this"
                       " run was given that too, the bank has changed since.")
    raise arrange.ArrangementError(
        f"{path} was arranged on {made}, and this run folds {now}.\n    "
        + advice)


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
    asked for by name now.

    Asking for it and naming a single setting at the same time is refused
    rather than resolved. Letting the narrower one quietly win meant
    `--ladder --mimicry 1` wrote the two plain takes, over the top of the two
    already there, and said nothing about having dropped the ladder somebody
    had just typed.
    """
    if args.ladder:
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


def rung_word(value: float) -> str:
    """A mimicry rung as it is spelled in a filename. 0.6 becomes mim0p60."""
    return f"mim{value:.2f}".replace(".", "p")


def variant_tag(args: argparse.Namespace) -> str | None:
    """What this render is called, when it is not the one a plain run makes.

    The plain name belongs to the take a plain run writes. Anything asked for
    specially says in the filename what was special about it, so an experiment
    cannot quietly replace the take somebody kept and decided to keep.

    This used to fall out for free: the default walked the mimicry ladder and
    every one of its files carried a rung, while the one-off renders carried
    none. Once the default became two files with no rung in the name, every
    one-off started writing the default's own filenames instead.

    None means this IS the plain take. Full mimicry counts as plain, because
    it is what a plain run renders and what the site asks for by name.

    A replay is tagged too. `--arrangement` is advertised as the way to edit
    what gets sung and hear the change, so the usual replay is a different
    rendering wearing the same level, and it was landing on top of the take
    somebody had kept and gone to the trouble of editing from.

    The rung is compared as it will be spelled, to two decimals, so nothing
    can sit one ten-thousandth away from full mimicry and take the name the
    ladder gives its own top rung.
    """
    if args.arrangement:
        return join_tags("replay", swallow_word(args))
    return join_tags(_shift_tag(args), swallow_word(args))


def join_tags(*tags: str | None) -> str | None:
    """Several filename tags as one, in order, skipping the absent ones."""
    present = [t for t in tags if t]
    return ".".join(present) if present else None


def _shift_tag(args: argparse.Namespace) -> str | None:
    """The shift part of variant_tag: a rung, --mix or --no-shift."""
    if args.no_shift:
        return "noshift"
    if args.mix is not None:
        return f"mix{args.mix:.2f}".replace(".", "p")
    rung = single_mimicry(args)
    return None if rung_word(rung) == rung_word(config.FULL_MIMICRY) \
        else rung_word(rung)


def versioned_name(output: Path, label: str, tag: str | None = None) -> Path:
    """The filename for one rendered version: the level, then what it is.

    Every path a render writes goes through here, which is the point: the
    level went into the name at one of two sites and not the other, so two
    single-level runs of one song wrote the same names and the second
    silently replaced the first. One function cannot disagree with itself.

    The level always goes in. The guard against doubling it checks the name
    rather than counting anything, so an --output that already names a level
    is left alone. The tag is the whole word, `mim0p60` or `noshift`, rather
    than digits with a prefix added here, because not every variant of a
    render is a mimicry rung.
    """
    stem = output.stem
    if label and not stem.endswith(f".{label}"):
        stem = f"{stem}.{label}"
    if tag is not None:
        stem = f"{stem}.{tag}"
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

    A run writes two files, `--ladder` writes fourteen, and there are dozens
    of songs, so flat that is hundreds sorted by name, interleaving every
    song's levels and rungs. The song name stays in the filename as well, so a
    file dragged out of its folder still says what it is.

    Banks get the same treatment for the same reason, one level down. The
    same song sung from two banks writes names that differ in
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
    bank_name = output_bank_name(args)
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
    parser = build_parser()
    args = parser.parse_args(argv)

    # Said here rather than resolved silently. --ladder means seven rungs per
    # level; --mimicry, --mix and --no-shift each name one shift outright.
    # Asked for together they contradict, and whichever one lost used to lose
    # without a word: `--ladder --mimicry 1` wrote the two plain takes over
    # the two already there and reported "2 versions" as though that had been
    # the request.
    named = [flag for flag, given in (("--mimicry", args.mimicry is not None),
                                      ("--mix", args.mix is not None),
                                      ("--no-shift", args.no_shift)) if given]
    if args.ladder and named:
        parser.error(f"--ladder renders every rung, so it cannot be combined "
                     f"with {named[0]}, which names one")
    refuse_contradicting_voices(parser, args)
    refuse_contradicting_swallow(parser, args)
    # --bank has no default in the parser so that naming it beside --voices
    # can be told apart from not naming it. Resolved here, after the check.
    if args.bank is None:
        args.bank = config.DEFAULT_BANK

    if args.rollback:
        # Before anything expensive. Rolling back needs neither stems nor a
        # bank nor a GPU, and asking for them would make the one command you
        # reach for when a render went wrong the slowest one there is.
        return _rollback(args)

    if not args.input.is_file():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return EXIT_ERROR

    bank_name = output_bank_name(args)
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

    # One voice unless --voices named several. Each is (name, directory the
    # run was pointed at, directory actually sung from, its units); a plain
    # run is a list of one, so everything below serves both.
    names = singing_names(args)
    voices: list[tuple[str, Path, Path, list]] = []
    bus_levels: set[float | None] = set()
    for name in names:
        words_dir = (args.words_dir if args.words_dir and not args.voices
                     else Path(config.BANKS[name]))
        # A bank may sit at its own level against the bed. A speaking voice
        # needs more than a shouted one to be heard over a band. banks resolves
        # a standardised tier back to the bank beside it, so --words-dir pointed
        # at either finds the same declaration.
        # This is also where a malformed bank.json is refused: banks validates
        # the whole file on every read, so catching its refusal here turns it
        # into an error with the error exit code rather than a traceback.
        try:
            bus_levels.add(banks.mix_for(words_dir).get("word_bus_lufs"))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_ERROR
        singing_from, standardised = resolve_bank(
            words_dir, prefer_standardised=not args.raw_clips)
        try:
            # --bare-syllables travels as an argument, never as a config write: a
            # module global set here outlives this run, and batch renders many
            # songs in one process, so every later song would inherit it.
            voice_units = load_bank(words_dir, prefer_standardised=not args.raw_clips,
                                    singable_only=False,
                                    place_bare_syllables=True if args.bare_syllables else None)
            if not args.json:
                how = "standardised" if standardised else "as recorded"
                print(f"  bank      {name} ({singing_from}, {how})")
        except BankError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_ERROR
        voices.append((name, words_dir, singing_from, voice_units))

    # The voices share one word bus, and the bus is levelled once. Two banks
    # declaring different levels cannot both be honoured, and quietly picking
    # one would put the other where its bank.json says it must not be.
    if len(bus_levels) > 1:
        declared = ", ".join(f"{n}: {banks.mix_for(d).get('word_bus_lufs')}"
                             for n, d, _, _ in voices)
        print(f"error: the voices declare different word_bus_lufs ({declared}),"
              " and they share one word bus.", file=sys.stderr)
        return EXIT_ERROR
    bus_lufs = bus_levels.pop()
    words_dir = voices[0][1]
    units = [u for _, _, _, voice_units in voices for u in voice_units]

    slots, merged, split = clean_slots([n.__dict__ for n in analysis.notes])
    base_slots = slots
    # Each voice may swallow at its own pace, so each gets its own slots.
    voice_slots = {}
    swallow_per: dict[str, float] = {}
    for name, _, _, voice_units in voices:
        words = swallow_words(args, name)
        if words is None:
            voice_slots[name] = slots
            continue
        per = swallow_notes(words, voice_units)
        swallow_per[name] = per
        voice_slots[name] = swallow_slots(slots, per)
        if not args.json:
            who = f" ({name})" if len(voices) > 1 else ""
            print(f"  swallow{who}  each bank word over {words:g} of the song's"
                  f" words: {per:.2f} notes per bank syllable,"
                  f" {len(slots)} -> {len(voice_slots[name])} slots")
    slots = voice_slots[names[0]]

    unreachable = {name: arrange.unreachable_words(voice_units)
                   for name, _, _, voice_units in voices}
    # A word counts as unsayable only when no voice can say it; one voice
    # lacking it still leaves the other voice's turns to say it in.
    cannot_say = [w for w in unreachable[names[0]]
                  if all(w in missing for missing in unreachable.values())]
    if not args.json:
        for name, missing in unreachable.items():
            if missing:
                who = f" ({name})" if len(voices) > 1 else ""
                print(f"  BANK      holds no clip saying{who}: {', '.join(missing)}")

    turns: list[take.Turn] = []
    if len(voices) > 1:
        try:
            turns, cached, kept_previous = take.load_or_detect(
                work, stems.vocal, config.SAMPLE_RATE,
                [n.__dict__ for n in analysis.notes], device)
        except take.TurnError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_ERROR
        if not args.json:
            how = "cached" if cached else "measured"
            print(f"  turns     {len(turns)} singers' turns, {how} -> "
                  f"{work / take.TURNS_FILE}")
            for k, turn in enumerate(turns):
                print(f"    {fmt_duration(turn.start_s):>6} - "
                      f"{fmt_duration(turn.end_s):<6}  singer {turn.speaker:<3}"
                      f" -> {names[k % len(names)]}")
            if kept_previous is not None:
                print(f"  turns     measured again; the file before, with any"
                      f" hand edits, is {kept_previous}")
        if len(turns) < len(voices) and not args.json:
            print(f"  TURNS     only {len(turns)} turn(s) for {len(voices)}"
                  f" voices, so {', '.join(names[len(turns):])} sings nothing")

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
                # The log records the grid it was laid over, so replay
                # rebuilds that grid rather than asking for it to be retyped.
                # Only an explicit --swallow that disagrees is refused.
                if args.swallow:
                    refuse_other_grid(described.swallow,
                                      swallow_per.get(names[0]),
                                      args.arrangement, described.swallow_words)
                elif described.swallow_words is not None:
                    # So the filename names the grid the take was sung on.
                    args.swallow = [(None, described.swallow_words,
                                     described.swallow_words)]
                slots = (swallow_slots(base_slots, described.swallow)
                         if described.swallow else base_slots)
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
                word_plan, drawn, draws, owners = arrange_voices(
                    voices, voice_slots, turns, level, seed, args.input.stem)
                if len(voices) > 1 and not args.json:
                    # The run's own seed, which brings the whole take back.
                    # Each voice's log records the seed its draw survived on.
                    print(f"  play      {level}, seed {seed}")
                for (name, *_), described, tries in zip(voices, drawn, draws):
                    # Written down before saving, so a replay can refuse a
                    # grid the log was not made on instead of doubling the
                    # pace without a word.
                    described.swallow = swallow_per.get(name)
                    described.swallow_words = swallow_words(args, name)
                    # One log per voice, in a folder per voice: two banks at
                    # one seed and level would otherwise share a filename.
                    saved = arrange.save(
                        described, work if len(voices) == 1
                        else work / config.VOICES_LOG_DIR / name)
                    if not args.json:
                        redrawn = ("" if tries <= 1
                                   else f", redrawn {tries - 1}x for coverage")
                        if len(voices) == 1:
                            print(f"  play      {level}, seed {described.seed}{redrawn}")
                        else:
                            print(f"  voice     {name}{redrawn}")
                        print(f"  words     {saved}")
                label = level
                if len(voices) > 1 and not args.json:
                    for v, (name, *_) in enumerate(voices):
                        print(f"  voice     {name} sings "
                              f"{owners.count(v)} of {len(owners)} units")
        except arrange.ArrangementError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_ERROR

        # Only what a redraw could have found. A word no clip contains is
        # already reported once against the bank, and repeating it per level
        # said the same thing three times while burying the case that matters:
        # a word the bank HAS and this arrangement happened to miss.
        # Several voices are read off the plan they ended up singing together,
        # since each arrangement's own coverage was counted over the whole song
        # and half of every one of them has been handed to another voice.
        if len(voices) == 1 or level is None:
            unsaid = described.missing()
        else:
            said = {w for p in word_plan.placements for w in p.unit.words}
            unsaid = [w for w in arrange.required_words() if w not in said]
        missing = [w for w in unsaid if w not in cannot_say]
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
                path = versioned_name(output, label, tag=variant_tag(args))
            else:
                decide_shifts(word_plan, mode=args.mix_mode, seed=args.seed,
                              target_mimicry=target)
                # Every rung of a ladder is tagged, including the top one:
                # seven files have to be told apart from each other, and
                # mim1p00 is what the ladder has always called that file.
                path = versioned_name(output, label, tag=join_tags(
                    rung_word(target), swallow_word(args)))

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
