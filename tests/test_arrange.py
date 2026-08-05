"""Cutting words out of phrases, and the arrangement that records the result.

Whether an arrangement is funny is a listening question and there is no test
for it. What is testable is that a slice lands on the word it claims, that the
same seed gives the same arrangement, that every required word is there, and
that a description read back produces the identical plan. The last one is the
one that has to hold: the log is the only record of an arrangement, so a
round trip that quietly drifts loses the take rather than reporting it.
"""

import random

import numpy as np
import pytest

from song_generator import config
from song_generator.arrange import (
    Arrangement, ArrangementError, Line, build, describe, enrich, index_by_word,
    join_words, level_params, parse_text, realise, render_text, required_words,
    slice_words, unit_for, word_spans,
)
from song_generator.mapping import Slot, Unit, plan_words

SR = config.SAMPLE_RATE


def _tone(seconds: float, freq: float = 220.0, amp: float = 0.4) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    mono = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([mono, mono])


def _unit(words, per_word=0.4, name=None) -> Unit:
    """A clip holding the given words, with honest boundaries."""
    syllables = [config.WORD_SYLLABLES[w] for w in words]
    total = sum(syllables) * (per_word / 2)
    audio = _tone(total)
    bounds, at = [], 0.0
    for n in sum(([w] * config.WORD_SYLLABLES[w] for w in words), []):
        at += per_word / 2
        bounds.append(round(at, 4))
    return Unit(
        name=name or ("-".join(words) + "_1.wav"),
        words=list(words),
        syllables=sum(syllables),
        duration_s=audio.shape[1] / SR,
        midi=53.0,
        audio=audio,
        bounds_s=bounds[:-1],
        syllable_midi=[53.0] * sum(syllables),
    )


@pytest.fixture
def bank():
    """Two-word and three-word clips, as the real bank is shaped."""
    return [
        _unit(["tango", "bravo"]),
        _unit(["delta"]),
        _unit(["delta", "tango", "kilometer"]),
        _unit(["aah", "calculator"]),
    ]


@pytest.fixture
def slots():
    out, at = [], 0.0
    for i in range(48):
        out.append(Slot(at, at + 0.25, 53.0 + (i % 5), phrase=i // 8))
        at += 0.25
    return out


# ---------------------------------------------------------------------------
# Slicing
# ---------------------------------------------------------------------------

def test_a_two_word_clip_knows_where_its_words_are(bank):
    spans = word_spans(bank[0])
    assert [w for w, _, _ in spans] == ["tango", "bravo"]
    assert spans[0][1] == 0.0
    assert spans[0][2] == pytest.approx(spans[1][1])


def test_a_single_word_clip_is_not_cut(bank):
    assert word_spans(bank[1]) is None


def test_slicing_yields_every_word_on_its_own(bank):
    """Every word in an ordinary clip becomes available by itself."""
    by = index_by_word(slice_words(bank))
    assert set(by) == {"tango", "bravo", "delta", "kilometer"}


def test_the_payoff_pairing_is_never_cut_apart(bank):
    """Slicing it is what lost it: the halves outvoted the whole recording.

    A dozen ways to say the payoff alone beat the one clip that says it the way
    the singer did, so the pairing stopped appearing at all. It stays whole.
    """
    pairing = next(u for u in bank if u.words == ["aah", "calculator"])
    assert pairing.is_shout_pairing
    assert not any(s.name.startswith(pairing.name) for s in slice_words(bank))


def test_the_pairing_survives_enrichment(bank):
    for level in ("conservative", "wild"):
        pool = enrich(bank, level, random.Random(2))
        assert any(u.is_shout_pairing for u in pool)


def test_a_slice_is_shorter_than_the_clip_it_came_from(bank):
    for sliced in slice_words(bank):
        parent = next(u for u in bank if u.name == sliced.name.split("#")[0])
        assert sliced.duration_s < parent.duration_s


def test_a_slice_says_exactly_one_word(bank):
    for sliced in slice_words(bank):
        assert len(sliced.words) == 1
        assert sliced.syllables == config.WORD_SYLLABLES[sliced.words[0]]


def test_a_slice_records_where_it_came_from(bank):
    names = {u.name for u in slice_words(bank)}
    assert any(n.startswith("tango-bravo_1.wav#") and n.endswith(":bravo") for n in names)


def test_slicing_never_touches_the_source_audio(bank):
    before = [u.audio.copy() for u in bank]
    slice_words(bank)
    assert all(np.array_equal(a, u.audio) for a, u in zip(before, bank))


# ---------------------------------------------------------------------------
# Joining
# ---------------------------------------------------------------------------

def test_joining_says_the_words_in_the_order_given(bank):
    by = index_by_word(slice_words(bank))
    joined = join_words([by["delta"][0], by["bravo"][0]])
    assert joined.words == ["delta", "bravo"]


def test_the_order_that_was_never_recorded_can_be_built(bank):
    """delta bravo exists nowhere in the bank; it is the point of the module."""
    assert not any(u.label == "delta+bravo" for u in bank)
    by = index_by_word(slice_words(bank))
    assert join_words([by["delta"][0], by["bravo"][0]]).label == "delta+bravo"


def test_a_join_carries_a_boundary_between_each_syllable(bank):
    by = index_by_word(slice_words(bank))
    joined = join_words([by["delta"][0], by["bravo"][0]])
    assert len(joined.bounds_s) == joined.syllables - 1
    assert joined.bounds_s == sorted(joined.bounds_s)
    assert all(0.0 < b < joined.duration_s for b in joined.bounds_s)


def test_joining_one_thing_returns_it_unchanged(bank):
    by = index_by_word(slice_words(bank))
    only = by["delta"][0]
    assert join_words([only]) is only


def test_joining_nothing_is_nothing():
    assert join_words([]) is None


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------

def test_off_adds_nothing(bank):
    assert len(enrich(bank, "off", random.Random(1))) == len(bank)


def test_a_level_only_ever_adds(bank):
    for level in ("conservative", "wild"):
        pool = enrich(bank, level, random.Random(1))
        assert len(pool) > len(bank)
        assert all(u in pool for u in bank)


def test_wild_invents_more_than_conservative(bank):
    counts = {}
    for level in ("conservative", "wild"):
        pool = enrich(bank, level, random.Random(3))
        counts[level] = sum(1 for u in pool if u.name.startswith("invented:"))
    assert counts["wild"] > counts["conservative"]


def test_an_unknown_level_is_refused_by_name():
    with pytest.raises(ValueError, match="unknown playfulness level"):
        level_params("feral")


def test_enrichment_is_reproducible_from_its_seed(bank):
    a = enrich(bank, "wild", random.Random(11))
    b = enrich(bank, "wild", random.Random(11))
    assert [u.label for u in a] == [u.label for u in b]


# ---------------------------------------------------------------------------
# Seed and coverage
# ---------------------------------------------------------------------------

def test_the_same_seed_gives_the_same_arrangement(bank, slots):
    _, first, _ = build(slots, bank, "wild", 4242)
    _, second, _ = build(slots, bank, "wild", 4242)
    assert [(l.words, l.n_slots, l.take) for l in first.lines] == \
           [(l.words, l.n_slots, l.take) for l in second.lines]


def test_different_seeds_give_different_arrangements(bank, slots):
    _, a, _ = build(slots, bank, "wild", 1)
    _, b, _ = build(slots, bank, "wild", 99)
    assert [l.words for l in a.lines] != [l.words for l in b.lines]


def test_every_required_word_is_present(bank, slots):
    _, arrangement, _ = build(slots, bank, "conservative", 7)
    assert arrangement.missing() == []
    assert set(required_words()) <= arrangement.words_used()


def test_wild_is_not_emptier_than_conservative(bank, slots):
    """Unpredictable and sparse are different things, and wild was both."""
    filled = {}
    for level in ("conservative", "wild"):
        runs = [build(slots, bank, level, 900 + i)[0].slots_used for i in range(6)]
        filled[level] = sum(runs) / len(runs)
    assert filled["wild"] >= filled["conservative"] * 0.9


def test_wild_still_says_more_different_things(bank, slots):
    variety = {}
    for level in ("conservative", "wild"):
        seen = set()
        for i in range(6):
            plan, _, _ = build(slots, bank, level, 700 + i)
            seen.update(p.unit.label for p in plan.placements)
        variety[level] = len(seen)
    assert variety["wild"] > variety["conservative"]


def test_coverage_is_reported_when_it_cannot_be_met(slots):
    """A bank that cannot say a required word must say so, not pretend."""
    thin = [_unit(["delta"])]
    _, arrangement, _ = build(slots, thin, "conservative", 5)
    assert "kilometer" in arrangement.missing()


# ---------------------------------------------------------------------------
# The log, both ways
# ---------------------------------------------------------------------------

def test_a_description_reads_back_identically(bank, slots):
    _, arrangement, _ = build(slots, bank, "wild", 20)
    back = parse_text(render_text(arrangement))
    assert [(l.words, l.n_slots, l.take) for l in back.lines] == \
           [(l.words, l.n_slots, l.take) for l in arrangement.lines]
    assert back.seed == arrangement.seed
    assert back.level == arrangement.level


def test_replaying_a_description_rebuilds_the_same_plan(bank, slots):
    plan, arrangement, _ = build(slots, bank, "wild", 31)
    replayed = realise(parse_text(render_text(arrangement)), slots, bank)
    assert [(p.unit.words, p.n_slots, round(p.onset_s, 3)) for p in plan.placements] == \
           [(p.unit.words, p.n_slots, round(p.onset_s, 3)) for p in replayed.placements]


def test_a_hand_written_arrangement_is_honoured(bank, slots):
    """The bridge to the guided mode: words nobody generated, assembled anyway."""
    text = (
        "# song    test\n"
        "# seed    1\n"
        "phrase 0\n"
        "  0:00.00  x4  delta bravo\n"
        "  0:01.00  x4  bravo delta\n"
    )
    plan = realise(parse_text(text), slots, bank)
    assert [p.unit.words for p in plan.placements] == [
        ["delta", "bravo"], ["bravo", "delta"]]


def test_deleting_the_take_still_works(bank, slots):
    _, arrangement, _ = build(slots, bank, "conservative", 8)
    stripped = Arrangement(
        arrangement.song, arrangement.bank, arrangement.level, arrangement.seed,
        [Line(l.phrase, l.onset_s, l.n_slots, l.words, None) for l in arrangement.lines])
    plan = realise(stripped, slots, bank)
    assert [p.unit.words for p in plan.placements] == \
           [l.words for l in arrangement.lines]


def test_an_unknown_word_is_refused_rather_than_dropped():
    with pytest.raises(ArrangementError, match="not words in this bank"):
        parse_text("phrase 0\n  0:00.00  x2  banana\n")


def test_a_malformed_line_is_refused_by_number():
    with pytest.raises(ArrangementError, match="line 2"):
        parse_text("phrase 0\n  nonsense here\n")


def test_an_empty_arrangement_is_refused():
    with pytest.raises(ArrangementError, match="no placements"):
        parse_text("# song  nothing\n")


def test_a_word_the_bank_cannot_say_is_refused(slots):
    thin = [_unit(["delta"])]
    text = "phrase 0\n  0:00.00  x4  delta kilometer\n"
    with pytest.raises(ArrangementError, match="cannot say"):
        realise(parse_text(text), slots, thin)


def test_the_header_names_the_vocabulary_for_whoever_edits_it(bank, slots):
    _, arrangement, _ = build(slots, bank, "conservative", 2)
    text = render_text(arrangement)
    for word in config.WORD_SYLLABLES:
        assert word in text


# ---------------------------------------------------------------------------
# The ladder underneath
# ---------------------------------------------------------------------------

def test_playfulness_leaves_the_planner_alone_when_off(bank, slots):
    """play=None must reproduce what the planner did before any of this."""
    a = plan_words(slots, bank, seed=5)
    b = plan_words(slots, bank, seed=5, play=None)
    assert [(p.unit.name, p.onset_s) for p in a.placements] == \
           [(p.unit.name, p.onset_s) for p in b.placements]


def test_a_fixed_arrangement_gives_a_fixed_ladder(bank, slots):
    """One arrangement, seven rungs, and they do not move between runs."""
    from song_generator.mapping import decide_shifts, mimicry

    plan, arrangement, _ = build(slots, bank, "wild", 64)
    first = []
    for target in config.MIMICRY_VARIANTS:
        decide_shifts(plan, target_mimicry=target)
        first.append(round(mimicry(plan), 4))

    again = realise(parse_text(render_text(arrangement)), slots, bank)
    second = []
    for target in config.MIMICRY_VARIANTS:
        decide_shifts(again, target_mimicry=target)
        second.append(round(mimicry(again), 4))

    assert first == second
    assert first == sorted(first)
