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
from pathlib import Path

import pytest
from test_arrange import _unit

from song_generator import arrange, audio_io, banks, config
from song_generator.mapping import Slot, group_phrases, load_bank, plan_sequence


def _spoken(n=3):
    """A bank cut with build_bank --raw: one variant per clip, in spoken order."""
    units = []
    for i in range(n):
        u = _unit(["delta"], name=f"raw_{i + 1:04d}.wav")
        u.variant = f"{i + 1:04d}"
        units.append(u)
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
        # 0.1s slots leave a 2-syllable placement 0.2s of span against a
        # 0.4s clip. A spoken word cut in half stops being the word, so the
        # unit keeps its full duration and overruns.
        plan = plan_sequence(_slots(dur=0.1), _spoken(3))
        first = plan.placements[0]
        assert first.slot_span_s == pytest.approx(0.2)
        assert first.play_s == pytest.approx(first.unit.duration_s)
        assert first.play_s > first.slot_span_s

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
# Output separated by bank
# ---------------------------------------------------------------------------

class TestOutputPerBank:
    def test_two_banks_for_one_song_write_to_different_folders(self):
        from song_generator.cli import output_path

        a = output_path(None, Path("input/song.mp4"), "curated")
        b = output_path(None, Path("input/song.mp4"), "muslimbank")
        assert a != b
        assert a.name == b.name == "song.mp3"
        assert a.parent.name == "curated"
        assert b.parent.name == "muslimbank"
        # Same song folder, so the levels of one song stay side by side.
        assert a.parent.parent == b.parent.parent
