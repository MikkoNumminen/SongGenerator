"""A bank can declare how it behaves, in a bank.json beside its clips.

The existing bank declares nothing and must not move an inch:
tests/test_determinism.py pins its exact placements, and everything here
exists so that suite can stay green while a second bank behaves differently.
What is tested here is the declaration itself. An undeclared bank gets
today's behaviour, a declared sequence replays the recordings in recorded
order, and a bank's overrides reach the planner without leaking into config
for the next song in a batch.
"""

import copy
import json
import types
from pathlib import Path

import numpy as np
import pytest
from factories import make_unit as _unit

from song_generator import arrange, audio_io, banks, cli, config
from song_generator.mapping import (
    Placement, Plan, Slot, build_segments, group_phrases, load_bank,
    mix as mix_buses, plan_sequence, render,
)


def _spoken(n=3):
    """A bank cut with build_bank --raw: one variant per clip, in spoken order."""
    units = []
    for i in range(n):
        u = _unit(["delta"], name=f"raw_{i + 1:04d}.wav")
        u.variant = f"{i + 1:04d}"
        units.append(u)
    return units


def _raw_spoken(n=3):
    """The same bank as its own log records it: every unit's word is "raw",
    which is what build_bank --raw writes and what no vocabulary holds."""
    units = _spoken(n)
    for u in units:
        u.words = ["raw"]
    return units


def _slots(n=48, dur=0.25):
    # A real gap after every eighth slot, so the groups the planner sings to
    # are the eight-slot phrases the fixture intends rather than whatever
    # the phrase-length cap cuts a continuous run into.
    out, at = [], 0.0
    for i in range(n):
        out.append(Slot(at, at + dur, 53.0 + (i % 5), phrase=i // 8))
        at += dur
        if i % 8 == 7:
            at += 0.5
    return out


def _arranged_bank():
    """The determinism fixture's shape: recorded phrases, no variants."""
    return [_unit(["tango", "bravo"]), _unit(["delta"]),
            _unit(["delta", "tango", "kilometer"]), _unit(["aah", "calculator"])]


# ---------------------------------------------------------------------------
# The sequence strategy
# ---------------------------------------------------------------------------

class TestPlanSequence:
    def test_the_first_placements_follow_the_variants(self):
        # Handed in scrambled, to prove the order comes from the variant
        # field rather than from whatever order load_bank happened to use.
        units = _spoken(5)
        plan = plan_sequence(_slots(), list(reversed(units)))
        assert [p.unit.variant for p in plan.placements[:3]] == [
            "0001", "0002", "0003"]

    def test_the_sequence_loops_when_the_units_run_out(self):
        # 48 slots against three 2-syllable units is 24 placements, so the
        # three units must come round eight times, 0001 straight after 0003.
        plan = plan_sequence(_slots(), _spoken(3))
        got = [p.unit.variant for p in plan.placements]
        assert got == ["0001", "0002", "0003"] * 8
        assert got[3] == "0001"

    def test_two_calls_are_identical(self):
        def fingerprint():
            plan = plan_sequence(_slots(), _spoken(5))
            return [(p.unit.name, p.onset_s, p.n_slots, p.play_s, p.phrase)
                    for p in plan.placements]

        assert fingerprint() == fingerprint()

    def test_a_unit_is_never_shortened_to_fit_its_slots(self):
        # 0.1s slots give a 2-syllable, 0.4s clip less span than it needs. A
        # spoken word cut in half stops being the word, so every unit keeps
        # its full duration and takes the slots its own time covers. Asserted
        # over the WHOLE plan: the version of this test that looked only at
        # the first placement stayed green while a backtracking guard starved
        # every phrase after the first down to nothing.
        plan = plan_sequence(_slots(dur=0.1), _spoken(3))
        assert len(plan.placements) == 12
        for p in plan.placements:
            assert p.play_s == pytest.approx(p.unit.duration_s)
            assert p.target_s == pytest.approx(p.unit.duration_s)

    def test_short_slots_do_not_starve_the_song(self):
        """Defect: when a unit did not fit its slots, a backtrack guard keyed
        on plan.placements, which is global, so after the first placement it
        fired at slot 0 of every later phrase and blocked the rest of the
        song: 1 placement over 2 of 48 slots. Every phrase must be sung."""
        plan = plan_sequence(_slots(dur=0.1), _spoken(3))
        assert plan.slots_used == plan.slots_total == 48
        assert plan.slots_dropped == 0
        assert {p.phrase for p in plan.placements} == set(range(6))

    def test_no_word_sounds_on_top_of_the_next(self):
        """The cursor is the one authority on collision, at any slot size and
        any pace: a word that needs more time than its slots give delays the
        next word instead of playing underneath it."""
        for dur in (0.1, 0.25):
            for speed in (0.3, 0.5, 1.0):
                plan = plan_sequence(_slots(dur=dur), _spoken(3),
                                     reading_speed=speed)
                assert plan.placements
                for a, b in zip(plan.placements, plan.placements[1:]):
                    assert b.onset_s >= a.onset_s + a.play_s - 1e-6, \
                        f"overlap at {b.onset_s} (dur={dur}, speed={speed})"

    def test_every_slot_is_accounted_for_at_any_pace(self):
        """A slot the cursor has already passed is sung over, not silent, so
        used and total stay equal however far a word overruns its phrase."""
        for speed in (0.3, 0.5, 1.0):
            plan = plan_sequence(_slots(dur=0.1), _spoken(3),
                                 reading_speed=speed)
            assert plan.slots_used == plan.slots_total == 48
            assert plan.slots_dropped == 0

    def test_the_cursor_never_advances_by_a_time_the_renderer_refuses(self):
        """Defect: a pace outside the engine's range advanced the cursor by
        the unclamped duration_s / speed while build_segments clamped the
        sound to TIME_STRETCH_RANGE, so at reading_speed 3.0 every clip
        sounded at natural * 0.5 and the cursor moved natural / 3:
        systematic overlap. The plan may only promise what the renderer
        will produce."""
        for speed in (5.0, 0.3):
            plan = plan_sequence(_slots(), _spoken(3), reading_speed=speed)
            assert plan.placements
            for p in plan.placements:
                _, total = build_segments(p)
                assert total == pytest.approx(p.play_s), \
                    f"planned {p.play_s}, renders {total} (speed={speed})"

    def test_names_break_variant_ties(self):
        a = _unit(["delta"], name="b.wav")
        b = _unit(["delta"], name="a.wav")
        plan = plan_sequence(_slots(), [a, b])
        assert plan.placements[0].unit.name == "a.wav"

    def test_every_slot_is_covered(self):
        plan = plan_sequence(_slots(), _spoken(3))
        assert plan.slots_used == plan.slots_total == 48
        assert plan.slots_dropped == 0

    def test_the_variant_travels_from_the_index_on_disk(self, tmp_path):
        """The order lives in words.json, so a unit that lost its variant on
        the way in would be sorted by name, which is not spoken order."""
        entries = {}
        for i in (2, 1):
            name = f"raw_{i:04d}.wav"
            audio_io.write_wav(tmp_path / name, _unit(["delta"]).audio)
            entries[name] = {"words": ["delta"], "variant": f"{i:04d}",
                             "syllables": 2, "duration_s": 0.4}
        (tmp_path / "words.json").write_text(json.dumps(entries),
                                             encoding="utf-8")

        units = load_bank(tmp_path, prefer_standardised=False,
                          singable_only=False)
        assert {u.name: u.variant for u in units} == {
            "raw_0001.wav": "0001", "raw_0002.wav": "0002"}


# ---------------------------------------------------------------------------
# The pace of the reciting
# ---------------------------------------------------------------------------

class TestReadingSpeed:
    def test_a_slower_pace_widens_every_span(self):
        # 0.4s units at half speed need 0.8s each, which is four 0.25s slots
        # instead of two, and half as many trips through the bank.
        natural = plan_sequence(_slots(), _spoken(3))
        slow = plan_sequence(_slots(), _spoken(3), reading_speed=0.5)
        assert len(slow.placements) == len(natural.placements) / 2
        for p in slow.placements:
            assert p.n_slots == 4
            assert p.target_s == pytest.approx(0.8)
            assert p.play_s == pytest.approx(0.8)

    def test_the_pace_comes_from_the_bank_not_the_song(self, tmp_path):
        """reading_speed declared in bank.json must reach every placement as
        its target duration; how fast a voice reads is a fact about the
        recording, not something the melody's slot grid decides."""
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"conservative": {"strategy": "sequence",
                                        "overrides": {"reading_speed": 0.5}}}
        }), encoding="utf-8")
        plan = arrange.build(_slots(), _spoken(3), "conservative", 1,
                             song="fixture", bank="fixture",
                             bank_dir=tmp_path)[0]
        assert plan.placements
        for p in plan.placements:
            assert p.target_s == pytest.approx(p.unit.duration_s / 0.5)

    def test_the_pace_holds_when_nothing_is_shifted(self):
        """Defect: the unshifted render branch truncated to play_s and
        clamped to the clip's natural length, so at --no-shift or mimicry
        0.00 reading_speed did nothing and the trailing-silence stutter came
        back. The target duration must be honoured with shifting off."""
        unit = _spoken(1)[0]  # a 0.4s clip
        slots = [Slot(0.0, 0.25, 53.0, 0), Slot(0.25, 0.5, 53.0, 0)]
        paced = Placement(unit=unit, onset_s=0.0, slot_span_s=0.5, play_s=0.8,
                          n_slots=2, phrase=0, slots=slots, split=False,
                          target_s=0.8)
        plan = Plan(placements=[paced], slots_used=2, slots_total=2)

        sr = config.SAMPLE_RATE
        bus = render(plan, int(2 * sr), sr, shift=False)
        tail = bus[:, int(0.55 * sr):int(0.75 * sr)]
        assert float(np.abs(tail).max()) > 0.01, \
            "the pace was dropped the moment shifting was off"

    def test_without_a_target_the_unshifted_branch_still_truncates(self):
        """The control for the test above, and the pinned old behaviour for
        every sung placement: no target, no stretching, the clip stops where
        play_s says."""
        unit = _spoken(1)[0]
        slots = [Slot(0.0, 0.25, 53.0, 0), Slot(0.25, 0.5, 53.0, 0)]
        p = Placement(unit=unit, onset_s=0.0, slot_span_s=0.5, play_s=0.3,
                      n_slots=2, phrase=0, slots=slots)
        plan = Plan(placements=[p], slots_used=2, slots_total=2)

        sr = config.SAMPLE_RATE
        bus = render(plan, int(2 * sr), sr, shift=False)
        tail = bus[:, int(0.35 * sr):]
        assert float(np.abs(tail).max()) == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# What the sequence strategy sings, pinned exactly
# ---------------------------------------------------------------------------

# The counterpart of tests/test_determinism.py, for the other strategy: the
# same fixture slots, three spoken units, one exact expectation. If this
# fails, the question is not "is the new expectation right", it is "did I
# mean to change what a sequence bank recites".
#
# Re-recorded once, deliberately, when reciting stopped waiting for the next
# note. The units are 0.4s and RECITE_WORD_GAP_S is 0.06, so inside a phrase
# every word now starts 0.46s after the one before, wherever the melody's
# notes happen to fall; the old 0.50 steps were the notes' own onsets. Each
# phrase still opens on its first note, because a phrase boundary is where
# the singer stopped for long enough to end the sentence.
SEQUENCE_1987 = [
    "phrase 0",
    "   0:00.00  x2  =0.50  delta                             [raw_0001.wav]",
    "   0:00.46  x2  =0.50  delta                             [raw_0002.wav]",
    "   0:00.92  x2  =0.50  delta                             [raw_0003.wav]",
    "   0:01.38  x2  =0.50  delta                             [raw_0001.wav]",
    "phrase 1",
    "   0:02.50  x2  =0.50  delta                             [raw_0002.wav]",
    "   0:02.96  x2  =0.50  delta                             [raw_0003.wav]",
    "   0:03.42  x2  =0.50  delta                             [raw_0001.wav]",
    "   0:03.88  x2  =0.50  delta                             [raw_0002.wav]",
    "phrase 2",
    "   0:05.00  x2  =0.50  delta                             [raw_0003.wav]",
    "   0:05.46  x2  =0.50  delta                             [raw_0001.wav]",
    "   0:05.92  x2  =0.50  delta                             [raw_0002.wav]",
    "   0:06.38  x2  =0.50  delta                             [raw_0003.wav]",
    "phrase 3",
    "   0:07.50  x2  =0.50  delta                             [raw_0001.wav]",
    "   0:07.96  x2  =0.50  delta                             [raw_0002.wav]",
    "   0:08.42  x2  =0.50  delta                             [raw_0003.wav]",
    "   0:08.88  x2  =0.50  delta                             [raw_0001.wav]",
    "phrase 4",
    "   0:10.00  x2  =0.50  delta                             [raw_0002.wav]",
    "   0:10.46  x2  =0.50  delta                             [raw_0003.wav]",
    "   0:10.92  x2  =0.50  delta                             [raw_0001.wav]",
    "   0:11.38  x2  =0.50  delta                             [raw_0002.wav]",
    "phrase 5",
    "   0:12.50  x2  =0.50  delta                             [raw_0003.wav]",
    "   0:12.96  x2  =0.50  delta                             [raw_0001.wav]",
    "   0:13.42  x2  =0.50  delta                             [raw_0002.wav]",
    "   0:13.88  x2  =0.50  delta                             [raw_0003.wav]",
]


def test_the_recitation_for_a_given_bank_does_not_move(tmp_path):
    (tmp_path / "bank.json").write_text(json.dumps({
        "levels": {"conservative": {"strategy": "sequence"}}
    }), encoding="utf-8")
    arr = arrange.build(_slots(), _spoken(3), "conservative", 1987,
                        song="fixture", bank="fixture", bank_dir=tmp_path)[1]
    got = [l.rstrip() for l in arrange.render_text(arr).splitlines()
           if l.strip() and not l.lstrip().startswith("#")]
    assert got == SEQUENCE_1987


# ---------------------------------------------------------------------------
# Keeping a clip whole
# ---------------------------------------------------------------------------

class TestNeverSplit:
    def test_a_whole_clip_is_fitted_to_its_target(self):
        """Defect: the whole-clip branch switched its fitting off whenever
        pace read 1.0, and an arranged planner never set pace, so a clip
        rendered at natural length over a fraction of the time and played
        over the next word. The target must be honoured, whoever planned."""
        unit = _unit(["tango", "bravo"])  # 0.8s
        slots = [Slot(0.0, 0.2, 60.0, 0), Slot(0.2, 0.4, 60.0, 0)]
        p = Placement(unit=unit, onset_s=0.0, slot_span_s=0.4, play_s=0.4,
                      n_slots=2, phrase=0, slots=slots, split=False,
                      target_s=0.4)
        segments, total = build_segments(p)
        assert len(segments) == 1
        assert total == pytest.approx(0.4)
        assert segments[0].out_dur_s == pytest.approx(0.4)

    def test_the_engine_range_bounds_the_fitting(self):
        """A clip is never compressed past what the engine stretches cleanly;
        beyond that a slight overrun beats an unrecognisable word."""
        unit = _unit(["tango", "bravo"])  # 0.8s
        slots = [Slot(0.0, 0.1, 60.0, 0)]
        p = Placement(unit=unit, onset_s=0.0, slot_span_s=0.1, play_s=0.1,
                      n_slots=1, phrase=0, slots=slots, split=False,
                      target_s=0.1)
        _, total = build_segments(p)
        lo, _ = config.TIME_STRETCH_RANGE
        assert total == pytest.approx(0.8 * lo)

    def test_an_arranged_level_of_a_never_split_bank_is_marked(self, tmp_path):
        """The live case: a bank that recites one level and arranges another.
        Every arranged placement must carry the no-split flag AND the time
        plan_words actually gave it, or build_segments has nothing to fit
        the whole clip to."""
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"wild": {"strategy": "arranged"}},
            "never_split": True,
        }), encoding="utf-8")
        plan = arrange.build(_slots(), _arranged_bank(), "wild", 1987,
                             song="fixture", bank="fixture",
                             bank_dir=tmp_path)[0]
        assert plan.placements
        for p in plan.placements:
            assert p.split is False
            assert p.target_s is not None
            assert p.target_s == pytest.approx(p.play_s)
            assert p.target_s <= p.slot_span_s + 1e-6

    def test_a_recited_never_split_clip_keeps_its_pace(self):
        """split=False and a pace target together: the whole clip is one
        segment stretched to the reciting pace, not to its slot span."""
        unit = _spoken(1)[0]  # 0.4s
        slots = [Slot(0.0, 0.25, 53.0, 0), Slot(0.25, 0.5, 53.0, 0)]
        p = Placement(unit=unit, onset_s=0.0, slot_span_s=0.5, play_s=0.5,
                      n_slots=2, phrase=0, slots=slots, split=False,
                      target_s=0.5)
        segments, total = build_segments(p)
        assert len(segments) == 1
        assert total == pytest.approx(0.5)


class TestRecitedSyllables:
    """The paced split path: end to end, nothing dropped, nothing on top."""

    def test_a_raw_shout_advances_the_recital_not_overlaps_it(self):
        """Defect, latent: in the paced path a raw shout syllable stayed
        pinned to its slot while its neighbours walked a cursor, so it
        sounded on top of them. Every syllable advances the cursor; the
        shout only keeps its recorded length while doing so."""
        unit = _unit(["aah", "calculator"])  # shout syllable first, 1.0s
        slots = [Slot(i * 0.25, (i + 1) * 0.25, 60.0, 0) for i in range(5)]
        p = Placement(unit=unit, onset_s=0.0, slot_span_s=1.25, play_s=1.5,
                      n_slots=5, phrase=0, slots=slots, split=True,
                      target_s=1.5)
        segments, total = build_segments(p)
        assert len(segments) == 5
        for a, b in zip(segments, segments[1:]):
            assert b.out_start_s == pytest.approx(a.out_start_s + a.out_dur_s)
        # The shout keeps its own length; the rest share the remaining time.
        assert segments[0].out_dur_s == pytest.approx(0.2)
        assert total == pytest.approx(1.5)

    def test_reciting_never_drops_a_syllable_short_of_slots(self):
        """Fewer slots than syllables happens whenever the slots are long.
        The sung path stops at the last slot; the recited path reuses its
        pitch instead, because half a spoken word is not a shorter word."""
        unit = _unit(["tango", "bravo"])  # 4 syllables, 0.8s
        slots = [Slot(0.0, 0.6, 60.0, 0)]
        p = Placement(unit=unit, onset_s=0.0, slot_span_s=0.6, play_s=0.8,
                      n_slots=1, phrase=0, slots=slots, split=True,
                      target_s=0.8)
        segments, total = build_segments(p)
        assert len(segments) == 4
        assert total == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

class TestSequenceReplay:
    """A sequence bank's own .arr must come back as the same plan.

    The file records what was placed where, and deliberately not how the
    bank behaves: never_split, the strategy and reading_speed are properties
    of the bank, re-derived at replay through the same resolution build
    uses. A replay that forgot them re-pitched whole spoken clips per
    syllable, sliced them into words, and cut them to their slots.
    """

    def _bank_dir(self, tmp_path):
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"conservative": {"strategy": "sequence",
                                        "overrides": {"reading_speed": 0.8}}},
            "never_split": True,
        }), encoding="utf-8")
        return tmp_path

    @staticmethod
    def _fingerprint(plan):
        return [(p.unit.name, round(p.onset_s, 3), p.n_slots, p.split,
                 round(p.play_s, 3),
                 None if p.target_s is None else round(p.target_s, 3))
                for p in plan.placements]

    def test_replay_reproduces_the_recitation(self, tmp_path):
        bank_dir = self._bank_dir(tmp_path)
        units = _spoken(5)
        plan, arrangement, _ = arrange.build(
            _slots(), units, "conservative", 7,
            song="fixture", bank="fixture", bank_dir=bank_dir)
        replayed = arrange.realise(
            arrange.parse_text(arrange.render_text(arrangement)),
            _slots(), units, bank_dir=bank_dir)
        assert self._fingerprint(replayed) == self._fingerprint(plan)

    def test_a_raw_banks_own_log_replays(self, tmp_path):
        """The bank this replay machinery was built for: build_bank --raw
        gives every unit the word "raw", which no vocabulary holds, so the
        bank's own log was refused at parsing and none of the replay work
        was reachable for it. The bank's words make the file readable, and
        the replay must be the plan that was rendered."""
        bank_dir = self._bank_dir(tmp_path)
        units = _raw_spoken(5)
        plan, arrangement, _ = arrange.build(
            _slots(), units, "conservative", 7,
            song="fixture", bank="fixture", bank_dir=bank_dir)
        text = arrange.render_text(arrangement)
        with pytest.raises(arrange.ArrangementError,
                           match="not words in this bank"):
            arrange.parse_text(text)
        replayed = arrange.realise(
            arrange.parse_text(text, bank_words={w for u in units
                                                 for w in u.words}),
            _slots(), units, bank_dir=bank_dir)
        assert self._fingerprint(replayed) == self._fingerprint(plan)

    def test_both_levels_shuffled_do_not_draw_the_same_order(self, tmp_path):
        """--seed hands one seed to every level, so drawing from it alone gave
        two identical files: the exact failure shuffled exists to fix,
        reappearing the moment somebody asked for a repeatable take."""
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"conservative": {"strategy": "shuffled"},
                       "wild": {"strategy": "shuffled"}},
            "never_split": True,
        }), encoding="utf-8")
        units = _raw_spoken(8)
        orders = []
        for level in ("conservative", "wild"):
            plan = arrange.build(_slots(), units, level, 11, song="f", bank="f",
                                 bank_dir=tmp_path)[0]
            orders.append([p.unit.name for p in plan.placements])
        assert orders[0] != orders[1]

    def test_the_same_seed_and_level_draw_the_same_order(self, tmp_path):
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"wild": {"strategy": "shuffled"}}, "never_split": True,
        }), encoding="utf-8")
        units = _raw_spoken(8)
        twice = [[p.unit.name for p in arrange.build(
            _slots(), units, "wild", 11, song="f", bank="f",
            bank_dir=tmp_path)[0].placements] for _ in range(2)]
        assert twice[0] == twice[1]

    def test_the_draw_does_not_depend_on_the_order_the_bank_loaded_in(self, tmp_path):
        """Shuffling load_bank's order made words.json key order an input, so
        the same seed gave a different take once a clip was added anywhere."""
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"wild": {"strategy": "shuffled"}}, "never_split": True,
        }), encoding="utf-8")
        units = _raw_spoken(8)
        straight = [p.unit.name for p in arrange.build(
            _slots(), units, "wild", 11, song="f", bank="f",
            bank_dir=tmp_path)[0].placements]
        reversed_load = [p.unit.name for p in arrange.build(
            _slots(), list(reversed(units)), "wild", 11, song="f", bank="f",
            bank_dir=tmp_path)[0].placements]
        assert straight == reversed_load

    def test_shuffled_without_never_split_is_refused(self, tmp_path):
        """The strategy promises whole clips and cannot keep that promise on
        its own: without never_split the clips are cut at their syllables and
        scaled to their slots, silently."""
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"wild": {"strategy": "shuffled"}},
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="never_split"):
            banks.strategy_for(tmp_path, "wild")

    def test_a_shuffled_bank_replays_by_reciting(self, tmp_path):
        """The whole point of shuffling is that nothing is stretched or cut.

        Replay re-derives the strategy from the bank, and it read only
        "sequence", so a shuffled take fell through to the arranged path and
        came back fitted to its notes: every clip stretched to its slot, which
        is exactly what the strategy exists to avoid.
        """
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"conservative": {"strategy": "shuffled"}},
            "never_split": True,
        }), encoding="utf-8")
        units = _raw_spoken(6)
        plan, arrangement, _ = arrange.build(
            _slots(), units, "conservative", 11,
            song="fixture", bank="fixture", bank_dir=tmp_path)
        replayed = arrange.realise(
            arrange.parse_text(arrange.render_text(arrangement),
                               bank_words={w for u in units for w in u.words}),
            _slots(), units, bank_dir=tmp_path)

        assert self._fingerprint(replayed) == self._fingerprint(plan)
        # Reciting gives each clip the time it needs; the arranged path would
        # have cut every target down to its slot span.
        for p in replayed.placements:
            assert p.target_s == pytest.approx(p.unit.duration_s, rel=1e-3)

    def test_shuffling_changes_the_order_and_nothing_else(self, tmp_path):
        """Same clips, same lengths, different running order."""
        for strategy in ("sequence", "shuffled"):
            (tmp_path / "bank.json").write_text(json.dumps({
                "levels": {"conservative": {"strategy": strategy}},
                "never_split": True,
            }), encoding="utf-8")
            units = _raw_spoken(6)
            plan = arrange.build(_slots(), units, "conservative", 11,
                                 song="fixture", bank="fixture",
                                 bank_dir=tmp_path)[0]
            if strategy == "sequence":
                straight = [p.unit.name for p in plan.placements]
                lengths = sorted(round(p.target_s, 4) for p in plan.placements)
            else:
                shuffled = [p.unit.name for p in plan.placements]
                assert sorted(round(p.target_s, 4)
                              for p in plan.placements) == lengths
        assert shuffled != straight, "the order was not drawn from the seed"

    def test_replay_keeps_the_recitation_off_the_notes(self, tmp_path):
        """The defect, named. A recitation starts each word
        RECITE_WORD_GAP_S after the last one stopped rather than on a note,
        so the time written in the file is not any slot's onset. Replay
        anchored every line to the nearest slot, which snapped the words back
        onto the melody and, where the next note was far away, anchored them
        to a different slot than the one they had been placed on. The take
        that came back was not the take that was rendered.
        """
        bank_dir = self._bank_dir(tmp_path)
        units = _spoken(5)
        plan, arrangement, _ = arrange.build(
            _slots(), units, "conservative", 7,
            song="fixture", bank="fixture", bank_dir=bank_dir)
        replayed = arrange.realise(
            arrange.parse_text(arrange.render_text(arrangement)),
            _slots(), units, bank_dir=bank_dir)

        notes = {round(s.onset_s, 6) for s in _slots()}
        off = [p for p in replayed.placements
               if round(p.onset_s, 6) not in notes]
        assert off, ("every replayed word landed on a note, so the "
                     "recitation was snapped back onto the melody")
        assert ([round(p.onset_s, 6) for p in replayed.placements]
                == [round(p.onset_s, 6) for p in plan.placements])

    def test_an_arrangement_longer_than_the_song_is_refused(self, tmp_path):
        """Handing back a shorter song that still claimed to be this
        arrangement would be a silent truncation, which is the failure the
        whole replay path is arranged to avoid."""
        bank_dir = self._bank_dir(tmp_path)
        units = _spoken(5)
        _, arrangement, _ = arrange.build(
            _slots(), units, "conservative", 7,
            song="fixture", bank="fixture", bank_dir=bank_dir)
        with pytest.raises(arrange.ArrangementError, match="room for"):
            arrange.realise(
                arrange.parse_text(arrange.render_text(arrangement)),
                _slots(n=8), units, bank_dir=bank_dir)

    def test_replay_does_not_slice_a_never_split_bank(self, tmp_path):
        bank_dir = self._bank_dir(tmp_path)
        units = _spoken(5)
        _, arrangement, _ = arrange.build(
            _slots(), units, "conservative", 7,
            song="fixture", bank="fixture", bank_dir=bank_dir)
        replayed = arrange.realise(
            arrange.parse_text(arrange.render_text(arrangement)),
            _slots(), units, bank_dir=bank_dir)
        for p in replayed.placements:
            assert "#" not in p.unit.name, "a spoken clip came back as a slice"
            assert p.split is False

    @pytest.mark.parametrize("never_split", [True, False])
    @pytest.mark.parametrize("units_fn", [_spoken, _raw_spoken])
    def test_replay_reproduces_whether_or_not_the_bank_splits(
            self, tmp_path, never_split, units_fn):
        """Every other test in this class declares never_split, but a sequence
        bank is not obliged to. Without it the pool is enriched with slices and
        joins, so unit_for is choosing from a different and much larger set,
        and the take named in the file has to still win against them."""
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"conservative": {"strategy": "sequence"}},
            "never_split": never_split,
        }), encoding="utf-8")
        units = units_fn(5)
        plan, arrangement, _ = arrange.build(
            _slots(), units, "conservative", 11,
            song="fixture", bank="fixture", bank_dir=tmp_path)

        replayed = arrange.realise(
            arrange.parse_text(arrange.render_text(arrangement),
                               bank_words={w for u in units for w in u.words}),
            _slots(), units, bank_dir=tmp_path)

        assert self._fingerprint(replayed) == self._fingerprint(plan)

    def test_replay_without_a_bank_dir_stays_exactly_as_before(self, tmp_path):
        """The default is the behaviour every existing .arr depends on."""
        units = _arranged_bank()
        plan, arrangement, _ = arrange.build(_slots(), units, "wild", 31)
        replayed = arrange.realise(
            arrange.parse_text(arrange.render_text(arrangement)),
            _slots(), units, bank_dir=None)
        assert [p.unit.name for p in replayed.placements] == \
               [p.unit.name for p in plan.placements]
        for p in replayed.placements:
            assert p.split is True
            assert p.target_s is None


# ---------------------------------------------------------------------------
# The bank's own level against the bed
# ---------------------------------------------------------------------------

class TestShiftCap:
    """How far a bank's voice may be moved before the shift folds.

    A property of the recordings. SHIFT_CAP_SEMITONES is 12 because 12 was
    measured and judged by ear against 7, but on SUNG banks. A speaking voice
    tears sooner, and the words broke at their ends long before the tool
    thought it was asking too much.
    """

    def test_a_bank_that_declares_nothing_takes_the_tools_own_limit(self, tmp_path):
        assert banks.shift_cap(tmp_path) == config.SHIFT_CAP_SEMITONES
        assert banks.shift_cap(None) == config.SHIFT_CAP_SEMITONES

    def test_a_declared_cap_is_returned(self, tmp_path):
        (tmp_path / "bank.json").write_text(json.dumps({
            "shift_cap_semitones": 6.0
        }), encoding="utf-8")
        assert banks.shift_cap(tmp_path) == 6.0

    def test_a_string_is_refused_by_name(self, tmp_path):
        (tmp_path / "bank.json").write_text(json.dumps({
            "shift_cap_semitones": "6.0"
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="shift_cap_semitones") as caught:
            banks.shift_cap(tmp_path)
        assert "bank.json" in str(caught.value)

    @pytest.mark.parametrize("cap", [0.0, -6.0, 13.0])
    def test_a_cap_outside_what_the_tool_can_do_is_refused(self, tmp_path, cap):
        """Zero would fold everything and a cap above the tool's own limit
        would claim a distance it never shifts, both silently."""
        (tmp_path / "bank.json").write_text(json.dumps({
            "shift_cap_semitones": cap
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="shift_cap_semitones"):
            banks.shift_cap(tmp_path)

    def test_the_cap_reaches_the_thing_that_folds(self, tmp_path):
        """The whole point: a declared cap has to arrive at fold_shift, or it
        is a number in a file that changes nothing."""
        from song_generator.pitchshift import fold_shift

        assert abs(fold_shift(9.0, 6.0)) <= 6.0
        assert fold_shift(9.0, 12.0) == pytest.approx(9.0)


class TestWordBusLufs:
    def test_the_declared_level_is_returned(self, tmp_path):
        (tmp_path / "bank.json").write_text(json.dumps({
            "mix": {"word_bus_lufs": -11.0}
        }), encoding="utf-8")
        assert banks.mix_for(tmp_path) == {"word_bus_lufs": -11.0}
        assert banks.mix_for(None) == {}

    def test_a_string_is_refused_by_file_not_deep_in_the_mix(self, tmp_path):
        """A JSON string used to surface as a TypeError inside _normalise,
        blaming nothing. The refusal must name the file and the setting."""
        (tmp_path / "bank.json").write_text(json.dumps({
            "mix": {"word_bus_lufs": "-11.0"}
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="word_bus_lufs") as caught:
            banks.mix_for(tmp_path)
        assert "bank.json" in str(caught.value)

    def test_a_reading_speed_that_is_not_a_number_is_refused(self, tmp_path):
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"conservative": {"strategy": "sequence",
                                        "overrides": {"reading_speed": "0.8"}}}
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="reading_speed") as caught:
            banks.overrides_for(tmp_path, "conservative")
        assert "bank.json" in str(caught.value)

    def test_a_reading_speed_of_zero_is_refused(self, tmp_path):
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"conservative": {"strategy": "sequence",
                                        "overrides": {"reading_speed": 0}}}
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="reading_speed"):
            banks.overrides_for(tmp_path, "conservative")

    def test_a_pace_the_engine_cannot_deliver_is_refused(self, tmp_path):
        """A reading_speed of 3.0 used to pass validation, every clip then
        sounded at the clamped pace while the planner's cursor kept the
        declared one, and the words landed on top of each other. What the
        file accepts must be what the engine delivers."""
        for speed in (3.0, 0.3):
            (tmp_path / "bank.json").write_text(json.dumps({
                "levels": {"conservative": {
                    "strategy": "sequence",
                    "overrides": {"reading_speed": speed}}}
            }), encoding="utf-8")
            with pytest.raises(ValueError, match="reading_speed") as caught:
                banks.overrides_for(tmp_path, "conservative")
            assert "bank.json" in str(caught.value)

    def test_the_accepted_range_is_the_engines_own(self, tmp_path):
        """Derived from TIME_STRETCH_RANGE rather than typed beside it, so
        retuning the engine cannot leave the validation refusing paces it
        now delivers. Both endpoints are deliverable, so both pass."""
        lo, hi = config.TIME_STRETCH_RANGE
        assert banks.reading_speed_range() == (1.0 / hi, 1.0 / lo)
        for speed in banks.reading_speed_range():
            (tmp_path / "bank.json").write_text(json.dumps({
                "levels": {"conservative": {
                    "strategy": "sequence",
                    "overrides": {"reading_speed": speed}}}
            }), encoding="utf-8")
            got = banks.overrides_for(tmp_path, "conservative")
            assert got["reading_speed"] == speed

    def test_the_level_reaches_the_mix(self):
        """mix() must honour a bank's declared bus level, or the whole
        setting is a comment."""
        sr = config.SAMPLE_RATE
        t = np.arange(2 * sr) / sr
        tone = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        words = np.stack([tone, tone])
        bed = np.zeros_like(words)

        loud = mix_buses(words, bed, sr, word_bus_lufs=-20.0)
        quiet = mix_buses(words, bed, sr, word_bus_lufs=-40.0)

        def rms(x):
            return float(np.sqrt(np.mean(np.square(x))))

        assert rms(loud) > 5 * rms(quiet)


# ---------------------------------------------------------------------------
# Settings resolve to the bank, however the directory was reached
# ---------------------------------------------------------------------------

class TestSettingsComeFromTheBank:
    def _bank_and_tier(self, tmp_path):
        bank = tmp_path / "words_hq"
        bank.mkdir()
        (bank / "bank.json").write_text(json.dumps({
            "levels": {"conservative": {"strategy": "sequence"}},
            "mix": {"word_bus_lufs": -11.0},
            "never_split": True,
        }), encoding="utf-8")
        tier = tmp_path / ("words_hq" + config.STD_SUFFIX)
        tier.mkdir()
        (tier / config.STD_MANIFEST).write_text("{}", encoding="utf-8")
        return bank, tier

    def test_a_tier_answers_with_what_its_bank_declared(self, tmp_path):
        """Defect: --words-dir pointed at a .std tier read settings from the
        tier itself, which has no bank.json, so every declared setting
        silently vanished. A tier is a derivative of its bank."""
        bank, tier = self._bank_and_tier(tmp_path)
        assert banks.settings_dir(tier) == bank
        assert banks.strategy_for(tier, "conservative") == "sequence"
        assert banks.never_split(tier) is True
        assert banks.mix_for(tier).get("word_bus_lufs") == -11.0

    def test_the_bank_itself_is_untouched_by_the_rule(self, tmp_path):
        bank, _ = self._bank_and_tier(tmp_path)
        assert banks.settings_dir(bank) == bank
        assert banks.strategy_for(bank, "conservative") == "sequence"

    def test_a_name_alone_does_not_make_a_tier(self, tmp_path):
        """The manifest marker decides, the same rule resolve_bank uses. A
        directory that merely ends in .std speaks for itself."""
        d = tmp_path / "foo.std"
        d.mkdir()
        assert banks.settings_dir(d) == d

    def test_a_tier_whose_bank_is_gone_speaks_for_itself(self, tmp_path):
        tier = tmp_path / ("orphan" + config.STD_SUFFIX)
        tier.mkdir()
        (tier / config.STD_MANIFEST).write_text("{}", encoding="utf-8")
        assert banks.settings_dir(tier) == tier
        assert banks.strategy_for(tier, "conservative") == "arranged"


# ---------------------------------------------------------------------------
# The declaration
# ---------------------------------------------------------------------------

class TestBankSettings:
    def test_a_bank_with_no_bank_json_behaves_exactly_as_today(self, tmp_path):
        assert banks.strategy_for(tmp_path, "conservative") == "arranged"
        assert banks.strategy_for(tmp_path, "wild") == "arranged"
        assert banks.overrides_for(tmp_path, "wild") == {}

    def test_a_declared_strategy_and_overrides_are_returned(self, tmp_path):
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {
                "conservative": {"strategy": "sequence"},
                "wild": {"strategy": "arranged",
                         "overrides": {"chant_chance": 0.55, "chant_max": 6}},
            }
        }), encoding="utf-8")
        assert banks.strategy_for(tmp_path, "conservative") == "sequence"
        assert banks.strategy_for(tmp_path, "wild") == "arranged"
        assert banks.overrides_for(tmp_path, "conservative") == {}
        assert banks.overrides_for(tmp_path, "wild") == {
            "chant_chance": 0.55, "chant_max": 6}

    def test_an_unknown_strategy_is_refused_by_name(self, tmp_path):
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"wild": {"strategy": "feral"}}
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="feral") as caught:
            banks.strategy_for(tmp_path, "wild")
        said = str(caught.value)
        assert "bank.json" in said
        assert "arranged" in said and "sequence" in said

    def test_a_typo_is_caught_even_for_the_level_not_being_asked_about(self, tmp_path):
        """Otherwise it sits unnoticed until the day that level runs."""
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"wild": {"strategy": "feral"}}
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="feral"):
            banks.strategy_for(tmp_path, "conservative")

    def test_malformed_json_is_refused_rather_than_read_as_empty(self, tmp_path):
        (tmp_path / "bank.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="bank.json"):
            banks.strategy_for(tmp_path, "wild")

    def test_a_misspelled_level_is_refused_by_name(self, tmp_path):
        """"conservativ" declared sequence and the conservative level
        rendered arranged, silently, in the wrong order: exactly the
        failure this file exists to prevent, reached through the key
        instead of the value."""
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"conservativ": {"strategy": "sequence"}}
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="conservativ") as caught:
            banks.strategy_for(tmp_path, "conservative")
        said = str(caught.value)
        assert "bank.json" in said
        assert "conservative" in said and "wild" in said

    def test_a_misspelled_override_knob_is_refused_by_name(self, tmp_path):
        """"reading_sped": 0.8 left the pace at 1.0 with no complaint. An
        override nothing reads changes nothing and says nothing."""
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"conservative": {"strategy": "sequence",
                                        "overrides": {"reading_sped": 0.8}}}
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="reading_sped") as caught:
            banks.overrides_for(tmp_path, "conservative")
        assert "bank.json" in str(caught.value)

    def test_every_knob_a_level_defines_may_be_overridden(self, tmp_path):
        """The control for the refusal above: the legitimate set is the
        level's own parameters plus reading_speed, so leaning on all of
        them at once passes."""
        knobs = dict(config.PLAY_LEVELS["wild"])
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"wild": {"strategy": "arranged", "overrides": knobs}}
        }), encoding="utf-8")
        assert banks.overrides_for(tmp_path, "wild") == knobs

    def test_a_levels_section_of_the_wrong_shape_is_refused(self, tmp_path):
        """"levels": [] used to surface as a bare AttributeError traceback,
        blaming nothing, which is outside the refuse-by-name contract."""
        (tmp_path / "bank.json").write_text(json.dumps({"levels": []}),
                                            encoding="utf-8")
        with pytest.raises(ValueError, match="levels") as caught:
            banks.strategy_for(tmp_path, "wild")
        assert "bank.json" in str(caught.value)

    def test_a_level_that_is_not_an_object_is_refused(self, tmp_path):
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"wild": "sequence"}
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="wild") as caught:
            banks.strategy_for(tmp_path, "wild")
        assert "bank.json" in str(caught.value)

    def test_overrides_of_the_wrong_shape_are_refused(self, tmp_path):
        """Named as a shape problem. Without the shape check the knob check
        reads the string as its characters and refuses those, which blames
        four knobs called 'f', 'a', 's' and 't' instead of the mistake."""
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"wild": {"strategy": "arranged", "overrides": "fast"}}
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="must be an object") as caught:
            banks.overrides_for(tmp_path, "wild")
        assert "bank.json" in str(caught.value)

    def test_a_file_that_is_not_an_object_is_refused(self, tmp_path):
        (tmp_path / "bank.json").write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError, match="bank.json"):
            banks.strategy_for(tmp_path, "wild")

    def test_a_never_split_string_is_refused_not_read_as_true(self, tmp_path):
        """The two numeric settings got type checks; the boolean did not,
        and bool("false") is True, so a bank meaning to allow splitting
        kept every clip whole."""
        (tmp_path / "bank.json").write_text(json.dumps({
            "never_split": "false"
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="never_split") as caught:
            banks.never_split(tmp_path)
        assert "bank.json" in str(caught.value)


# ---------------------------------------------------------------------------
# The wiring through arrange.build
# ---------------------------------------------------------------------------

class TestBuildDispatch:
    def _sequence_dir(self, tmp_path):
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"conservative": {"strategy": "sequence"}}
        }), encoding="utf-8")
        return tmp_path

    def test_a_sequence_bank_is_recited_not_arranged(self, tmp_path):
        bank_dir = self._sequence_dir(tmp_path)
        plan, arrangement, tries = arrange.build(
            _slots(), _spoken(5), "conservative", 1987,
            song="fixture", bank="fixture", bank_dir=bank_dir)
        assert tries == 1
        assert [p.unit.variant for p in plan.placements[:3]] == [
            "0001", "0002", "0003"]
        # The description still works, so the .arr log keeps its shape.
        assert len(arrangement.lines) == len(plan.placements)
        assert arrangement.lines[0].take == "raw_0001.wav"

    def test_the_seed_changes_nothing_in_a_sequence(self, tmp_path):
        """No randomness at all is the rule, and this is what it looks like
        from outside: two different seeds, one identical result."""
        bank_dir = self._sequence_dir(tmp_path)

        def lines(seed):
            arrangement = arrange.build(
                _slots(), _spoken(5), "conservative", seed,
                song="fixture", bank="fixture", bank_dir=bank_dir)[1]
            return [(l.phrase, l.onset_s, l.n_slots, l.take)
                    for l in arrangement.lines]

        assert lines(1) == lines(2)

    def test_an_undeclared_bank_dir_matches_no_bank_dir_at_all(self, tmp_path):
        """A bank directory holding no bank.json must change nothing."""
        def lines(bank_dir):
            arrangement = arrange.build(
                _slots(), _arranged_bank(), "conservative", 1987,
                song="fixture", bank="fixture", bank_dir=bank_dir)[1]
            return [(l.phrase, l.onset_s, l.take) for l in arrangement.lines]

        assert lines(tmp_path) == lines(None)


class TestOverrides:
    def test_overrides_reach_the_planner(self, tmp_path):
        # phrase_fill 1.0 keeps every phrase, and the fixture at this seed
        # otherwise leaves some instrumental, so the difference is visible in
        # which phrases carry words, deterministically.
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"conservative": {"strategy": "arranged",
                                        "overrides": {"phrase_fill": 1.0}}}
        }), encoding="utf-8")
        every_phrase = set(range(len(group_phrases(_slots()))))

        def sung_phrases(bank_dir):
            arrangement = arrange.build(
                _slots(), _arranged_bank(), "conservative", 1987,
                song="fixture", bank="fixture", bank_dir=bank_dir)[1]
            return {l.phrase for l in arrangement.lines}

        assert sung_phrases(None) != every_phrase
        assert sung_phrases(tmp_path) == every_phrase

    def test_overrides_do_not_mutate_the_levels_in_config(self, tmp_path):
        """batch renders many songs in one process. A write into
        config.PLAY_LEVELS would carry this bank's overrides into every
        later song, whatever bank it sings from."""
        (tmp_path / "bank.json").write_text(json.dumps({
            "levels": {"conservative": {"strategy": "arranged",
                                        "overrides": {"phrase_fill": 1.0,
                                                      "chant_chance": 0.99}}}
        }), encoding="utf-8")
        before = copy.deepcopy(config.PLAY_LEVELS)
        arrange.build(_slots(), _arranged_bank(), "conservative", 1987,
                      song="fixture", bank="fixture", bank_dir=tmp_path)
        assert config.PLAY_LEVELS == before


# ---------------------------------------------------------------------------
# The declaration at the command line
# ---------------------------------------------------------------------------

class TestCommandLine:
    """cli.main with the pipeline stubbed out around the declaration layer.

    Decoding, separation, detection and analysis are fixtures; what actually
    runs is bank.json, the arrangement, and the render. That is the slice
    these two contracts live in: a refusal must arrive as an error with the
    error exit code, and a sequence bank must be able to replay the log it
    wrote.
    """

    def _stub_pipeline(self, monkeypatch):
        sr = config.SAMPLE_RATE
        silence = np.zeros((2, 6 * sr), dtype=np.float32)

        monkeypatch.setattr(audio_io, "decode", lambda path: silence)
        written = []
        monkeypatch.setattr(audio_io, "encode_mp3",
                            lambda path, audio: written.append(Path(path)))
        stems = types.SimpleNamespace(vocal=silence, instrumental=silence,
                                      cached=True, backend="demucs")
        monkeypatch.setattr(cli, "separate", lambda *a, **k: stems)
        found = types.SimpleNamespace(
            vocal_lufs=-20.0, mix_lufs=-14.0, rel_lu=6.0, voiced_frac=0.5,
            f0_backend="fixture", vocal_present=True, reasons=[],
            as_dict=lambda: {})
        monkeypatch.setattr(cli, "detect_vocal", lambda *a, **k: found)
        notes = [types.SimpleNamespace(
            onset_s=i * 0.25, offset_s=(i + 1) * 0.25, dur_s=0.25,
            midi=53.0 + (i % 5), phrase=i // 8, rms_db=-20.0)
            for i in range(16)]
        analysis = types.SimpleNamespace(
            notes=notes, to_json=lambda path, include_f0=True: None)
        monkeypatch.setattr(cli, "analyse", lambda *a, **k: analysis)
        monkeypatch.setattr(cli, "analysis_report", lambda *a, **k: "")
        return written

    def _song_and_bank(self, tmp_path, declaration):
        song = tmp_path / "song.mp4"
        song.write_bytes(b"x")
        words = tmp_path / "spoken"
        words.mkdir()
        (words / "bank.json").write_text(json.dumps(declaration),
                                         encoding="utf-8")
        return ([str(song), "--words-dir", str(words),
                 "--work-dir", str(tmp_path / "work"),
                 "-o", str(tmp_path / "out.mp3")])

    def test_a_malformed_declaration_is_an_error_not_a_traceback(
            self, tmp_path, monkeypatch, capsys):
        """The deliberate refusals in banks.py arrived at the command line
        as uncaught ValueError tracebacks with exit 1, instead of the
        error: line and the error exit code every other refusal gets."""
        self._stub_pipeline(monkeypatch)
        argv = self._song_and_bank(tmp_path, {"never_split": "false"})
        assert cli.main(argv) == 2
        assert "error:" in capsys.readouterr().err

    def test_a_sequence_bank_replays_its_own_log_at_the_command_line(
            self, tmp_path, monkeypatch):
        """The whole loop the log exists for: render once, then feed the
        .arr the run wrote straight back with --arrangement. With a raw
        bank this failed at parsing, before realise was reached, because
        "raw" is in no vocabulary."""
        self._stub_pipeline(monkeypatch)
        argv = self._song_and_bank(tmp_path, {
            "levels": {"conservative": {"strategy": "sequence",
                                        "overrides": {"reading_speed": 0.8}}},
            "never_split": True,
        }) + ["--no-shift"]
        units = _raw_spoken(3)
        monkeypatch.setattr(cli, "load_bank", lambda *a, **k: units)
        monkeypatch.setattr(cli, "resolve_bank",
                            lambda d, prefer_standardised=True: (d, False))

        assert cli.main(argv + ["--play", "conservative", "--seed", "7"]) == 0
        logs = list((tmp_path / "work").rglob("*.arr"))
        assert len(logs) == 1
        assert cli.main(argv + ["--arrangement", str(logs[0])]) == 0


# ---------------------------------------------------------------------------
# Output separated by bank
# ---------------------------------------------------------------------------

class TestOutputPerBank:
    def test_two_banks_for_one_song_write_to_different_folders(self):
        from song_generator.cli import output_path

        a = output_path(None, Path("input/song.mp4"), "ppbank")
        b = output_path(None, Path("input/song.mp4"), "muslimbank")
        assert a != b
        assert a.name == b.name == "song.mp3"
        assert a.parent.name == "ppbank"
        assert b.parent.name == "muslimbank"
        # Same song folder, so the levels of one song stay side by side.
        assert a.parent.parent == b.parent.parent
