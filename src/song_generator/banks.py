"""Per-bank behaviour, declared in a bank.json beside the clips.

One bank ran through one arrangement machinery and there was nothing to
declare. The second bank broke that: its words were spoken in an order that
carries the meaning, so they have to come back in that order, and "how should
these recordings be placed" turned out to be a property of the recordings
rather than of a run. A property of the recordings lives beside the
recordings, as a file in the bank directory:

    {
      "levels": {
        "conservative": {"strategy": "sequence",
                         "overrides": {"reading_speed": 0.8}},
        "wild": {"strategy": "arranged",
                 "overrides": {"chant_chance": 0.55, "chant_max": 6}}
      },
      "mix": {"word_bus_lufs": -11.0},
      "never_split": true
    }

Three strategies exist:

  arranged   the planner chooses units by role, fit and variety, from a seed,
             redrawn until every required word is covered. What every bank
             did before banks could declare anything.
  sequence   the units replayed in the order they were recorded, looping when
             they run out. No seed, no draws, no coverage. See
             mapping.plan_sequence.
  shuffled   the same reciting, in an order drawn from the seed. Nothing is
             cut, stretched or syllabified, because the placement is the
             reciting one; only the running order changes.

"overrides" sit on top of the level's parameters from PLAY_LEVELS, so a bank
can lean a level without redefining it. Only the knobs the level itself
defines may appear, plus reading_speed; an override nothing reads would leave
the level's own value in force with no complaint, so an unknown knob is
refused by name, like an unknown level or strategy. "sequence" reads exactly
one of them, reading_speed, the pace the bank is recited at: 1.0 is as
spoken, lower is slower, and it must lie within what the stretch engine can
deliver, the reciprocal of TIME_STRETCH_RANGE. The rest mean nothing to it.

"never_split" keeps every clip whole, and "mix" holds word_bus_lufs, the
level the bank's words sit at against the bed; see never_split and mix_for
below for why each is a property of the recordings rather than of a level.

Settings always come from the bank as declared. A standardised tier sits
beside its bank as a derivative of it, so every reader here resolves a tier
back to the bank first; pointing --words-dir at either finds the same file.

A bank with no bank.json gets "arranged" and no overrides, which is exactly
the behaviour every bank had before this file existed. tests/test_determinism.py
pins that for the existing bank, so an undeclared bank cannot drift.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config

# Every strategy a bank may declare. Listed once, here, so the refusal below
# can name what would have been accepted.
# "shuffled" is "sequence" with the running order drawn from the seed instead
# of taken from the recording. It exists because the only mode that neither
# cuts, stretches nor syllabifies a word is the reciting one, and that mode is
# deterministic: a bank declaring it for both levels wrote two identical files.
# Shuffling the order varies the take while leaving every clip exactly as it
# was recorded, at its own length.
STRATEGIES = ("arranged", "sequence", "shuffled")

SETTINGS_FILE = "bank.json"


def settings_dir(bank_dir: Path) -> Path:
    """The directory whose bank.json speaks for these clips.

    A standardised tier sits beside its bank as words_hq.std and is a
    derivative of it, not a different bank, so the settings belong to the
    bank however the tier was reached. The manifest marker decides what is
    a tier, the same rule mapping.resolve_bank uses to decide what is
    already levelled. A tier whose source bank is gone speaks for itself,
    which for a directory with no bank.json means the defaults.
    """
    bank_dir = Path(bank_dir)
    if (bank_dir.name.endswith(config.STD_SUFFIX)
            and (bank_dir / config.STD_MANIFEST).is_file()):
        source = bank_dir.with_name(bank_dir.name[:-len(config.STD_SUFFIX)])
        if source.is_dir():
            return source
    return bank_dir


def _a_number(value) -> bool:
    """JSON numbers only. bool passes isinstance(int) and is not a level."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _an_object(value) -> bool:
    """A JSON object. Everything in bank.json that nests must be one, and a
    section of the wrong shape used to surface as a bare AttributeError
    traceback rather than a refusal that names the file."""
    return isinstance(value, dict)


def _a_boolean(value) -> bool:
    """A JSON boolean. The string "false" is not one, and read loosely it
    counted as true, so a bank meaning to allow splitting kept every clip
    whole. The refusal is a ValueError like every other refusal here: the
    problem is the declared value, and one handler catches them all."""
    return isinstance(value, bool)


def reading_speed_range() -> tuple[float, float]:
    """The paces the stretch engine can deliver, slowest to fastest.

    A recited clip is rendered as one stretch whose ratio is the reciprocal
    of the pace, clamped to TIME_STRETCH_RANGE, so the deliverable paces are
    the reciprocals of that range. A declared pace outside it would pass the
    plan a duration the renderer will not produce: the clip would sound at
    the clamped pace while the planner's cursor advanced at the declared
    one, and every word would land on top of the word after it.
    """
    lo, hi = config.TIME_STRETCH_RANGE
    return 1.0 / hi, 1.0 / lo


def deliverable_speed(reading_speed: float) -> float:
    """reading_speed bounded to what the engine delivers.

    Declarations are validated against the same range, so for a declared
    bank this changes nothing. It exists for the programmatic callers of
    plan_sequence and realise, which take a speed directly: bounding it
    here keeps the cursor and the rendered sound agreeing at every entry
    point rather than only the declared one.
    """
    slowest, fastest = reading_speed_range()
    return min(max(float(reading_speed), slowest), fastest)


def _declared(bank_dir: Path) -> dict:
    """What this bank declares, or an empty dict when it declares nothing.

    Resolved through settings_dir, so asking about a standardised tier
    answers with what the bank beside it declared. Every reader of the
    declaration goes through here, which is what makes the tier rule a
    property of the settings rather than something each caller remembers.

    A malformed file is refused by name rather than read as empty. A bank
    that declared "sequence" and silently got "arranged" would still play,
    in the wrong order, which is the failure the file exists to prevent.
    The two numeric settings are checked the same way and for the same
    reason: a word_bus_lufs written as a string would otherwise surface as
    a TypeError deep inside the mix, blaming nothing.
    """
    path = settings_dir(bank_dir) / SETTINGS_FILE
    if not path.is_file():
        return {}
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not _an_object(settings):
        raise ValueError(
            f"{path} must hold a JSON object of settings,"
            f" got {type(settings).__name__}."
        )

    levels = settings.get("levels", {})
    if not _an_object(levels):
        raise ValueError(
            f'"levels" in {path} must be an object mapping level names to'
            f" declarations, got {levels!r}."
        )

    # Every declared level is checked whole, not only the one being asked
    # for. A typo in the level this run does not render would otherwise sit
    # unnoticed until the day that level runs.
    for level, declared in levels.items():
        if level not in config.PLAY_LEVELS:
            raise ValueError(
                f"unknown level {level!r} in {path}.\n"
                f"    Expected one of: {', '.join(sorted(config.PLAY_LEVELS))}.\n"
                "    A declaration under a level that does not exist would be"
                " ignored silently, and the level it meant would render"
                " arranged, in the wrong order."
            )
        if not _an_object(declared):
            raise ValueError(
                f"level {level!r} in {path} must be an object,"
                f" got {declared!r}."
            )
        strategy = declared.get("strategy", "arranged")
        if strategy not in STRATEGIES:
            raise ValueError(
                f"unknown strategy {strategy!r} for level {level!r} in {path}.\n"
                f"    Expected one of: {', '.join(STRATEGIES)}.\n"
                "    A bank that declares nothing gets 'arranged'."
            )
        overrides = declared.get("overrides", {})
        if not _an_object(overrides):
            raise ValueError(
                f'"overrides" for level {level!r} in {path} must be an object'
                f" of knob names to values, got {overrides!r}."
            )
        # Only knobs something reads. The level's own parameters may be
        # leant on, and reading_speed is the one knob the sequence strategy
        # reads on top of them. Anything else would sit in the merged dict
        # unread, leaving the level's own value in force with no complaint,
        # which is the same silent failure as a misspelled level.
        knobs = set(config.PLAY_LEVELS[level]) | {"reading_speed"}
        unknown = sorted(set(overrides) - knobs)
        if unknown:
            raise ValueError(
                f"unknown override {', '.join(repr(k) for k in unknown)} for"
                f" level {level!r} in {path}.\n"
                f"    Expected knobs the level defines in PLAY_LEVELS, or"
                " reading_speed.\n"
                "    An override nothing reads changes nothing and says"
                " nothing, which is the failure this file exists to prevent."
            )
        speed = overrides.get("reading_speed")
        if speed is not None:
            slowest, fastest = reading_speed_range()
            if not _a_number(speed) or not slowest <= speed <= fastest:
                raise ValueError(
                    f"reading_speed for level {level!r} in {path} must be a"
                    f" number between {slowest:g} and {fastest:g},"
                    f" got {speed!r}.\n"
                    "    It is the pace the bank is recited at: 1.0 is as"
                    " spoken, lower is slower. The bounds are what the"
                    " stretch engine delivers (TIME_STRETCH_RANGE): outside"
                    " them the renderer would clamp the stretch while the"
                    " planner kept the declared pace, and the words would"
                    " land on top of each other. Write 0.8, not \"0.8\"."
                )

    mix = settings.get("mix", {})
    if not _an_object(mix):
        raise ValueError(f'"mix" in {path} must be an object, got {mix!r}.')
    lufs = mix.get("word_bus_lufs")
    if lufs is not None and not _a_number(lufs):
        raise ValueError(
            f"word_bus_lufs in {path} must be a number, in LUFS, got {lufs!r}.\n"
            "    Write -11.0, not \"-11.0\"."
        )

    cap = settings.get("shift_cap_semitones")
    ceiling = float(config.SHIFT_CAP_SEMITONES)
    if cap is not None and (not _a_number(cap) or not 1.0 <= cap <= ceiling):
        raise ValueError(
            f"shift_cap_semitones in {path} must be a number between 1 and"
            f" {ceiling:g}, got {cap!r}.\n"
            "    It is how far this bank's voice may be moved before the shift"
            " is folded by whole octaves instead. The bound is"
            " SHIFT_CAP_SEMITONES, the tool's own limit and the default, read"
            " from config rather than repeated here so the two cannot"
            " disagree. A bank that tears before then says so."
            " Write 6.0, not \"6.0\"."
        )

    # A strategy that promises whole clips needs a bank that keeps them whole.
    for level, declared in levels.items():
        if (_an_object(declared) and declared.get("strategy") == "shuffled"
                and not settings.get("never_split", False)):
            raise ValueError(
                f"level {level!r} in {path} declares \"shuffled\" without"
                " \"never_split\": true.\n"
                "    shuffled exists because reciting is the only placement"
                " that neither cuts, stretches nor syllabifies a word, and"
                " that guarantee is never_split's to give. Without it the"
                " clips are cut at their syllables and scaled to their slots,"
                " which is the output the strategy was added to avoid, and"
                " nothing would say so."
            )

    keep_whole = settings.get("never_split", False)
    if not _a_boolean(keep_whole):
        raise ValueError(
            f"never_split in {path} must be true or false,"
            f" got {keep_whole!r}.\n"
            "    Write false, not \"false\": a JSON string is not a boolean,"
            " and read loosely it counted as true, so a bank meaning to"
            " allow splitting kept every clip whole."
        )
    return settings


def strategy_for(bank_dir: Path, level: str) -> str:
    """How this bank wants this level placed. "arranged" when it has not said."""
    levels = _declared(bank_dir).get("levels", {})
    return str(levels.get(level, {}).get("strategy", "arranged"))


def overrides_for(bank_dir: Path, level: str) -> dict:
    """This bank's adjustments to the level's parameters. Empty when none.

    Returned as a fresh dict so a caller merging it onto the level's own
    parameters cannot end up sharing state with anything.
    """
    levels = _declared(bank_dir).get("levels", {})
    return dict(levels.get(level, {}).get("overrides", {}))


def mix_for(bank_dir: Path | None) -> dict:
    """This bank's mix adjustments. Empty when it has not said.

    Separate from the level overrides because loudness is a property of the
    recordings, not of how playfully they are arranged. A speaking voice and a
    shouted one do not sit at the same level against a band, and the bank is
    the thing that knows which it is.

    A fresh dict, so a caller cannot end up sharing state with the settings.
    """
    if bank_dir is None:
        return {}
    return dict(_declared(bank_dir).get("mix", {}))


def shift_cap(bank_dir: Path | None) -> float:
    """How far this bank's voice may be moved before the shift is folded.

    A property of the recordings rather than of the tool. `SHIFT_CAP_SEMITONES`
    is 12 because 12 was measured and then judged by ear to sound better than
    7, but that was judged on SUNG banks, where the vocoder is resynthesising
    a voice already holding a note. A speaking voice tears sooner: this bank
    spans five semitones and was being dragged ten upward, and the words broke
    at the ends long before the tool thought it was asking too much.

    Lower it and more syllables fold to another octave instead, so the melody
    survives in part rather than in full. That is the trade, and it is worth
    taking when the alternative is a shift that tears: a word in the wrong
    octave is still the word.
    """
    if bank_dir is None:
        return config.SHIFT_CAP_SEMITONES
    declared = _declared(bank_dir).get("shift_cap_semitones")
    return config.SHIFT_CAP_SEMITONES if declared is None else float(declared)


def never_split(bank_dir: Path | None) -> bool:
    """True when no clip in this bank may be cut into pieces.

    A sung bank is cut apart constantly: syllables are re-pitched one by one
    onto their own notes, and slice_words takes single words out of recorded
    phrases so an order nobody sang can still be said. Both are wrong for a
    bank of spoken names, where half a word is not a shorter word, it is a
    different sound.

    Off by default, so a bank that has not said anything keeps being cut apart
    exactly as before.
    """
    if bank_dir is None:
        return False
    return bool(_declared(bank_dir).get("never_split", False))
