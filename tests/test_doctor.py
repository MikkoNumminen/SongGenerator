"""The folding prediction has to be worth acting on.

It is the fast way to ask whether a song suits a bank before spending a
render on it. For a long time it answered by measuring each note against the
NEAREST take in the bank, which read 0% folding on songs that then folded half
their syllables. One clip at the top of the range made the whole top of the
range look reachable, and selection cannot reach it: a unit also has to fit the
slot's length and say the word being sung.

These tests pin the property that matters. A melody sitting an octave above
where the bank actually lives must be reported as folding, even when a single
outlier take sits right beside it.
"""

from __future__ import annotations

import numpy as np
import pytest

from song_generator import config, doctor
from song_generator.mapping import Unit


def _unit(name: str, midi: float, words: list[str], syllables: int = 2) -> Unit:
    return Unit(
        name=name,
        words=words,
        syllables=syllables,
        duration_s=0.5,
        midi=midi,
        audio=np.zeros((2, int(0.5 * config.SAMPLE_RATE)), dtype=np.float32),
        bounds_s=[],
        syllable_midi=[midi] * syllables,
    )


def _bank_with_one_high_outlier() -> list[Unit]:
    """Twelve takes around F3, and exactly one an octave and a half up.

    This is the shape of the real bank: a register one pitch wide, plus a
    couple of stray takes that read as range and are not.
    """
    word = next(w for w, n in config.WORD_SYLLABLES.items() if n == 2)
    units = [_unit(f"{word}_{i}.wav", 53.0 + (i % 3), [word]) for i in range(12)]
    units.append(_unit(f"{word}_high.wav", 71.0, [word]))
    return units


def _predicted(units, midis, capsys) -> tuple[float, float]:
    notes = [{"midi": float(m)} for m in midis]
    doctor._report_folding(units, notes)
    line = [l for l in capsys.readouterr().out.splitlines() if "predicted shift" in l]
    assert line, "the prediction must be printed"
    text = line[0]
    median = float(text.split("median ")[1].split(" semitones")[0])
    percent = float(text.split(", ")[1].split("%")[0])
    return median, percent


def test_a_lone_high_take_does_not_make_a_high_song_look_easy(capsys):
    """The regression this was written for.

    Every note sits at MIDI 71, where exactly one of thirteen takes lives.
    Measured against the nearest take the answer is 0% folded, which is what
    it used to say. Measured against the register the bank actually occupies
    it is the octave and a half it really is.
    """
    units = _bank_with_one_high_outlier()
    median, percent = _predicted(units, [71.0] * 20, capsys)

    assert median > config.SHIFT_CAP_SEMITONES, (
        "a melody an octave and a half above the bank's own register cannot "
        "report a shift inside the cap just because one take sits there"
    )
    assert percent == 100.0, "every note is beyond the cap from the bulk of this bank"


def test_a_song_sitting_on_the_bank_folds_nothing(capsys):
    units = _bank_with_one_high_outlier()
    median, percent = _predicted(units, [53.0, 54.0, 53.5, 55.0], capsys)

    assert median < 3.0
    assert percent == 0.0


def test_shouts_and_payoffs_are_left_out_of_the_register(capsys):
    """They do not place like ordinary units, so they must not define where
    the bank sits. A bare shout is never shifted at all, and a climax unit is
    refused outside a peak, so counting either would move the centre toward
    pitches an ordinary slot can never draw from."""
    word = next(w for w, n in config.WORD_SYLLABLES.items() if n == 2)
    ordinary = [_unit(f"{word}_{i}.wav", 53.0, [word]) for i in range(4)]
    shout = config.SHOUT_WORDS[0] if config.SHOUT_WORDS else None
    if shout is None:
        pytest.skip("this vocabulary has no shout to exclude")
    loud = [_unit(f"{shout}_{i}.wav", 75.0, [shout], syllables=1) for i in range(20)]

    median, _ = _predicted(ordinary + loud, [53.0] * 8, capsys)
    assert median < 1.0, (
        "twenty shouts at 75 must not drag the bank's register away from the "
        "four ordinary takes that actually place"
    )
