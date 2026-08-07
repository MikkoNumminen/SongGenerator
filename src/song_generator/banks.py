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

Two strategies exist:

  arranged   the planner chooses units by role, fit and variety, from a seed,
             redrawn until every required word is covered. What every bank
             did before banks could declare anything.
  sequence   the units replayed in the order they were recorded, looping when
             they run out. No seed, no draws, no coverage. See
             mapping.plan_sequence.

"overrides" sit on top of the level's parameters from PLAY_LEVELS, so a bank
can lean a level without redefining it. "sequence" reads exactly one of them,
reading_speed, the pace the bank is recited at: 1.0 is as spoken, lower is
slower. The rest mean nothing to it.

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
STRATEGIES = ("arranged", "sequence")

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

    # Every declared strategy is checked, not only the one being asked for.
    # A typo in the level this run does not render would otherwise sit
    # unnoticed until the day that level runs.
    for level, declared in settings.get("levels", {}).items():
        strategy = declared.get("strategy", "arranged")
        if strategy not in STRATEGIES:
            raise ValueError(
                f"unknown strategy {strategy!r} for level {level!r} in {path}.\n"
                f"    Expected one of: {', '.join(STRATEGIES)}.\n"
                "    A bank that declares nothing gets 'arranged'."
            )
        speed = declared.get("overrides", {}).get("reading_speed")
        if speed is not None and (not _a_number(speed) or speed <= 0):
            raise ValueError(
                f"reading_speed for level {level!r} in {path} must be a number"
                f" above zero, got {speed!r}.\n"
                "    It is the pace the bank is recited at: 1.0 is as spoken,"
                " lower is slower. Write 0.8, not \"0.8\"."
            )

    lufs = settings.get("mix", {}).get("word_bus_lufs")
    if lufs is not None and not _a_number(lufs):
        raise ValueError(
            f"word_bus_lufs in {path} must be a number, in LUFS, got {lufs!r}.\n"
            "    Write -11.0, not \"-11.0\"."
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
