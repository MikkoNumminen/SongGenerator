"""Stage 4b: who is singing when, and which bank takes each turn.

Everything below is plain arithmetic on times, exercised without the model
detect() needs: no test here calls detect() or imports speechbrain.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from factories import make_unit
from song_generator import config
from song_generator import turns as turns_mod
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
        # 5.0 is voice 1's, but voice 0's word from 4.9 is still sounding.
        assert onsets == [0.0, 2.0, 4.9, 7.0, 9.0]
        assert owners == [0, 0, 0, 1, 1]
        assert combined.slots_used == sum(p.n_slots for p in combined.placements)
        assert combined.slots_used == 5

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

VOCAL = np.zeros((2, 100), dtype=np.float32)


class TestLoadOrDetect:
    def test_matching_settings_return_the_cache_without_detecting(self, tmp_path, monkeypatch):
        cached_turns = [{"start_s": 0.0, "end_s": 5.0, "speaker": 0}]
        (tmp_path / "turns.json").write_text(json.dumps({
            "settings": settings(),
            "vocal": turns_mod.fingerprint(VOCAL),
            "turns": cached_turns,
        }), encoding="utf-8")

        def _boom(*a, **kw):
            raise AssertionError("detect() must not be called when the cache matches")

        monkeypatch.setattr("song_generator.turns.detect", _boom)

        got, cached, _ = load_or_detect(tmp_path, vocal=VOCAL, sr=16000, notes=[])

        assert cached is True
        assert got == [Turn(0.0, 5.0, 0)]

    def test_mismatched_settings_detect_and_rewrite_the_cache(self, tmp_path, monkeypatch):
        (tmp_path / "turns.json").write_text(json.dumps({
            "settings": {**settings(), "min_turn_s": -1.0},
            "turns": [{"start_s": 0.0, "end_s": 1.0, "speaker": 9}],
        }), encoding="utf-8")

        fresh = [Turn(0.0, 3.0, 0)]
        monkeypatch.setattr("song_generator.turns.detect", lambda *a, **kw: fresh)

        got, cached, _ = load_or_detect(tmp_path, vocal=VOCAL, sr=16000, notes=[])

        assert cached is False
        assert got == fresh
        saved = json.loads((tmp_path / "turns.json").read_text(encoding="utf-8"))
        assert saved["settings"] == settings()
        assert saved["turns"] == [{"start_s": 0.0, "end_s": 3.0, "speaker": 0}]
        assert not (tmp_path / ".turns.json.tmp").exists()

    def test_measuring_again_keeps_the_file_it_replaces(self, tmp_path, monkeypatch):
        """The file is editable by hand, so it is never simply written over."""
        edited = {"settings": {**settings(), "min_turn_s": -1.0},
                  "turns": [{"start_s": 0.0, "end_s": 1.0, "speaker": 9}]}
        (tmp_path / "turns.json").write_text(json.dumps(edited), encoding="utf-8")
        monkeypatch.setattr("song_generator.turns.detect",
                            lambda *a, **kw: [Turn(0.0, 3.0, 0)])
        _, _, previous = load_or_detect(tmp_path, vocal=VOCAL, sr=16000, notes=[])
        assert previous == tmp_path / "turns.previous.json"
        assert json.loads(previous.read_text(encoding="utf-8")) == edited

    def test_the_model_is_fetched_beside_the_song_s_work_directory(self, tmp_path, monkeypatch):
        """Not wherever the command happened to be run from."""
        seen = {}

        def detect(*a, model_dir=None, **kw):
            seen["dir"] = model_dir
            return [Turn(0.0, 1.0, 0)]

        monkeypatch.setattr("song_generator.turns.detect", detect)
        song = tmp_path / "work" / "song"
        song.mkdir(parents=True)
        load_or_detect(song, vocal=VOCAL, sr=16000, notes=[])
        assert seen["dir"] == tmp_path / "work" / "models" / "spkrec"

    def test_no_cache_file_detects(self, tmp_path, monkeypatch):
        fresh = [Turn(0.0, 2.0, 0)]
        monkeypatch.setattr("song_generator.turns.detect", lambda *a, **kw: fresh)

        got, cached, _ = load_or_detect(tmp_path, vocal=VOCAL, sr=16000, notes=[])

        assert cached is False
        assert got == fresh

    def test_different_notes_do_not_measure_again(self, tmp_path, monkeypatch):
        """The melody analysis is not bit-stable run to run, so keyed on the
        notes the turns were measured again on every render and every hand
        edit moved aside each time."""
        (tmp_path / "turns.json").write_text(json.dumps({
            "settings": settings(),
            "vocal": turns_mod.fingerprint(VOCAL),
            "turns": [{"start_s": 0.0, "end_s": 5.0, "speaker": 0}],
        }), encoding="utf-8")

        def _boom(*a, **kw):
            raise AssertionError("detect() must not run for a note jitter")

        monkeypatch.setattr("song_generator.turns.detect", _boom)
        got, cached, _ = load_or_detect(tmp_path, vocal=VOCAL, sr=16000,
                                        notes=[{"onset_s": 2.0, "dur_s": 0.5}])
        assert cached and got == [Turn(0.0, 5.0, 0)]

    def test_a_second_measurement_keeps_the_first_file_it_moved(self, tmp_path, monkeypatch):
        (tmp_path / "turns.json").write_text("{}", encoding="utf-8")
        (tmp_path / "turns.previous.json").write_text('{"hand": 1}', encoding="utf-8")
        monkeypatch.setattr("song_generator.turns.detect",
                            lambda *a, **kw: [Turn(0.0, 1.0, 0)])
        _, _, previous = load_or_detect(tmp_path, vocal=VOCAL, sr=16000, notes=[])
        assert previous == tmp_path / "turns.previous2.json"
        assert (tmp_path / "turns.previous.json").read_text(encoding="utf-8") == '{"hand": 1}'

    def test_a_different_vocal_stem_is_measured_again(self, tmp_path, monkeypatch):
        """Stems separated again land at the same paths; turns measured on
        the old stem must not be laid over the new one."""
        (tmp_path / "turns.json").write_text(json.dumps({
            "settings": settings(),
            "vocal": turns_mod.fingerprint(VOCAL),
            "turns": [{"start_s": 0.0, "end_s": 5.0, "speaker": 0}],
        }), encoding="utf-8")
        fresh = [Turn(0.0, 9.0, 1)]
        monkeypatch.setattr("song_generator.turns.detect", lambda *a, **kw: fresh)
        got, cached, _ = load_or_detect(tmp_path, vocal=VOCAL + 1.0, sr=16000, notes=[])
        assert cached is False
        assert got == fresh

    @pytest.mark.parametrize("turns", [
        [{"start_s": 0.0, "end_s": 5.0, "speaker": 0},
         {"start_s": 300.0, "end_s": 290.0, "speaker": 1}],
        [{"start_s": -1.0, "end_s": 5.0, "speaker": 0}],
        [{"start": 0.0, "end_s": 5.0, "speaker": 0}],
        [{"start_s": 0.0, "end_s": 5.0}],
        [{"start_s": "soon", "end_s": 5.0, "speaker": 0}],
        [{"start_s": 0.0, "end_s": 5.0, "speaker": 0},
         {"start_s": 4.0, "end_s": 9.0, "speaker": 1}],
        [],
    ])
    def test_a_hand_edit_that_cannot_be_used_is_refused_by_name(self, tmp_path, turns):
        """The file is documented as editable, so a typo in it is an error
        naming the file, never a traceback."""
        (tmp_path / "turns.json").write_text(json.dumps({
            "settings": settings(), "vocal": turns_mod.fingerprint(VOCAL),
            "turns": turns}), encoding="utf-8")
        with pytest.raises(TurnError, match="turns.json"):
            load_or_detect(tmp_path, vocal=VOCAL, sr=16000, notes=[])

    def test_an_extra_field_in_a_hand_edit_is_ignored(self, tmp_path):
        (tmp_path / "turns.json").write_text(json.dumps({
            "settings": settings(), "vocal": turns_mod.fingerprint(VOCAL),
            "turns": [{"start_s": 0.0, "end_s": 5.0, "speaker": 0, "note": "x"}]}),
            encoding="utf-8")
        got, cached, _ = load_or_detect(tmp_path, vocal=VOCAL, sr=16000, notes=[])
        assert cached and got == [Turn(0.0, 5.0, 0)]

    def test_invalid_json_raises_turn_error(self, tmp_path, monkeypatch):
        (tmp_path / "turns.json").write_text("{not json", encoding="utf-8")

        def _boom(*a, **kw):
            raise AssertionError("detect() must not be called on a corrupt cache")

        monkeypatch.setattr("song_generator.turns.detect", _boom)

        with pytest.raises(TurnError):
            load_or_detect(tmp_path, vocal=VOCAL, sr=16000, notes=[])


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


class TestReviewFixes:
    """Holes a review found in turn-taking, each pinned where it was closed."""

    def test_a_bank_named_twice_is_refused(self):
        """Turns go round the list, so a repeat puts one voice on two turns in
        a row wherever the list wraps."""
        a, b = list(config.BANKS)[:2]
        parser = build_parser()
        args = parser.parse_args(["song.mp4", "--voices", a, b, a])
        with pytest.raises(SystemExit):
            refuse_contradicting_voices(parser, args)

    def test_bank_named_beside_voices_is_refused(self):
        a, b, c = list(config.BANKS)[:3]
        parser = build_parser()
        args = parser.parse_args(["song.mp4", "--voices", a, b, "--bank", c])
        with pytest.raises(SystemExit):
            refuse_contradicting_voices(parser, args)

    def test_slot_totals_come_from_each_voice_s_own_grid(self):
        """Voices swallowing at different paces plan on different grids."""
        from song_generator.mapping import Slot
        turns_ = [Turn(0.0, 5.0, 0), Turn(5.0, 10.0, 1)]
        coarse = [Slot(t, t + 1.0, 60, 0) for t in range(10)]
        fine = [Slot(t / 2, t / 2 + 0.5, 60, 0) for t in range(20)]
        combined, _ = take_turns([Plan(), Plan()], turns_, [coarse, fine])
        assert combined.slots_total == 5 + 10

    def test_each_voice_is_judged_on_the_turns_it_sings(self, monkeypatch):
        """Coverage judged over the whole song was met at the first draw while
        the words that met it went to the other voice. Each build is told
        which moments its voice sings, so its own redraws judge those."""
        from song_generator import arrange, cli
        seen = {}

        def build(slots, units, level, seed, song="", bank="", bank_dir=None,
                  sings=None, **kw):
            seen[bank] = sings
            plan = Plan(placements=[_placement(1.0), _placement(6.0)])
            return plan, arrange.describe(plan, song, bank, level, seed), 1

        monkeypatch.setattr(arrange, "build", build)
        voices = [("a", None, "a", []), ("b", None, "b", [])]
        turns_ = [Turn(0.0, 5.0, 0), Turn(5.0, 10.0, 1)]
        plan, drawn, draws, owners = cli.arrange_voices(
            voices, {"a": [], "b": []}, turns_, "wild", 100, "song")
        assert seen["a"](1.0) and not seen["a"](6.0)
        assert seen["b"](6.0) and not seen["b"](1.0)
        assert draws == [1, 1]
        assert [p.onset_s for p in plan.placements] == [1.0, 6.0]
        assert owners == [0, 1]

    def test_each_voice_s_log_holds_what_that_voice_sang(self, monkeypatch):
        """Not its whole-song arrangement, half of which the other voice sang."""
        from song_generator import arrange, cli

        def build(slots, units, level, seed, song="", bank="", bank_dir=None,
                  sings=None, **kw):
            plan = Plan(placements=[_placement(1.0), _placement(6.0)])
            return plan, arrange.describe(plan, song, bank, level, seed), 1

        monkeypatch.setattr(arrange, "build", build)
        voices = [("a", None, "a", []), ("b", None, "b", [])]
        turns_ = [Turn(0.0, 5.0, 0), Turn(5.0, 10.0, 1)]
        _, drawn, _, _ = cli.arrange_voices(
            voices, {"a": [], "b": []}, turns_, "wild", 100, "song")
        assert [line.onset_s for line in drawn[0].lines] == [1.0]
        assert [line.onset_s for line in drawn[1].lines] == [6.0]

    def test_a_voice_that_owns_no_turn_is_not_planned(self, monkeypatch):
        """One turn for two voices: the second would be judged on nothing
        and spend every redraw on it."""
        from song_generator import arrange, cli
        built = []

        def build(slots, units, level, seed, song="", bank="", bank_dir=None,
                  sings=None, **kw):
            built.append(bank)
            plan = Plan(placements=[_placement(1.0)])
            return plan, arrange.describe(plan, song, bank, level, seed), 1

        monkeypatch.setattr(arrange, "build", build)
        voices = [("a", None, "a", []), ("b", None, "b", [])]
        plan, drawn, draws, owners = cli.arrange_voices(
            voices, {"a": [], "b": []}, [Turn(0.0, 10.0, 0)], "wild", 1, "song")
        assert built == ["a"]
        assert draws == [1, 0]
        assert owners == [0] and not drawn[1].lines

    def test_later_voices_are_asked_only_for_what_is_still_unsaid(self, monkeypatch):
        """Coverage is for the take: every voice asked for every word in its
        own turns made a voice with one short turn spend every draw."""
        from song_generator import arrange, cli
        word = list(config.WORD_SYLLABLES)[0]
        asked = {}

        def build(slots, units, level, seed, song="", bank="", bank_dir=None,
                  sings=None, wanted=None, pairing=True):
            asked[bank] = (wanted, pairing)
            at = 1.0 if bank == "long" else 8.0
            plan = Plan(placements=[Placement(
                unit=make_unit([word]), onset_s=at, slot_span_s=0.5,
                play_s=0.5, n_slots=1, phrase=0)])
            return plan, arrange.describe(plan, song, bank, level, seed), 1

        monkeypatch.setattr(arrange, "build", build)
        monkeypatch.setattr(arrange, "required_words", lambda: (word, "other"))
        # Turns 0 and 2 go to the first voice, 18 s; turn 1 to the second, 2 s.
        voices = [("long", None, "long", []), ("short", None, "short", [])]
        turns_ = [Turn(0.0, 7.0, 1), Turn(7.0, 9.0, 0), Turn(9.0, 20.0, 1)]
        cli.arrange_voices(voices, {"long": [], "short": []}, turns_, "wild",
                           1, "song")
        assert asked["long"][0] == {word, "other"}
        assert asked["short"][0] == {"other"}

    def test_one_voice_is_arrange_build_alone(self, monkeypatch):
        from song_generator import arrange, cli
        calls = []

        def build(slots, units, level, seed, song="", bank="", bank_dir=None,
                  sings=None, **kw):
            calls.append(sings)
            plan = Plan(placements=[_placement(1.0)])
            return plan, arrange.describe(plan, song, bank, level, seed), 3

        monkeypatch.setattr(arrange, "build", build)
        plan, drawn, draws, owners = cli.arrange_voices(
            [("a", None, "a", [])], {"a": []}, [], "wild", 100, "song")
        assert calls == [None] and draws == [3] and owners == [0]


class TestHandover:
    def test_the_incoming_voice_waits_for_the_outgoing_word_to_finish(self):
        """Voices planned apart can overlap at a handover; the incoming
        voice's words that start while the outgoing one sounds are dropped
        whole, and the first one after it is kept."""
        turns_ = [Turn(0.0, 5.0, 0), Turn(5.0, 10.0, 1)]
        long_word = Placement(unit=_unit(), onset_s=4.8, slot_span_s=1.5,
                              play_s=1.5, n_slots=1, phrase=0)
        plan0 = Plan(placements=[long_word])
        plan1 = Plan(placements=[_placement(5.0), _placement(5.1),
                                 _placement(5.3)])
        combined, owners = take_turns([plan0, plan1], turns_)
        assert [p.onset_s for p in combined.placements] == [4.8, 5.3]
        assert owners == [0, 1]

    def test_a_voice_s_own_words_are_not_held_back_by_itself(self):
        turns_ = [Turn(0.0, 10.0, 0), Turn(10.0, 20.0, 1)]
        plan0 = Plan(placements=[_placement(1.0), _placement(1.2)])
        combined, _ = take_turns([plan0, Plan()], turns_)
        assert [p.onset_s for p in combined.placements] == [1.0, 1.2]

    def test_used_never_exceeds_total(self):
        """A placement covering slots across a handover counts only the slots
        in its own voice's turns."""
        from song_generator.mapping import Slot
        turns_ = [Turn(0.0, 5.0, 0), Turn(5.0, 10.0, 1)]
        grid = [Slot(t, t + 1.0, 60, 0) for t in range(10)]
        spanning = Placement(unit=_unit(), onset_s=4.0, slot_span_s=2.0,
                             play_s=0.5, n_slots=2, phrase=0,
                             slots=[grid[4], grid[5]])
        combined, _ = take_turns([Plan(placements=[spanning]), Plan()],
                                 turns_, [grid, grid])
        assert combined.slots_used == 1
        assert combined.slots_used <= combined.slots_total


class TestSwallowRecordedInTheLog:
    def test_the_grid_survives_a_round_trip(self):
        from song_generator import arrange
        word = list(config.WORD_SYLLABLES)[0]
        arr = arrange.Arrangement("song", "bank", "wild", 7, [
            arrange.Line(0, 1.0, 1, [word])], swallow=2.4123, swallow_words=2.6)
        back = arrange.parse_text(arrange.render_text(arr))
        assert back.swallow == pytest.approx(2.4123)
        assert back.swallow_words == pytest.approx(2.6)

    def test_a_refused_replay_names_the_value_to_pass(self, tmp_path):
        """The log's figure is notes per syllable, which --swallow does not
        take; the message names the words the log was made with."""
        from song_generator import arrange, cli
        with pytest.raises(arrange.ArrangementError, match="--swallow 2.6"):
            cli.refuse_other_grid(3.06, None, tmp_path / "w.arr", 2.6)

    def test_a_log_without_it_reads_as_unswallowed(self):
        from song_generator import arrange
        word = list(config.WORD_SYLLABLES)[0]
        arr = arrange.Arrangement("song", "bank", "wild", 7, [
            arrange.Line(0, 1.0, 1, [word])])
        assert arrange.parse_text(arrange.render_text(arr)).swallow is None

    @pytest.mark.parametrize("logged, now", [(2.4, None), (None, 2.4), (2.4, 3.0)])
    def test_a_replay_on_another_grid_is_refused(self, logged, now, tmp_path):
        from song_generator import arrange, cli
        with pytest.raises(arrange.ArrangementError, match="--swallow"):
            cli.refuse_other_grid(logged, now, tmp_path / "w.arr")

    def test_an_unswallowed_log_says_to_leave_swallow_out(self, tmp_path):
        from song_generator import arrange, cli
        with pytest.raises(arrange.ArrangementError, match="without --swallow"):
            cli.refuse_other_grid(None, 2.4, tmp_path / "w.arr")

    @pytest.mark.parametrize("logged, now", [(None, None), (2.4, 2.40001)])
    def test_the_same_grid_replays(self, logged, now, tmp_path):
        from song_generator import cli
        cli.refuse_other_grid(logged, now, tmp_path / "w.arr")

    def test_the_grid_is_logged_in_full(self):
        """Rebuilt from a rounded figure, a phrase near a half could round
        the other way and move a slot."""
        from song_generator import arrange
        word = list(config.WORD_SYLLABLES)[0]
        per = 2.6 * 2.5 / 1.47
        arr = arrange.Arrangement("song", "bank", "wild", 7, [
            arrange.Line(0, 1.0, 1, [word])], swallow=per)
        assert arrange.parse_text(arrange.render_text(arr)).swallow == per

    @pytest.mark.parametrize("bad", ["2-", "inf", "1-inf", "nan"])
    def test_a_degenerate_swallow_is_refused(self, bad):
        with pytest.raises(SystemExit):
            parse("--swallow", bad)

    def test_the_swallow_tag_does_not_depend_on_argument_order(self):
        from song_generator import cli
        a, b = list(config.BANKS)[:2]
        one = parse("--voices", a, b, "--swallow", "2.6", f"{b}=2")
        two = parse("--voices", a, b, "--swallow", f"{b}=2", "2.6")
        assert cli.swallow_word(one) == cli.swallow_word(two)


class TestSoundingLength:
    def test_a_clip_with_no_pitch_to_move_to_sounds_whole(self):
        """A shifted render with no segments plays the clip whole, so that is
        how long it sounds, not play_s."""
        from song_generator import mapping
        unit = _unit()
        unit.syllable_midi = [None] * len(unit.syllable_midi or [None])
        unit.midi = None
        p = Placement(unit=unit, onset_s=0.0, slot_span_s=0.1, play_s=0.1,
                      n_slots=1, phrase=0, slots=[])
        assert mapping.sounding_s(p) == pytest.approx(unit.duration_s)
