"""The vocabulary must hold together, and nothing else checks that it does.

Every invariant here fails silently when broken. A spelling naming a word that
no longer exists simply stops composing. A shout letter at the start of a real
word quietly eats it during parsing. The bank still builds, the run still
finishes, and the output is wrong.

The shipped vocabulary satisfies all of them today, but it did so by luck until
these existed.
"""

import pytest

from song_generator import config


def test_shipped_vocabulary_is_consistent():
    problems = config.validate_vocabulary()
    assert not problems, "shipped vocabulary is inconsistent:\n  " + "\n  ".join(problems)


class TestValidatorCatchesEachFailure:
    """Each case is a mistake that is easy to make in a local override."""

    def test_spelling_a_word_that_does_not_exist(self, monkeypatch):
        monkeypatch.setattr(config, "WORD_SPELLING", {"ghost": ("gh", "ost")})
        problems = config.validate_vocabulary()
        assert any("not in WORD_SYLLABLES" in p for p in problems)

    def test_spelling_with_the_wrong_number_of_parts(self, monkeypatch):
        monkeypatch.setattr(config, "WORD_SYLLABLES", {"bravo": 2})
        monkeypatch.setattr(config, "WORD_SPELLING", {"bravo": ("b", "ra", "vo")})
        problems = config.validate_vocabulary()
        assert any("2 syllables in WORD_SYLLABLES but 3" in p for p in problems)

    def test_shout_word_missing_from_the_table(self, monkeypatch):
        monkeypatch.setattr(config, "SHOUT_WORDS", ("nosuchword",))
        assert any("SHOUT_WORDS" in p for p in config.validate_vocabulary())

    def test_climax_word_missing_from_the_table(self, monkeypatch):
        monkeypatch.setattr(config, "CLIMAX_WORDS", ("nosuchword",))
        assert any("CLIMAX_WORDS" in p for p in config.validate_vocabulary())

    def test_one_word_being_a_prefix_of_another(self, monkeypatch):
        monkeypatch.setattr(config, "WORD_SYLLABLES", {"car": 1, "carpet": 2})
        monkeypatch.setattr(config, "WORD_SPELLING", {})
        problems = config.validate_vocabulary()
        assert any("is a prefix of" in p for p in problems), (
            "the parser takes the longest match, so 'car' could never be named alone"
        )

    def test_a_word_starting_with_a_shout_letter(self, monkeypatch):
        """The subtlest one: a shout run swallows the start of a real word."""
        monkeypatch.setattr(config, "WORD_SYLLABLES", {"apple": 2, "aah": 1})
        monkeypatch.setattr(config, "WORD_SPELLING", {})
        monkeypatch.setattr(config, "SHOUT_WORDS", ("aah",))
        monkeypatch.setattr(config, "SHOUT_CHARS", "ah")
        problems = config.validate_vocabulary()
        assert any("SHOUT_CHARS" in p for p in problems)

    def test_a_syllable_starting_with_a_shout_letter(self, monkeypatch):
        monkeypatch.setattr(config, "WORD_SYLLABLES", {"below": 2})
        monkeypatch.setattr(config, "WORD_SPELLING", {"below": ("be", "ah")})
        monkeypatch.setattr(config, "SHOUT_CHARS", "ah")
        assert any("starts with a shout letter" in p
                   for p in config.validate_vocabulary())


def test_a_partial_override_is_reported(monkeypatch):
    """Redefining one table and forgetting the one that depends on it.

    The likeliest real mistake when writing vocabulary_local.py: replace
    WORD_SYLLABLES with your own words and leave WORD_SPELLING as it was. The
    bank still builds. It just silently cannot spell anything.
    """
    monkeypatch.setattr(config, "WORD_SYLLABLES", {"foo": 2, "ooh": 1})
    monkeypatch.setattr(config, "SHOUT_WORDS", ("ooh",))
    monkeypatch.setattr(config, "CLIMAX_WORDS", ("foo",))
    # WORD_SPELLING deliberately left holding the shipped example's words.

    problems = config.validate_vocabulary()
    assert any("not in WORD_SYLLABLES" in p for p in problems), (
        f"a partial override went unreported: {problems}"
    )
