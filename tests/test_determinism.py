"""What paskapillu sings, pinned exactly.

Every bank shares `arrange.py` and `mapping.py`. A new bank that wants
different behaviour, words replayed in the order they were spoken rather than
chosen, is a change to code the existing bank runs through, and the failure
mode is not a crash. It is one unit moving, in a song nobody re-listens to for
a fortnight.

`docs/AI-FIRST.md` scores determinism at 9 for exactly this gap: the seeds are
there and documented, and nothing asserted that the same inputs produce the
same arrangement. These do.

The bank and slots are fixtures rather than the real bank, because the real one
is gitignored and a test that needs it cannot run on a fresh clone. The
vocabulary is the shipped example, pinned by conftest.

If one of these fails, the question is not "is the new expectation right". It
is "did I mean to change what the existing bank sings".
"""

from __future__ import annotations

import pytest

from song_generator import arrange, config
from song_generator.mapping import Slot


def _bank(unit):
    """Built from the clip factory in conftest, where it is pinned in place.

    The exact expectations below depend on the factory's internals, so it
    cannot be a private helper of another test module that someone refactors
    without knowing these pins exist.
    """
    return [unit(["tango", "bravo"]), unit(["delta"]),
            unit(["delta", "tango", "kilometer"]), unit(["aah", "calculator"])]


def _slots():
    out, at = [], 0.0
    for i in range(48):
        out.append(Slot(at, at + 0.25, 53.0 + (i % 5), phrase=i // 8))
        at += 0.25
    return out


def _placements(unit, level: str, seed: int) -> list[str]:
    arr = arrange.build(_slots(), _bank(unit), level, seed,
                        song="fixture", bank="fixture")[1]
    return [l.rstrip() for l in arrange.render_text(arr).splitlines()
            if l.strip() and not l.lstrip().startswith("#")]


CONSERVATIVE_1987 = [
    "phrase 0",
    "   0:00.00  x2  =0.50  delta                             [delta_1.wav]",
    "   0:00.50  x4  =1.00  tango bravo                       [tango-bravo_1.wav]",
    "   0:01.50  x2  =0.50  tango                             [delta-tango-kilometer_1.wav#2:tango]",
    "   0:02.00  x8  =2.00  delta tango kilometer             [delta-tango-kilometer_1.wav]",
    "   0:04.00  x4  =1.00  tango delta                       [invented:tango+delta:1]",
    "   0:05.00  x3  =0.75  bravo                             [tango-bravo_1.wav#2:bravo]",
    "phrase 1",
    "   0:05.75  x3  =0.75  tango                             [tango-bravo_1.wav#1:tango]",
    "phrase 3",
    "   0:07.25  x4  =1.00  delta tango                       [invented:delta+tango:6]",
    "phrase 5",
    "   0:09.25  x5  =1.25  bravo delta                       [invented:bravo+delta:2]",
    "phrase 6",
    "   0:10.50  x6  =1.50  aah calculator                    [aah-calculator_1.wav]",
]

WILD_1987 = [
    "phrase 0",
    "   0:00.00  x4  =1.00  bravo tango                       [invented:bravo+tango:6]",
    "   0:01.00  x2  =0.50  tango                             [delta-tango-kilometer_1.wav#2:tango]",
    "   0:01.50  x2  =0.50  delta                             [delta_1.wav]",
    "   0:02.00  x4  =1.00  tango bravo                       [tango-bravo_1.wav]",
    "   0:03.00  x8  =2.00  bravo tango kilometer             [invented:bravo+tango+kilometer:7]",
    "   0:05.00  x3  =0.75  bravo                             [tango-bravo_1.wav#2:bravo]",
    "phrase 2",
    "   0:06.50  x3  =0.75  delta                             [delta-tango-kilometer_1.wav#1:delta]",
    "phrase 4",
    "   0:08.25  x4  =1.00  tango delta                       [invented:tango+delta:10]",
    "phrase 5",
    "   0:09.25  x5  =1.25  aah calculator                    [aah-calculator_1.wav]",
    "phrase 6",
    "   0:10.50  x6  =1.50  aah calculator                    [aah-calculator_1.wav]",
]


@pytest.mark.parametrize("level,expected", [
    ("conservative", CONSERVATIVE_1987),
    ("wild", WILD_1987),
])
def test_the_arrangement_for_a_given_seed_does_not_move(level, expected, unit):
    assert _placements(unit, level, 1987) == expected


def test_the_same_seed_twice_is_the_same_arrangement(unit):
    """The guarantee the seed is printed for. Nothing asserted it before."""
    assert _placements(unit, "wild", 4242) == _placements(unit, "wild", 4242)


def test_a_different_seed_is_a_different_arrangement(unit):
    """Otherwise the test above passes for the wrong reason, on a planner that
    ignores its seed entirely."""
    # The second seed sits outside the redraw window on purpose. On a coverage
    # miss, arrange.build replans with seed + attempt, so two seeds closer
    # than PLAY_COVERAGE_TRIES can legitimately walk onto the same draw: seed
    # A redrawing once plans exactly what seed A + 1 plans on its first try.
    # Adjacent seeds would then fail here on correct behaviour.
    other = 4242 + config.PLAY_COVERAGE_TRIES + 1
    assert _placements(unit, "wild", 4242) != _placements(unit, "wild", other)
