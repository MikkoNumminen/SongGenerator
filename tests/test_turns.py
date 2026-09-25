"""Stage 4b: who is singing when, and which bank takes each turn.

Everything below is plain arithmetic on times, exercised without the model
detect() needs: no test here calls detect() or imports speechbrain.
"""

from __future__ import annotations

import json

import pytest

from factories import make_unit
from song_generator import config
from song_generator.cli import (
    build_parser,
    output_bank_name,
    refuse_contradicting_voices,
)
from song_generator.mapping import Placement, Plan
from song_generator.turns import (
    TurnError,
    Turn,
    absorb_short,
    from_labels,
    load_or_detect,
    runs,
    settings,
    take_turns,
    to_turns,
    voice_of,
    voiced_windows,
)


def parse(*argv):
    return build_parser().parse_args(["song.mp4", *argv])


# ---------------------------------------------------------------------------
# runs()
# ---------------------------------------------------------------------------

class TestRuns:
    def test_consecutive_equal_labels_become_one_run(self):
        got = runs([0.0, 0.5, 1.0, 1.5], [0, 0, 0, 0])
        assert got == [[0.0, 1.5, 0]]

    def test_a_label_change_starts_a_new_run(self):
        got = runs([0.0, 0.5, 1.0, 1.5], [0, 0, 1, 1])
        assert got == [[0.0, 0.5, 0], [1.0, 1.5, 1]]

    def test_every_window_its_own_label_is_one_run_each(self):
        got = runs([0.0, 0.5, 1.0], [0, 1, 0])
        assert got == [[0.0, 0.0, 0], [0.5, 0.5, 1], [1.0, 1.0, 0]]


# ---------------------------------------------------------------------------
# absorb_short()
# ---------------------------------------------------------------------------

class TestAbsorbShort:
    """min_s=4.0, hop_s=0.5 throughout, matching TURN_MIN_S and TURN_HOP_S."""

    def test_a_blip_between_the_same_speaker_merges_the_three_into_one(self):
        rs = [[0.0, 5.0, 0], [5.5, 5.5, 1], [6.0, 11.0, 0]]

        got = absorb_short(rs, min_s=4.0, hop_s=0.5)

        assert got == [[0.0, 11.0, 0]]

    def test_a_blip_between_different_speakers_is_split_at_its_middle(self):
        rs = [[0.0, 5.0, 0], [5.5, 5.5, 1], [6.0, 11.0, 2]]

        got = absorb_short(rs, min_s=4.0, hop_s=0.5)

        assert got == [[0.0, 5.5, 0], [5.5, 11.0, 2]]

    def test_a_short_run_at_the_start_is_absorbed_into_its_only_neighbour(self):
        rs = [[0.0, 0.0, 1], [0.5, 10.0, 0]]

        got = absorb_short(rs, min_s=4.0, hop_s=0.5)

        assert got == [[0.0, 10.0, 0]]

    def test_a_short_run_at_the_end_is_absorbed_into_its_only_neighbour(self):
        rs = [[0.0, 10.0, 0], [10.5, 10.5, 1]]

        got = absorb_short(rs, min_s=4.0, hop_s=0.5)

        assert got == [[0.0, 10.5, 0]]

    def test_runs_at_or_above_min_s_are_left_untouched(self):
        rs = [[0.0, 3.5, 0], [4.0, 7.5, 1]]  # each is exactly 4.0s long

        got = absorb_short(rs, min_s=4.0, hop_s=0.5)

        assert got == rs

    def test_a_single_run_is_returned_as_is(self):
        rs = [[0.0, 5.0, 0]]

        assert absorb_short(rs, min_s=4.0, hop_s=0.5) == rs


# ---------------------------------------------------------------------------
# to_turns() / from_labels()
# ---------------------------------------------------------------------------

class TestToTurns:
    def test_the_handover_sits_halfway_between_the_two_runs(self):
        rs = [[0.0, 5.0, 0], [6.0, 11.0, 1]]

        got = to_turns(rs, duration_s=12.0)

        assert got[0].start_s == 0.0
        assert got[0].end_s == 5.5
        assert got[1].start_s == 5.5
        assert got[1].end_s == 12.0

    def test_no_gap_between_consecutive_turns(self):
        rs = [[0.0, 5.0, 0], [6.0, 11.0, 1], [12.0, 20.0, 2]]

        got = to_turns(rs, duration_s=25.0)

        for a, b in zip(got, got[1:]):
            assert a.end_s == b.start_s

    def test_the_first_turn_starts_at_zero_and_the_last_ends_at_the_duration(self):
        rs = [[1.0, 5.0, 0], [6.0, 9.0, 1]]

        got = to_turns(rs, duration_s=10.0)

        assert got[0].start_s == 0.0
        assert got[-1].end_s == 10.0

    def test_empty_runs_give_no_turns(self):
        assert to_turns([], duration_s=10.0) == []


class TestFromLabels:
    def test_labels_become_turns_covering_the_whole_song(self):
        centres = [0.0, 0.5, 1.0, 1.5, 6.0, 6.5, 7.0]
        labels = [0, 0, 0, 0, 1, 1, 1]

        got = from_labels(centres, labels, duration_s=8.0, min_s=4.0, hop_s=0.5)

        assert got[0].start_s == 0.0
        assert got[-1].end_s == 8.0
        for a, b in zip(got, got[1:]):
            assert a.end_s == b.start_s

    def test_empty_input_gives_no_turns(self):
        assert from_labels([], [], duration_s=10.0) == []


# ---------------------------------------------------------------------------
# voice_of()
# ---------------------------------------------------------------------------

class TestVoiceOf:
    def test_voices_alternate_turn_by_turn_with_two_voices(self):
        turns_ = [Turn(0.0, 5.0, 0), Turn(5.0, 10.0, 1), Turn(10.0, 15.0, 2)]

        assert voice_of(turns_, 2, 0.0) == 0
        assert voice_of(turns_, 2, 6.0) == 1
        assert voice_of(turns_, 2, 12.0) == 0

    def test_three_voices_cycle_through_all_three(self):
        turns_ = [Turn(0.0, 5.0, 0), Turn(5.0, 10.0, 1),
                  Turn(10.0, 15.0, 2), Turn(15.0, 20.0, 3)]

        assert voice_of(turns_, 3, 1.0) == 0
        assert voice_of(turns_, 3, 6.0) == 1
        assert voice_of(turns_, 3, 11.0) == 2
        assert voice_of(turns_, 3, 16.0) == 0

    def test_a_time_past_the_last_turn_belongs_to_the_last_turns_voice(self):
        turns_ = [Turn(0.0, 5.0, 0), Turn(5.0, 10.0, 1)]

        assert voice_of(turns_, 2, 100.0) == 1

    def test_the_boundary_time_belongs_to_the_next_turn(self):
        """t < end_s: the instant of a handover is already the next voice's."""
        turns_ = [Turn(0.0, 5.0, 0), Turn(5.0, 10.0, 1)]

        assert voice_of(turns_, 2, 5.0) == 1

    def test_no_turns_at_all_defaults_to_voice_zero(self):
        assert voice_of([], 2, 3.0) == 0


# ---------------------------------------------------------------------------
# take_turns()
# ---------------------------------------------------------------------------

def _unit():
    return make_unit(["bravo"], per_word=0.4)


def _placement(onset_s, n_slots=1):
    return Placement(unit=_unit(), onset_s=onset_s, slot_span_s=0.5,
                     play_s=0.5, n_slots=n_slots, phrase=0)


class TestTakeTurns:
    def test_each_kept_placement_belongs_to_the_voice_owning_its_onset(self):
        """Two voices, each arranged over the whole song, so each already has
        a placement everywhere; take_turns keeps only the one whose voice
        owns the moment it starts in."""
        turns_ = [Turn(0.0, 5.0, 0), Turn(5.0, 10.0, 1)]
        plan0 = Plan(placements=[_placement(0.0), _placement(2.0),
                                 _placement(4.9), _placement(6.0)])
        plan1 = Plan(placements=[_placement(1.0), _placement(3.0),
                                 _placement(5.0), _placement(7.0),
                                 _placement(9.0)])

        combined, owners = take_turns([plan0, plan1], turns_)

        onsets = [p.onset_s for p in combined.placements]
        assert onsets == sorted(onsets)
        assert onsets == [0.0, 2.0, 4.9, 5.0, 7.0, 9.0]
        assert owners == [0, 0, 0, 1, 1, 1]
        assert combined.slots_used == sum(p.n_slots for p in combined.placements)
        assert combined.slots_used == 6

    def test_a_placement_just_before_a_handover_is_kept_whole_by_the_earlier_voice(self):
        """Not dropped for straddling the boundary, and not duplicated by the
        other voice: ownership is decided by where the placement starts."""
        turns_ = [Turn(0.0, 5.0, 0), Turn(5.0, 10.0, 1)]
        near_handover = _placement(4.9)
        plan0 = Plan(placements=[near_handover])
        plan1 = Plan(placements=[_placement(4.9)])  # would-be duplicate, wrong voice

        combined, owners = take_turns([plan0, plan1], turns_)

        assert len(combined.placements) == 1
        assert combined.placements[0] is near_handover
        assert owners == [0]

    def test_owners_lines_up_positionally_with_placements(self):
        turns_ = [Turn(0.0, 5.0, 0), Turn(5.0, 10.0, 1)]
        plan0 = Plan(placements=[_placement(0.0)])
        plan1 = Plan(placements=[_placement(6.0)])

        combined, owners = take_turns([plan0, plan1], turns_)

        assert len(owners) == len(combined.placements)
        for placement, owner in zip(combined.placements, owners):
            assert (owner == 0) == (placement.onset_s < 5.0)


# ---------------------------------------------------------------------------
# voiced_windows()
# ---------------------------------------------------------------------------

class TestVoicedWindows:
    def test_windows_mostly_outside_notes_are_skipped(self, monkeypatch):
        monkeypatch.setattr(config, "TURN_WINDOW_S", 1.0)
        monkeypatch.setattr(config, "TURN_HOP_S", 1.0)
        monkeypatch.setattr(config, "TURN_MIN_VOICED", 0.4)

        # A note only in [0, 1): the window starting at 1.0 has nothing sung
        # in it and must be skipped; the one at 0.0 is fully inside the note.
        notes = [{"onset_s": 0.0, "dur_s": 1.0}]

        got = voiced_windows(notes, duration_s=3.0)

        assert 0.0 in got
        assert 1.0 not in got

    def test_window_starts_step_by_turn_hop_s(self, monkeypatch):
        monkeypatch.setattr(config, "TURN_WINDOW_S", 1.0)
        monkeypatch.setattr(config, "TURN_HOP_S", 0.5)
        monkeypatch.setattr(config, "TURN_MIN_VOICED", 0.0)

        notes = [{"onset_s": 0.0, "dur_s": 3.0}]

        got = voiced_windows(notes, duration_s=3.0)

        assert got == [0.0, 0.5, 1.0, 1.5, 2.0]


# ---------------------------------------------------------------------------
# load_or_detect() cache behaviour
# ---------------------------------------------------------------------------

class TestLoadOrDetect:
    def test_matching_settings_return_the_cache_without_detecting(self, tmp_path, monkeypatch):
        cached_turns = [{"start_s": 0.0, "end_s": 5.0, "speaker": 0}]
        (tmp_path / "turns.json").write_text(json.dumps({
            "settings": settings(),
            "turns": cached_turns,
        }), encoding="utf-8")

        def _boom(*a, **kw):
            raise AssertionError("detect() must not be called when the cache matches")

        monkeypatch.setattr("song_generator.turns.detect", _boom)

        got, cached = load_or_detect(tmp_path, vocal=None, sr=16000, notes=[])

        assert cached is True
        assert got == [Turn(0.0, 5.0, 0)]

    def test_mismatched_settings_detect_and_rewrite_the_cache(self, tmp_path, monkeypatch):
        (tmp_path / "turns.json").write_text(json.dumps({
            "settings": {**settings(), "min_turn_s": -1.0},
            "turns": [{"start_s": 0.0, "end_s": 1.0, "speaker": 9}],
        }), encoding="utf-8")

        fresh = [Turn(0.0, 3.0, 0)]
        monkeypatch.setattr("song_generator.turns.detect", lambda *a, **kw: fresh)

        got, cached = load_or_detect(tmp_path, vocal=None, sr=16000, notes=[])

        assert cached is False
        assert got == fresh
        saved = json.loads((tmp_path / "turns.json").read_text(encoding="utf-8"))
        assert saved["settings"] == settings()
        assert saved["turns"] == [{"start_s": 0.0, "end_s": 3.0, "speaker": 0}]
        assert not (tmp_path / ".turns.json.tmp").exists()

    def test_no_cache_file_detects(self, tmp_path, monkeypatch):
        fresh = [Turn(0.0, 2.0, 0)]
        monkeypatch.setattr("song_generator.turns.detect", lambda *a, **kw: fresh)

        got, cached = load_or_detect(tmp_path, vocal=None, sr=16000, notes=[])

        assert cached is False
        assert got == fresh

    def test_invalid_json_raises_turn_error(self, tmp_path, monkeypatch):
        (tmp_path / "turns.json").write_text("{not json", encoding="utf-8")

        def _boom(*a, **kw):
            raise AssertionError("detect() must not be called on a corrupt cache")

        monkeypatch.setattr("song_generator.turns.detect", _boom)

        with pytest.raises(TurnError):
            load_or_detect(tmp_path, vocal=None, sr=16000, notes=[])


# ---------------------------------------------------------------------------
# CLI: --voices
# ---------------------------------------------------------------------------

class TestVoicesFlag:
    def test_known_bank_names_are_accepted(self):
        a, b = list(config.BANKS)[:2]

        assert parse("--voices", a, b).voices == [a, b]

    def test_an_unknown_bank_name_is_refused(self):
        with pytest.raises(SystemExit):
            parse("--voices", "nosuchbank", "alsonot")

    def test_voices_is_none_by_default(self):
        assert parse().voices is None


class TestRefuseContradictingVoices:
    def test_a_single_voice_is_refused(self):
        parser = build_parser()
        args = parser.parse_args(["song.mp4", "--voices", list(config.BANKS)[0]])

        with pytest.raises(SystemExit):
            refuse_contradicting_voices(parser, args)

    def test_two_identical_voices_are_refused(self):
        parser = build_parser()
        bank = list(config.BANKS)[0]
        args = parser.parse_args(["song.mp4", "--voices", bank, bank])

        with pytest.raises(SystemExit):
            refuse_contradicting_voices(parser, args)

    def test_voices_combined_with_words_dir_is_refused(self):
        a, b = list(config.BANKS)[:2]
        parser = build_parser()
        args = parser.parse_args(["song.mp4", "--voices", a, b,
                                  "--words-dir", "some/dir"])

        with pytest.raises(SystemExit):
            refuse_contradicting_voices(parser, args)

    def test_voices_combined_with_arrangement_is_refused(self):
        a, b = list(config.BANKS)[:2]
        parser = build_parser()
        args = parser.parse_args(["song.mp4", "--voices", a, b,
                                  "--arrangement", "w.arr"])

        with pytest.raises(SystemExit):
            refuse_contradicting_voices(parser, args)

    def test_no_voices_passes(self):
        parser = build_parser()
        args = parser.parse_args(["song.mp4"])

        refuse_contradicting_voices(parser, args)  # must not raise


class TestOutputBankName:
    def test_several_voices_are_joined_with_a_plus(self):
        a, b = list(config.BANKS)[:2]

        assert output_bank_name(parse("--voices", a, b)) == f"{a}+{b}"

    def test_words_dir_names_the_directory_itself(self):
        assert output_bank_name(parse("--words-dir", "some/dir")) == "dir"

    def test_otherwise_it_falls_back_to_bank(self):
        got = output_bank_name(parse())
        assert got == config.DEFAULT_BANK
