"""Density and climax rules: how much gets sung, and where the payoff lands.

These encode taste, but the failures were mechanical and all of them were
silent -- the output was simply wrong rather than erroring -- so each one gets
a test that would have caught it.
"""

import numpy as np
import pytest

from luokkaretki_generator import config
from luokkaretki_generator.mapping import (
    Slot, Unit, find_climaxes, group_phrases, plan_words,
)

SR = config.SAMPLE_RATE


def _unit(words, syllables, dur=0.5):
    n = int(dur * SR)
    tone = (0.3 * np.sin(2 * np.pi * 200 * np.arange(n) / SR)).astype(np.float32)
    return Unit(name="-".join(words) + ".wav", words=list(words),
                syllables=syllables, duration_s=dur, midi=53.0,
                audio=np.stack([tone, tone]))


@pytest.fixture
def bank():
    return [
        _unit(["paska"], 2, 0.45),
        _unit(["perse", "pillu"], 4, 0.9),
        _unit(["perse", "pillu", "perse"], 6, 1.4),
        _unit(["eee"], 1, 0.6),
        _unit(["eee", "paviaani"], 5, 1.7),
    ]


def _phrases(count, slots_each, gap=1.0, midi=60.0, rms=-20.0):
    """Distinct phrases, separated by gaps wider than PHRASE_GAP_S."""
    out, t = [], 0.0
    for _ in range(count):
        for _ in range(slots_each):
            out.append(Slot(t, t + 0.25, midi, 0, rms))
            t += 0.25
        t += gap
    return out


class TestPhraseFill:
    def test_full_fill_uses_every_phrase(self, bank, monkeypatch):
        monkeypatch.setattr(config, "PHRASE_FILL", 1.0)
        plan = plan_words(_phrases(10, 6), bank)
        assert plan.slots_dropped == 0

    def test_partial_fill_leaves_space(self, bank, monkeypatch):
        monkeypatch.setattr(config, "PHRASE_FILL", 0.5)
        plan = plan_words(_phrases(10, 6), bank)
        assert plan.slots_dropped > 0, "nothing was left instrumental"
        assert plan.slots_used > 0, "everything was left instrumental"


class TestShoutBudget:
    def test_shouts_are_rationed(self, bank, monkeypatch):
        """eee fits any leftover slot, so without a cap it wins every phrase."""
        monkeypatch.setattr(config, "PHRASE_FILL", 1.0)
        monkeypatch.setattr(config, "SHOUT_MAX_SHARE", 0.1)

        plan = plan_words(_phrases(20, 5), bank)
        shouts = sum(1 for p in plan.placements if p.unit.is_bare_shout)
        assert shouts <= 4, f"{shouts} bare shouts placed despite a 10% budget"


class TestClimaxes:
    def test_peaks_are_the_loud_high_phrases(self):
        groups = group_phrases(
            _phrases(4, 6, midi=55.0, rms=-30.0) + _phrases(1, 6, midi=75.0, rms=-8.0)
        )
        peaks = find_climaxes(groups, min_slots=1)
        assert len(groups) - 1 in peaks, "the loudest, highest phrase was not a peak"

    def test_phrases_too_short_for_the_payoff_are_not_peaks(self):
        """The bug that made paviaani never appear, in any render.

        Peaks were ranked on intensity alone, and the highest-scoring phrases
        were shorter than the shortest paviaani unit. It could not fit, so it
        was never placed, and nothing said so.
        """
        groups = group_phrases(_phrases(6, 3, midi=70.0, rms=-10.0))
        assert find_climaxes(groups, min_slots=5) == set()

    def test_paviaani_is_refused_away_from_a_peak(self, bank, monkeypatch):
        monkeypatch.setattr(config, "PHRASE_FILL", 1.0)
        monkeypatch.setattr(config, "CLIMAX_PHRASE_SHARE", 0.0)
        monkeypatch.setattr(config, "CLIMAX_WILDCARD_CHANCE", 0.0)

        plan = plan_words(_phrases(12, 6), bank)
        assert not any(p.unit.is_climax for p in plan.placements), (
            "paviaani was placed outside a peak"
        )

    def test_paviaani_lands_when_a_peak_can_hold_it(self, bank, monkeypatch):
        monkeypatch.setattr(config, "PHRASE_FILL", 1.0)
        monkeypatch.setattr(config, "CLIMAX_PHRASE_SHARE", 0.4)
        monkeypatch.setattr(config, "CLIMAX_USE_CHANCE", 1.0)

        slots = _phrases(4, 8, midi=55.0, rms=-30.0) + _phrases(2, 8, midi=75.0, rms=-8.0)
        plan = plan_words(slots, bank)
        assert any(p.unit.is_climax for p in plan.placements), (
            "no payoff placed even though a peak was long enough to hold one"
        )

    def test_climax_phrases_survive_thinning(self, bank, monkeypatch):
        """PHRASE_FILL used to drop the very phrases reserved for a climax."""
        monkeypatch.setattr(config, "PHRASE_FILL", 0.3)
        monkeypatch.setattr(config, "CLIMAX_PHRASE_SHARE", 0.2)
        monkeypatch.setattr(config, "CLIMAX_USE_CHANCE", 1.0)

        slots = _phrases(8, 8, midi=55.0, rms=-30.0) + _phrases(2, 8, midi=78.0, rms=-6.0)
        plan = plan_words(slots, bank)
        assert any(p.unit.is_climax for p in plan.placements)


class TestRawShouts:
    def test_a_bare_shout_is_never_resynthesised(self, bank, monkeypatch):
        """A vocoder removes the crack and attack that make it a shout."""
        from luokkaretki_generator.mapping import precompute_shifted

        monkeypatch.setattr(config, "PHRASE_FILL", 1.0)
        monkeypatch.setattr(config, "SHOUT_MAX_SHARE", 1.0)

        plan = plan_words(_phrases(12, 5), bank)
        cache = precompute_shifted(plan, SR)
        for i, p in enumerate(plan.placements):
            if p.unit.is_bare_shout:
                assert i not in cache, "a bare shout was sent through the vocoder"

    def test_a_shout_inside_a_word_keeps_its_own_pitch(self, bank):
        from luokkaretki_generator.mapping import build_segments

        unit = _unit(["eee", "paviaani"], 5, 1.7)
        unit.bounds_s = [0.4, 0.7, 1.0, 1.35]
        unit.syllable_midi = [53.0] * 5

        slots = [Slot(i * 0.3, i * 0.3 + 0.28, 70.0, 0) for i in range(5)]
        from luokkaretki_generator.mapping import Placement

        p = Placement(unit=unit, onset_s=0.0, slot_span_s=1.5, play_s=1.7,
                      n_slots=5, phrase=0, slots=slots)
        segments, _ = build_segments(p)

        assert segments[0].semitones == 0.0, "the shout syllable was pitch-shifted"
        assert any(s.semitones != 0.0 for s in segments[1:]), (
            "the word after the shout should still follow the melody"
        )
