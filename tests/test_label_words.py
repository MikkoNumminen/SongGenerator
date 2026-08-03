"""Fuzzy matching of recogniser output onto the five-word bank.

Whisper is trained on speech, not singing, and Finnish is not one of its
stronger languages, so a sung bank word comes back spelled loosely. Matching is
therefore fuzzy against a closed vocabulary. These pin both directions: real
variants must be accepted, and unrelated words must NOT be dragged onto a bank
word just because it is the nearest of only five options.
"""

import pytest

from luokkaretki_generator.label_words import (
    MATCH_THRESHOLD, RENAME_CONFIDENT, LabelRow, best_target, candidate_span,
    merge, normalise, overlap, Match,
)


def test_candidate_span_reads_times_off_a_generated_name():
    assert candidate_span("c07__4syl__F#3__9.43-9.98") == (9.43, 9.98)
    assert candidate_span("c01__2syl__F3__0.09-0.48") == (0.09, 0.48)


@pytest.mark.parametrize("stem", ["paska1", "maybe-pillu__c07", "random"])
def test_candidate_span_absent_once_renamed(stem):
    assert candidate_span(stem) is None


def test_weak_matches_cannot_reach_the_bank_unaided():
    """A 'maybe-' name must not parse as a bank word.

    Whisper heard one 4-syllable word as the same wrong token eleven times at
    0.67. If that prefix parsed, a single shaky guess would populate the bank
    with clips nobody had listened to.
    """
    from luokkaretki_generator.build_bank import parse_name

    assert MATCH_THRESHOLD < RENAME_CONFIDENT
    assert parse_name("maybe-pornolehti__c04__2syl__F#3__2.75-3.11") is None


@pytest.mark.parametrize("heard,expected", [
    ("Paska!", "paska"),
    ("paska", "paska"),
    ("pasca", "paska"),        # recogniser spelling drift
    ("perse", "perse"),
    ("pillua", "pillu"),       # Finnish inflection
    ("Paviaani,", "paviaani"),
    ("pornolehti", "pornolehti"),
    ("porno", "pornolehti"),   # clean prefix of a long word
])
def test_accepts_real_variants(heard, expected):
    target, score = best_target(normalise(heard))
    assert target == expected
    assert score >= MATCH_THRESHOLD, f"{heard!r} scored only {score:.2f}"


@pytest.mark.parametrize("heard", ["ja", "on", "vittu", "kissa", "the", ""])
def test_rejects_unrelated_words(heard):
    _, score = best_target(normalise(heard))
    assert score < MATCH_THRESHOLD, (
        f"{heard!r} scored {score:.2f} and would be written into labels.tsv"
    )


def test_normalise_keeps_finnish_vowels():
    assert normalise("PÄÄ-Ö!") == "pääö"
    assert normalise("  paska.  ") == "paska"


def test_overlap():
    assert overlap(0, 1, 0.5, 2) == pytest.approx(0.5)
    assert overlap(0, 1, 2, 3) == 0.0


def _row(word, start, end):
    return LabelRow(word, "", start, end, "", "", "c01.wav")


def test_merge_fills_the_overlapping_region():
    rows = [_row("?", 1.0, 1.6)]
    filled, added = merge(rows, [Match("paska", 1.1, 1.5, 0.95, "paska")])
    assert (filled, added) == (1, 0)
    assert rows[0].word == "paska"


def test_merge_keeps_existing_labels():
    """A hand-typed label outranks a guess from a speech model."""
    rows = [_row("perse", 1.0, 1.6)]
    filled, added = merge(rows, [Match("paska", 1.1, 1.5, 0.95, "paska")])
    assert (filled, added) == (0, 0)
    assert rows[0].word == "perse"


def test_merge_adds_a_row_when_nothing_overlaps():
    rows = [_row("?", 1.0, 1.6)]
    filled, added = merge(rows, [Match("pillu", 8.0, 8.4, 0.9, "pillu")])
    assert (filled, added) == (0, 1)
    assert len(rows) == 2
    assert [r.start_s for r in rows] == sorted(r.start_s for r in rows)
