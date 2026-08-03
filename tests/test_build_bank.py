"""Filename parsing and syllable boundaries for the word bank.

The rename workflow is the primary way clips enter the bank, so how a filename
parses is load-bearing: a name that fails to parse is silently ignored, which
looks identical to "I decided to skip that one".
"""

import numpy as np
import pytest

from luokkaretki import config
from luokkaretki.build_bank import (
    parse_name, parse_phrase, scan_folder, syllable_boundaries,
)


class TestPhraseNames:
    """Multi-word clips are the most valuable thing in the bank.

    A clip holding two words also holds the sung transition between them, which
    beats cutting them apart and splicing them back together. So the parser has
    to read a whole sequence out of a name -- and, just as importantly, refuse a
    name that ends mid-word.
    """

    @pytest.mark.parametrize("stem,words,variant", [
        ("persepillu", ["perse", "pillu"], ""),
        ("persepilluperse", ["perse", "pillu", "perse"], ""),
        ("perse-pillu_2", ["perse", "pillu"], "2"),
        ("paskapersepornolehti", ["paska", "perse", "pornolehti"], ""),
        ("pillupaska1", ["pillu", "paska"], "1"),
        ("paska", ["paska"], ""),
        ("PASKA-PERSE", ["paska", "perse"], ""),
    ])
    def test_reads_the_whole_sequence(self, stem, words, variant):
        assert parse_phrase(stem) == (words, variant)

    @pytest.mark.parametrize("stem", [
        "paskapersepor",     # ends on a chopped 'pornolehti'
        "pillupaskapor",
        "nolehti",           # the other half of one
        "per",
        "persee",            # too long to be one word; ambiguous
    ])
    def test_rejects_names_ending_mid_word(self, stem):
        assert parse_phrase(stem) is None, (
            f"{stem!r} was accepted -- a clip that cuts off mid-syllable would "
            "enter the bank with its fragment treated as a variant label"
        )

    def test_longest_word_wins(self):
        """'pornolehti' must not be read as some shorter word plus junk."""
        assert parse_phrase("pornolehti") == (["pornolehti"], "")

    def test_separator_admits_a_word_like_variant(self):
        """'low' is a label after a separator, but a fragment without one."""
        assert parse_phrase("paviaani_low") == (["paviaani"], "low")
        assert parse_phrase("paviaanilow") is None

SR = config.SAMPLE_RATE


@pytest.mark.parametrize("stem,expected", [
    ("paska", ("paska", "")),
    ("paska1", ("paska", "1")),
    ("paska2", ("paska", "2")),
    ("paska_1", ("paska", "1")),
    ("paska_low", ("paska", "low")),
    ("paska-high", ("paska", "high")),
    ("paska 3", ("paska", "3")),
    ("PASKA1", ("paska", "1")),
    ("Paviaani_Low", ("paviaani", "low")),
    ("pornolehti3", ("pornolehti", "3")),
    ("perse", ("perse", "")),
    ("pillu_take2", ("pillu", "take2")),
])
def test_parse_name_accepts_every_naming_style(stem, expected):
    assert parse_name(stem) == expected


@pytest.mark.parametrize("stem", [
    "c07__3syl__C4__5.06-5.75",   # still carrying its candidate name
    "vittu1",
    "random",
    "",
])
def test_parse_name_rejects_non_bank_names(stem):
    assert parse_name(stem) is None


def test_scan_folder_splits_named_from_unnamed(tmp_path):
    import soundfile as sf

    for name in ("paska1.wav", "perse_low.wav", "persepillu.wav",
                 "c03__2syl__F3__1.0-1.4.wav"):
        sf.write(str(tmp_path / name), np.zeros(1000, dtype=np.float32), SR)

    named, ignored = scan_folder(tmp_path)
    assert sorted(n.stem for n in named) == ["paska", "perse", "perse-pillu"]
    assert [p.name for p in ignored] == ["c03__2syl__F3__1.0-1.4.wav"]

    phrase = next(n for n in named if n.stem == "perse-pillu")
    assert phrase.words == ["perse", "pillu"]
    assert phrase.syllables == 4


def _syllabic(n_bumps: int, dur: float = 0.8) -> np.ndarray:
    """A clip whose envelope has n_bumps loudness peaks."""
    t = np.arange(int(SR * dur)) / SR
    carrier = np.sin(2 * np.pi * 200 * t)
    env = np.abs(np.sin(np.pi * n_bumps * t / dur)) ** 2 + 0.02
    y = (carrier * env).astype(np.float32)
    return np.stack([y, y])


class TestSyllableBoundaryCount:
    """The count must always match the word, whatever the envelope suggests.

    A word is known to have exactly 2 or 4 syllables. An envelope bump from a
    rolled consonant produces extra nuclei, and every spurious boundary drags a
    syllable onto the wrong note when the word is laid over the melody.
    """

    def test_two_syllable_word_gets_exactly_one_boundary(self):
        # Deliberately more envelope bumps than the word has syllables.
        bounds = syllable_boundaries(_syllabic(5), SR, n_syllables=2)
        assert len(bounds) == 1

    def test_four_syllable_word_gets_exactly_three_boundaries(self):
        bounds = syllable_boundaries(_syllabic(7), SR, n_syllables=4)
        assert len(bounds) == 3

    def test_too_few_nuclei_still_gives_the_right_count(self):
        bounds = syllable_boundaries(_syllabic(1), SR, n_syllables=4)
        assert len(bounds) == 3

    def test_boundaries_are_sorted_and_inside_the_clip(self):
        dur = 0.8
        bounds = syllable_boundaries(_syllabic(6, dur), SR, n_syllables=4)
        assert bounds == sorted(bounds)
        assert all(0 < b < dur for b in bounds), bounds

    def test_single_syllable_has_no_boundaries(self):
        assert syllable_boundaries(_syllabic(3), SR, n_syllables=1) == []
