"""Which banks exist on this machine, and whether they can actually sing.

The front end must not hardcode bank names. They live in a gitignored local
override, so they differ per machine, and `config.BANKS` on a fresh clone names
banks whose directories are empty because the clips are gitignored too. A
picker built from a union type would offer banks that cannot render and fail
deep inside `load_bank` when somebody pressed go.

So a bank is reported with whether it is built, not merely named, and "no bank
is built yet" is an ordinary answer rather than an error: it is the correct
state of a fresh clone, and the useful response to it is the command that fixes
it, not a stack trace.

Reads the index only, never the audio. Loading a bank's clips means reading
every wav in it, which is seconds and megabytes for a question the front end
asks on every page load.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BankInfo:
    """One bank as the front end needs to see it."""

    name: str
    directory: str
    built: bool
    units: int
    standardised: bool
    problem: str | None = None

    @property
    def usable(self) -> bool:
        return self.built and self.units > 0 and self.problem is None


def _read_index(index: Path) -> tuple[int, str | None]:
    """How many clips the index claims, or why it cannot be read."""
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return 0, f"words.json is not readable JSON ({exc.msg})"
    except OSError as exc:
        return 0, f"words.json could not be read ({exc.strerror or exc})"
    if not isinstance(data, dict):
        return 0, "words.json is not an object of clip entries"
    return len(data), None


def inspect(name: str, directory: Path, standardised_suffix: str) -> BankInfo:
    """Describe one bank without loading a single sample of audio."""
    index = directory / "words.json"
    if not index.is_file():
        return BankInfo(
            name=name,
            directory=str(directory),
            built=False,
            units=0,
            standardised=False,
            problem=None,  # not built is not a fault, it is a fresh clone
        )

    units, problem = _read_index(index)
    # The tier is preferred at render time when it carries both markers, the
    # same test resolve_bank makes. Reported so the front end can say which
    # audio a run would actually use.
    tier = directory.with_name(directory.name + standardised_suffix)
    standardised = (tier / "words.json").is_file()

    return BankInfo(
        name=name,
        directory=str(directory),
        built=True,
        units=units,
        standardised=standardised,
        problem=problem,
    )


def catalog(banks: dict[str, str], repo_root: Path,
            standardised_suffix: str) -> list[BankInfo]:
    """Every configured bank, in the order the configuration names them.

    Order is preserved rather than sorted: the configuration lists the default
    first, and a picker that reordered it would put an unexpected bank at the
    top on somebody else's machine.
    """
    return [
        inspect(name, repo_root / directory, standardised_suffix)
        for name, directory in banks.items()
    ]
