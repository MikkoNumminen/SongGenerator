"""Stage 3: slot cleanup, unit placement, mixing."""

import numpy as np
import pytest

from luokkaretki import config
from luokkaretki.mapping import (
    Plan, Slot, Unit, clean_slots, decide_by_mimicry, decide_shifts, group_phrases,
    mimicry, mix, plan_words, render, report,
)

SR = config.SAMPLE_RATE


def _unit(words, syllables, dur=0.5, name=None):
    n = int(dur * SR)
    audio = (0.3 * np.sin(2 * np.pi * 200 * np.arange(n) / SR)).astype(np.float32)
    return Unit(name=name or ("-".join(words) + ".wav"), words=list(words),
                syllables=syllables, duration_s=dur, midi=53.0,
                audio=np.stack([audio, audio]))


@pytest.fixture
def bank():
    return [
        _unit(["paska"], 2, 0.45),
        _unit(["perse", "pillu"], 4, 0.9),
        _unit(["perse", "pillu", "perse"], 6, 1.5),
        _unit(["paska", "perse", "pornolehti"], 8, 1.8),
    ]


def _slots(n, start=0.0, dur=0.25, gap=0.0, phrase=0):
    out, t = [], start
    for _ in range(n):
        out.append(Slot(t, t + dur, 60.0, phrase))
        t += dur + gap
    return out


class TestSlotCleanup:
    def test_blips_are_merged_into_their_neighbour(self):
        notes = [
            {"onset_s": 0.0, "offset_s": 0.30, "midi": 60.0, "phrase": 0},
            {"onset_s": 0.30, "offset_s": 0.33, "midi": 60.0, "phrase": 0},  # 30ms blip
            {"onset_s": 0.33, "offset_s": 0.60, "midi": 60.0, "phrase": 0},
        ]
        slots, merged, _ = clean_slots(notes)
        assert merged == 1
        assert len(slots) == 2
        assert all(s.dur_s >= config.MIN_SYLLABLE_S for s in slots)

    def test_held_notes_are_split_into_several_syllables(self):
        notes = [{"onset_s": 0.0, "offset_s": 2.0, "midi": 60.0, "phrase": 0}]
        slots, _, split = clean_slots(notes)
        assert split == 1
        assert 2 <= len(slots) <= config.MAX_SLOT_SPLIT
        assert all(s.dur_s <= config.MAX_SYLLABLE_S for s in slots)
        assert slots[0].onset_s == 0.0
        assert slots[-1].offset_s == pytest.approx(2.0)

    def test_empty_input(self):
        assert clean_slots([]) == ([], 0, 0)


class TestPhraseGrouping:
    def test_a_long_gap_starts_a_new_phrase(self):
        slots = _slots(2) + _slots(2, start=5.0)
        assert len(group_phrases(slots)) == 2

    def test_contiguous_slots_stay_one_phrase(self):
        assert len(group_phrases(_slots(6))) == 1


class TestPlacement:
    def test_even_phrase_is_filled_exactly(self, bank):
        plan = plan_words(_slots(8), bank)
        assert plan.slots_used == 8
        assert plan.slots_dropped == 0

    def test_odd_phrase_leaves_at_most_one_slot(self, bank):
        """Every bank unit is even, so an odd phrase can only ever end this way."""
        for n in (3, 5, 7, 9, 11):
            plan = plan_words(_slots(n), bank)
            assert plan.slots_total - plan.slots_used <= 1, f"{n} slots"

    def test_merge_last_absorbs_the_leftover_slot(self, bank, monkeypatch):
        monkeypatch.setattr(config, "ODD_SLOT_POLICY", "merge_last")
        plan = plan_words(_slots(5), bank)
        assert plan.slots_used == 5
        assert plan.slots_dropped == 0

    def test_drop_policy_leaves_it_silent(self, bank, monkeypatch):
        monkeypatch.setattr(config, "ODD_SLOT_POLICY", "drop")
        plan = plan_words(_slots(5), bank)
        assert plan.slots_dropped == 1

    def test_no_unit_runs_into_the_next(self, bank):
        plan = plan_words(_slots(24), bank)
        for a, b in zip(plan.placements, plan.placements[1:]):
            assert a.onset_s + a.play_s <= b.onset_s + 1e-6

    def test_placements_are_in_time_order(self, bank):
        plan = plan_words(_slots(24), bank)
        onsets = [p.onset_s for p in plan.placements]
        assert onsets == sorted(onsets)

    def test_every_placement_starts_on_a_slot_onset(self, bank):
        slots = _slots(16)
        onsets = {round(s.onset_s, 6) for s in slots}
        for p in plan_words(slots, bank).placements:
            assert round(p.onset_s, 6) in onsets

    def test_seed_makes_it_reproducible(self, bank):
        a = [p.unit.name for p in plan_words(_slots(20), bank, seed=7).placements]
        b = [p.unit.name for p in plan_words(_slots(20), bank, seed=7).placements]
        assert a == b

    def test_a_bank_with_only_long_units_cannot_fill_short_phrases(self):
        plan = plan_words(_slots(2), [_unit(["a", "b", "c"], 8, 1.8)])
        assert plan.slots_dropped == 2
        assert plan.placements == []


class TestRenderAndMix:
    def test_render_places_audio_at_the_right_sample(self, bank):
        slots = _slots(8, start=1.0)
        plan = plan_words(slots, bank)
        bus = render(plan, int(20 * SR))
        first = plan.placements[0]
        start = int(first.onset_s * SR)
        assert not np.any(bus[:, :start - 10])
        assert np.any(bus[:, start:start + 100])

    def test_render_never_exceeds_the_buffer(self, bank):
        plan = plan_words(_slots(8, start=9.5), bank)
        n = int(10 * SR)
        assert render(plan, n).shape == (2, n)

    def test_mix_respects_the_peak_ceiling(self):
        n = SR * 3
        loud = np.ones((2, n), dtype=np.float32) * 0.9
        out = mix(loud, loud)
        ceiling = 10 ** (config.OUTPUT_PEAK_CEILING_DB / 20)
        assert float(np.abs(out).max()) <= ceiling + 1e-6

    def test_mix_truncates_to_the_shorter_bus(self):
        a = np.zeros((2, SR * 2), dtype=np.float32)
        b = np.zeros((2, SR * 3), dtype=np.float32)
        assert mix(a, b).shape[1] == SR * 2


class TestShiftMix:
    """How much of the track sings along.

    Everything shifted sounds sung and stops being funny; nothing shifted is
    funny but never sounds like singing. The knob has to reach both ends
    exactly, and land in between without drifting.
    """

    def test_zero_leaves_everything_at_its_own_pitch(self, bank):
        plan = plan_words(_slots(40), bank)
        decide_shifts(plan, mix=0.0)
        assert not any(p.do_shift for p in plan.placements)

    def test_one_puts_everything_on_the_melody(self, bank):
        plan = plan_words(_slots(40), bank)
        decide_shifts(plan, mix=1.0)
        assert all(p.do_shift for p in plan.placements)

    @pytest.mark.parametrize("mix", [0.25, 0.5, 0.75])
    def test_proportion_is_honoured(self, bank, mix):
        plan = plan_words(_slots(80), bank)
        decide_shifts(plan, mix=mix)
        n = len(plan.placements)
        shifted = sum(1 for p in plan.placements if p.do_shift)
        assert abs(shifted / n - mix) < 0.1, f"{shifted}/{n} for mix={mix}"

    def test_furthest_mode_leaves_the_big_jumps_alone(self, bank):
        """Those are the most absurd unshifted, and the worst damaged shifted."""
        slots = [Slot(i * 0.3, i * 0.3 + 0.25, 53.0 + (30.0 if i % 2 else 0.0), 0)
                 for i in range(24)]
        plan = plan_words(slots, bank)
        decide_shifts(plan, mix=0.5, mode="furthest")

        shifted = [p.raw_distance() for p in plan.placements if p.do_shift]
        kept = [p.raw_distance() for p in plan.placements if not p.do_shift]
        if shifted and kept:
            assert max(shifted) <= min(kept) + 1e-6

    def test_random_mode_is_reproducible(self, bank):
        a = plan_words(_slots(40), bank, seed=3)
        b = plan_words(_slots(40), bank, seed=3)
        decide_shifts(a, mix=0.5, mode="random", seed=3)
        decide_shifts(b, mix=0.5, mode="random", seed=3)
        assert [p.do_shift for p in a.placements] == [p.do_shift for p in b.placements]

    def test_empty_plan_is_safe(self):
        decide_shifts(Plan(), mix=0.5)


class TestMimicry:
    """Mimicry is the setting that means the same thing across songs.

    SHIFT_MIX counts units shifted; that is not what a listener hears. A song
    whose melody ranges far above the bank has most syllables octave-folded, so
    each shifted unit carries less of the original tune, and the song sounds
    unfitted even with every unit shifted. Mimicry measures the result instead.
    """

    def _far_slots(self, n, distance):
        return [Slot(i * 0.3, i * 0.3 + 0.25, 53.0 + distance, 0) for i in range(n)]

    def test_nothing_shifted_mimics_nothing(self, bank):
        plan = plan_words(_slots(40), bank)
        decide_shifts(plan, mix=0.0)
        assert mimicry(plan) == 0.0

    def test_a_close_song_can_mimic_almost_exactly(self, bank):
        plan = plan_words(self._far_slots(40, 2.0), bank)
        decide_shifts(plan, mix=1.0)
        assert mimicry(plan) > 0.95

    def test_a_far_song_is_capped_by_folding(self, bank):
        """Every unit shifted, yet it still cannot fully mimic the original."""
        plan = plan_words(self._far_slots(40, 26.0), bank)
        decide_shifts(plan, mix=1.0)
        assert mimicry(plan) == pytest.approx(config.FOLDED_FIT, abs=0.05)

    @pytest.mark.parametrize("target", [0.2, 0.4, 0.6])
    def test_target_is_reached_on_a_close_song(self, bank, target):
        plan = plan_words(self._far_slots(60, 2.0), bank)
        achieved = decide_by_mimicry(plan, target)
        assert achieved >= target - 0.02
        assert achieved <= target + 0.15

    def test_a_far_song_shifts_more_units_for_the_same_mimicry(self, bank):
        """The compensation that makes one number work across songs."""
        close = plan_words(self._far_slots(60, 2.0), bank)
        far = plan_words(self._far_slots(60, 26.0), bank)
        decide_by_mimicry(close, 0.4)
        decide_by_mimicry(far, 0.4)

        close_n = sum(1 for p in close.placements if p.do_shift)
        far_n = sum(1 for p in far.placements if p.do_shift)
        assert far_n > close_n, (
            f"far song shifted {far_n} units, close song {close_n} -- a folded "
            "song must shift more to carry the same amount of the tune"
        )

    def test_target_above_the_ceiling_shifts_everything(self, bank):
        plan = plan_words(self._far_slots(40, 26.0), bank)
        decide_by_mimicry(plan, 0.99)
        assert all(p.do_shift for p in plan.placements)

    def test_empty_plan_is_safe(self):
        assert mimicry(Plan()) == 0.0
        assert decide_by_mimicry(Plan(), 0.5) == 0.0


def test_report_on_an_empty_plan():
    assert "nothing placed" in report(Plan(), [])
