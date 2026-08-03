"""Stage 3: slot cleanup, unit placement, mixing."""

import numpy as np
import pytest

from luokkaretki import config
from luokkaretki.mapping import (
    Plan, Slot, Unit, clean_slots, group_phrases, mix, plan_words, render, report,
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


def test_report_on_an_empty_plan():
    assert "nothing placed" in report(Plan(), [])
