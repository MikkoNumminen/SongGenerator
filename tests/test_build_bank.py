"""Filename parsing and syllable boundaries for the word bank.

The rename workflow is the primary way clips enter the bank, so how a filename
parses is load-bearing: a name that fails to parse is silently ignored, which
looks identical to "I decided to skip that one".
"""

import numpy as np
import pytest

from song_generator import config
from song_generator.build_bank import (
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
        ("tangodelta", ["tango", "delta"], ""),
        ("tangodeltatango", ["tango", "delta", "tango"], ""),
        ("tango-delta_2", ["tango", "delta"], "2"),
        ("bravotangokilometer", ["bravo", "tango", "kilometer"], ""),
        ("deltabravo1", ["delta", "bravo"], "1"),
        ("bravo", ["bravo"], ""),
        ("BRAVO-TANGO", ["bravo", "tango"], ""),
    ])
    def test_reads_the_whole_sequence(self, stem, words, variant):
        assert parse_phrase(stem) == (words, variant)

    @pytest.mark.parametrize("stem,words", [
        ("tan", ["tan"]),
        ("lometer", ["lo", "me", "ter"]),
        ("bravotangoki", ["bravo", "tango", "ki"]),
        ("deltabravoki", ["delta", "bravo", "ki"]),
    ])
    def test_syllable_names_parse_as_syllables(self, stem, words):
        """These read as fragments only while syllables are not first-class.

        Once the bank holds syllables, 'lometer' is precisely lo + me + ter,
        and a clip named that way is three usable slots rather than a chopped
        word. Naming is the user's act, so a name that spells out syllables is
        taken at its word.
        """
        assert parse_phrase(stem) == (words, "")

    @pytest.mark.parametrize("stem,words", [
        ("aaahcalculator", ["aah", "calculator"]),
        ("aaahhcalculator", ["aah", "calculator"]),
        ("ahhcalculator", ["aah", "calculator"]),
        ("tangoaah", ["tango", "aah"]),
    ])
    def test_a_shout_is_accepted_however_it_is_spelled(self, stem, words):
        """One gesture, spelled by ear: aah, aaah, ahh, aaahh all mean it.

        Someone naming clips by ear writes what they heard, and a held shout
        has no canonical spelling. Insisting on one would mean silently
        ignoring correctly identified clips.
        """
        assert parse_phrase(stem) == (words, "")

    def test_a_shout_run_does_not_eat_a_variant_label(self):
        """a and h are shout letters, so 'haze' must not be read as a shout."""
        assert parse_phrase("bravo-haze") == (["bravo"], "haze")
        assert parse_phrase("delta_hah") == (["delta"], "hah")

    @pytest.mark.parametrize("stem", ["xyz", "bravoxx"])
    def test_still_rejects_names_that_spell_nothing(self, stem):
        assert parse_phrase(stem) is None, (
            f"{stem!r} was accepted despite ending in something that is neither "
            "a word nor a syllable"
        )

    def test_longest_word_wins(self):
        """'kilometer' must not be read as some shorter word plus junk."""
        assert parse_phrase("kilometer") == (["kilometer"], "")

    def test_separator_admits_a_word_like_variant(self):
        """'quiet' is a label after a separator, but a fragment without one."""
        assert parse_phrase("calculator_quiet") == (["calculator"], "quiet")
        assert parse_phrase("calculatorquiet") is None

SR = config.SAMPLE_RATE


@pytest.mark.parametrize("stem,expected", [
    ("bravo", ("bravo", "")),
    ("bravo1", ("bravo", "1")),
    ("bravo2", ("bravo", "2")),
    ("bravo_1", ("bravo", "1")),
    ("bravo_quiet", ("bravo", "quiet")),
    ("bravo-haze", ("bravo", "haze")),
    ("bravo 3", ("bravo", "3")),
    ("BRAVO1", ("bravo", "1")),
    ("Calculator_Quiet", ("calculator", "quiet")),
    ("kilometer3", ("kilometer", "3")),
    ("tango", ("tango", "")),
    ("delta_soft", ("delta", "soft")),
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

    for name in ("bravo1.wav", "tango_quiet.wav", "tangodelta.wav",
                 "c03__2syl__F3__1.0-1.4.wav"):
        sf.write(str(tmp_path / name), np.zeros(1000, dtype=np.float32), SR)

    named, ignored = scan_folder(tmp_path)
    assert sorted(n.stem for n in named) == ["bravo", "tango", "tango-delta"]
    assert [p.name for p in ignored] == ["c03__2syl__F3__1.0-1.4.wav"]

    phrase = next(n for n in named if n.stem == "tango-delta")
    assert phrase.words == ["tango", "delta"]
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


class TestShoutTails:
    """A stuttered shout written out is content, not a take label.

    The distinction is only decidable from the shape of the name: a single
    unbroken run after a separator is a label ("delta_hah" is a take called
    hah), while shout letters broken up by separators is somebody writing down
    what they heard. Getting it wrong cost a 6.6 second clip six of its eleven
    syllables, which put every syllable in it on the wrong note.
    """

    def test_a_stuttered_tail_is_read_as_shouts(self):
        words, rest = parse_phrase("calculator-aah_ah-a-a-ah")
        assert words[0] == "calculator"
        assert words.count("aah") == 5
        assert rest == ""

    def test_an_unbroken_run_after_a_separator_is_still_a_label(self):
        assert parse_phrase("delta_hah") == (["delta"], "hah")
        assert parse_phrase("bravo-haze") == (["bravo"], "haze")

    def test_a_label_with_a_non_shout_letter_survives_separators(self):
        """Only ALL shout letters counts; one ordinary letter makes it a label."""
        assert parse_phrase("bravo-ha-ze") == (["bravo"], "ha-ze")

    def test_a_leading_run_is_unaffected(self):
        words, rest = parse_phrase("aaah")
        assert words == ["aah"]
        assert rest == ""
