"""Per-bank behaviour, declared in a bank.json beside the clips.

One bank ran through one arrangement machinery and there was nothing to
declare. The second bank broke that: its words were spoken in an order that
carries the meaning, so they have to come back in that order, and "how should
these recordings be placed" turned out to be a property of the recordings
rather than of a run. A property of the recordings lives beside the
recordings, as a file in the bank directory:

    {
      "levels": {
        "conservative": {"strategy": "sequence"},
        "wild": {"strategy": "arranged",
                 "overrides": {"chant_chance": 0.55, "chant_max": 6}}
      }
    }

Two strategies exist:

  arranged   the planner chooses units by role, fit and variety, from a seed,
             redrawn until every required word is covered. What every bank
             did before banks could declare anything.
  sequence   the units replayed in the order they were recorded, looping when
             they run out. No seed, no draws, no coverage. See
             mapping.plan_sequence.

"overrides" sit on top of the level's parameters from PLAY_LEVELS, so a bank
can lean a level without redefining it. They mean nothing to "sequence",
which has no parameters.

A bank with no bank.json gets "arranged" and no overrides, which is exactly
the behaviour every bank had before this file existed. tests/test_determinism.py
pins that for the existing bank, so an undeclared bank cannot drift.
"""

from __future__ import annotations

import json
from pathlib import Path

# Every strategy a bank may declare. Listed once, here, so the refusal below
# can name what would have been accepted.
STRATEGIES = ("arranged", "sequence")

SETTINGS_FILE = "bank.json"


def _declared(bank_dir: Path) -> dict:
    """What this bank declares, or an empty dict when it declares nothing.

    A malformed file is refused by name rather than read as empty. A bank
    that declared "sequence" and silently got "arranged" would still play,
    in the wrong order, which is the failure the file exists to prevent.
    """
    path = Path(bank_dir) / SETTINGS_FILE
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
