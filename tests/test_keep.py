"""--keep-original: stretches where the original vocal is left as it was.

Whistling came out of the separator in the vocal stem and was sung over with
words. These pin that a kept stretch gets no words by any route, that the
original comes back only inside it and whole, that the band keeps its level,
and that the flag says which piece it made in the filename.
"""

import numpy as np
import pytest

from song_generator import cli, config, keep, mapping
from song_generator.cli import build_parser
from song_generator.mapping import Slot


def parse(*argv):
    return build_parser().parse_args(["song.mp4", *argv])


class TestParseRanges:
    def test_minutes_and_seconds_or_plain_seconds(self):
        assert keep.parse_ranges("0:24-0:30, 63-69.5") == [(24.0, 30.0), (63.0, 69.5)]

    def test_overlapping_ranges_merge_and_sort(self):
        assert keep.parse_ranges("1:00-1:10,0:10-0:20,1:05-1:15") == \
            [(10.0, 20.0), (60.0, 75.0)]

    @pytest.mark.parametrize("bad", ["", "0:30-0:24", "abc", "1:00", "0:10-0:10",
                                     "1:75-2:00", "0:10-0:20-0:30", "-0:05-0:10"])
    def test_nonsense_is_refused_rather_than_guessed(self, bad):
        with pytest.raises(keep.KeepError):
            keep.parse_ranges(bad)


class TestOutside:
    def test_a_slot_touching_a_kept_range_gets_no_word(self):
        """A word begun before the stretch would ring on into it."""
        slots = [Slot(0.0, 0.5, 60, 0), Slot(0.9, 1.1, 60, 0),
                 Slot(1.5, 1.8, 60, 0), Slot(2.1, 2.4, 60, 0)]
        kept, dropped, _ = keep.outside(slots, [(1.0, 2.0)])
        assert [s.onset_s for s in kept] == [0.0, 2.1]
        assert dropped == 2

    def test_a_straddling_slot_widens_the_range_so_nothing_is_a_hole(self):
        """Its note is put back from where the singer started it."""
        slots = [Slot(0.9, 1.1, 60, 0), Slot(1.9, 2.3, 60, 0)]
        _, _, widened = keep.outside(slots, [(1.0, 2.0)])
        assert widened == [(0.9, 2.3)]

    def test_no_planner_can_join_the_notes_either_side_of_a_range(self):
        """The slots after a range start a new phrase, so swallowing and
        reciting cannot bridge it."""
        slots = [Slot(t, t + 0.2, 60, 0) for t in (0.0, 0.3, 0.6, 2.2, 2.5, 2.8)]
        kept, _, _ = keep.outside(slots, [(1.0, 2.0)])
        assert [s.phrase for s in kept] == [0, 0, 0, 1, 1, 1]
        swallowed = mapping.swallow_slots(kept, 6.0)
        assert all(not (s.onset_s < 2.0 and s.offset_s > 1.0) for s in swallowed)

    def test_existing_phrase_breaks_are_kept(self):
        slots = [Slot(0.0, 0.2, 60, 0), Slot(0.3, 0.5, 60, 1)]
        kept, _, _ = keep.outside(slots, [(5.0, 6.0)])
        assert [s.phrase for s in kept] == [0, 1]

    def test_the_slots_given_are_not_changed(self):
        slots = [Slot(2.2, 2.4, 60, 0)]
        keep.outside(slots, [(1.0, 2.0)])
        assert slots[0].phrase == 0

    def test_no_ranges_keeps_every_slot(self):
        slots = [Slot(0.0, 0.5, 60, 3)]
        kept, dropped, widened = keep.outside(slots, [])
        assert dropped == 0 and widened == []
        assert [(s.onset_s, s.offset_s) for s in kept] == [(0.0, 0.5)]


class TestWithOriginal:
    SR = 1000

    def test_the_original_comes_back_only_inside_the_range(self):
        n = 3 * self.SR
        bed = np.zeros((2, n), dtype=np.float32)
        vocal = np.ones((2, n), dtype=np.float32)
        out = keep.with_original(bed, vocal, [(1.0, 2.0)], sr=self.SR)
        assert out[:, :self.SR].max() == 0.0
        assert out[:, 2 * self.SR:].max() == 0.0
        assert out[:, int(1.5 * self.SR)].min() == 1.0

    def test_the_edges_fade_rather_than_click(self):
        m = keep.mask([(1.0, 2.0)], 3 * self.SR, self.SR, fade_s=0.1)
        assert m[self.SR] == 0.0
        assert 0.0 < m[self.SR + 50] < 1.0
        assert m[self.SR + 100] == 1.0

    def test_the_band_is_untouched_outside(self):
        n = 3 * self.SR
        bed = np.full((2, n), 0.25, dtype=np.float32)
        out = keep.with_original(bed, np.ones((2, n), np.float32),
                                 [(1.0, 2.0)], sr=self.SR)
        assert np.allclose(out[:, :self.SR], 0.25)

    def test_a_short_vocal_stem_does_not_shorten_the_song(self):
        bed = np.zeros((2, 3 * self.SR), dtype=np.float32)
        vocal = np.ones((2, 2 * self.SR), dtype=np.float32)
        out = keep.with_original(bed, vocal, [(1.5, 3.0)], sr=self.SR)
        assert out.shape == bed.shape


class TestNoWordsInsideARange:
    def test_the_gate_closes_inside_and_stays_open_outside(self):
        """The last guarantee, after the planner has already kept words out."""
        sr = 1000
        bus = np.ones((2, 3 * sr), dtype=np.float32)
        out = bus * keep.word_gate([(1.0, 2.0)], bus.shape[1], sr)
        assert out[:, int(1.5 * sr)].max() == 0.0
        assert out[:, int(0.5 * sr)].min() == 1.0

    def test_a_word_ringing_into_a_range_is_found_by_what_it_sounds(self):
        """The last word of a phrase plays past its slot; measured by what
        the render plays, it reaches the range and is left out whole."""
        from factories import make_unit
        from song_generator.mapping import Placement
        word = list(config.WORD_SYLLABLES)[0]
        slot = Slot(0.5, 0.7, 60, 0)
        ringing = Placement(unit=make_unit([word], per_word=0.8), onset_s=0.5,
                            slot_span_s=0.2, play_s=0.8, n_slots=1, phrase=0,
                            slots=[slot], split=False, target_s=0.8)
        assert keep.rings_into(ringing, [(1.0, 2.0)])
        assert not keep.rings_into(ringing, [(1.5, 2.0)])

    def test_the_first_slot_after_a_range_is_a_hard_break(self):
        slots = [Slot(0.0, 0.2, 60, 0), Slot(0.9, 1.05, 60, 0),
                 Slot(1.25, 1.4, 60, 0)]
        kept, _, _ = keep.outside(slots, [(1.0, 1.2)])
        assert [s.hard_break for s in kept] == [False, True]

    def test_phrase_grouping_respects_a_hard_break_under_the_phrase_gap(self):
        """group_phrases rebuilds phrases from gaps; a range narrower than
        PHRASE_GAP_S would otherwise vanish into one phrase again."""
        a = Slot(0.0, 0.2, 60, 0)
        b = Slot(0.25, 0.4, 60, 0, hard_break=True)
        assert len(mapping.group_phrases([a, b])) == 2
        assert len(mapping.group_phrases([Slot(0.0, 0.2, 60, 0),
                                          Slot(0.25, 0.4, 60, 0)])) == 1

    def test_swallowing_carries_the_break_to_the_group_it_starts(self):
        slots = [Slot(t, t + 0.1, 60, 0) for t in (0.0, 0.2, 0.4)]
        slots += [Slot(t, t + 0.1, 60, 1, hard_break=(t == 0.6))
                  for t in (0.6, 0.8, 1.0)]
        out = mapping.swallow_slots(slots, 3.0)
        assert [s.hard_break for s in out] == [False, True]


class TestLevel:
    def test_the_band_keeps_its_level_however_much_vocal_is_kept(self, monkeypatch):
        """Levelled as a whole, a bed holding a minute of the original turned
        the band down everywhere, so the words sat louder over the verses."""
        from song_generator import detect
        monkeypatch.setattr(detect, "integrated_lufs",
                            lambda audio, sr: 20 * np.log10(np.abs(audio).mean() + 1e-12))
        n = 1000
        band = np.full((2, n), 0.1, dtype=np.float32)
        bed = band.copy()
        bed[:, :500] += 0.05  # under the peak ceiling, which would scale all
        words = np.zeros((2, n), dtype=np.float32)
        plain = mapping.mix(words, band, sr=1000)
        kept = mapping.mix(words, bed, sr=1000, level_from=band)
        assert np.allclose(kept[:, 600:], plain[:, 600:])


class TestPastTheEnd:
    def test_a_range_after_the_song_ends_is_refused(self):
        with pytest.raises(keep.KeepError, match="after the song ends"):
            keep.refuse_past_the_end([(10.0, 20.0), (624.0, 630.0)], 200.0)

    def test_a_range_running_past_the_end_is_allowed(self):
        keep.refuse_past_the_end([(190.0, 210.0)], 200.0)


class TestFlag:
    def test_off_unless_asked(self):
        assert parse().keep_original is None
        assert cli.variant_tag(parse()) is None

    def test_parses_into_ranges(self):
        assert parse("--keep-original", "0:24-0:30").keep_original == [(24.0, 30.0)]

    def test_a_bad_range_is_refused_by_the_parser(self):
        with pytest.raises(SystemExit):
            parse("--keep-original", "0:30-0:24")

    def test_the_filename_names_the_piece(self):
        """Different ranges are a different piece: the chorus piece must not
        replace the whistling piece. The same ranges, however typed, are the
        same piece."""
        one = cli.variant_tag(parse("--keep-original", "0:24-0:30"))
        same = cli.variant_tag(parse("--keep-original", "24-30"))
        other = cli.variant_tag(parse("--keep-original", "0:24-0:30,1:03-1:09"))
        assert one.startswith("keep") and one == same and one != other
        tagged = cli.variant_tag(parse("--keep-original", "0:24-0:30",
                                       "--swallow", "2"))
        assert tagged == f"swallow2.{one}"

    def test_keeping_with_no_words_is_refused(self):
        """--no-words writes the band alone, so there is nothing to keep in."""
        with pytest.raises(SystemExit):
            cli.main(["song.mp4", "--keep-original", "0:24-0:30", "--no-words"])


class TestReplay:
    def test_the_log_records_the_ranges_and_reads_them_back(self):
        """They decide which slots existed, so a replay brings them back."""
        from song_generator import arrange
        word = list(config.WORD_SYLLABLES)[0]
        arr = arrange.Arrangement("song", "bank", "wild", 7, [
            arrange.Line(0, 1.0, 1, [word])], keep=[(24.0, 30.0), (63.0, 69.5)])
        back = arrange.parse_text(arrange.render_text(arr))
        assert back.keep == [(24.0, 30.0), (63.0, 69.5)]

    def test_a_log_without_ranges_reads_as_none(self):
        from song_generator import arrange
        word = list(config.WORD_SYLLABLES)[0]
        arr = arrange.Arrangement("song", "bank", "wild", 7, [
            arrange.Line(0, 1.0, 1, [word])])
        assert arrange.parse_text(arrange.render_text(arr)).keep is None

    def test_unreadable_ranges_in_a_log_are_refused(self):
        from song_generator import arrange
        word = list(config.WORD_SYLLABLES)[0]
        text = arrange.render_text(arrange.Arrangement(
            "song", "bank", "wild", 7, [arrange.Line(0, 1.0, 1, [word])]))
        text = text.replace("# Words available", "#   keep    24-soon\n# Words available")
        with pytest.raises(arrange.ArrangementError, match="kept ranges"):
            arrange.parse_text(text)


class TestThirdReview:
    def test_ranges_closer_than_their_fades_are_joined(self):
        """Faded separately, two ranges 50 ms apart dipped to neither the
        original nor a word between them."""
        _, _, widened = keep.outside([], [(60.0, 69.0), (69.05, 78.0)])
        assert widened == [(60.0, 78.0)]

    def test_a_slot_taken_in_by_the_widening_is_dropped_too(self):
        """B does not touch the range as given, but lies inside the stretch
        the straddling slot A widened it to."""
        a = Slot(0.9, 1.1, 60, 0)
        b = Slot(0.85, 0.95, 60, 0)
        kept, dropped, widened = keep.outside([b, a], [(1.0, 2.0)])
        assert kept == [] and dropped == 2
        assert widened == [(0.85, 2.0)]

    def test_the_log_keeps_the_ranges_exactly(self):
        """Rounded, an edge could move past a slot's end and a replay would
        cut a different set of slots than the take."""
        from song_generator import arrange
        word = list(config.WORD_SYLLABLES)[0]
        arr = arrange.Arrangement("song", "bank", "wild", 7, [
            arrange.Line(0, 1.0, 1, [word])], keep=[(24.004, 30.0)])
        assert arrange.parse_text(arrange.render_text(arr)).keep == [(24.004, 30.0)]

    def test_words_that_ring_in_are_not_counted_as_sung(self, monkeypatch):
        """Dropped after planning, their slots came off the report too."""
        from factories import make_unit
        from song_generator import arrange
        from song_generator.mapping import Placement, Plan
        word = list(config.WORD_SYLLABLES)[0]

        def placement(at, length):
            return Placement(unit=make_unit([word], per_word=length), onset_s=at,
                             slot_span_s=length, play_s=length, n_slots=2,
                             phrase=0, split=False, target_s=length)

        def build(slots, units, level, seed, song="", bank="", bank_dir=None,
                  sings=None, **kw):
            plan = Plan(placements=[placement(0.0, 0.5), placement(0.8, 0.6)],
                        slots_used=4, slots_total=10)
            return plan, arrange.describe(plan, song, bank, level, seed), 1

        monkeypatch.setattr(arrange, "build", build)
        plan, _, _, _ = cli.arrange_voices(
            [("a", None, "a", [])], {"a": []}, [], "wild", 1, "song",
            kept=[(1.0, 2.0)])
        assert [p.onset_s for p in plan.placements] == [0.0]
        assert plan.slots_used == 2


class TestFourthReview:
    def _log(self, header):
        from song_generator import arrange
        word = list(config.WORD_SYLLABLES)[0]
        text = arrange.render_text(arrange.Arrangement(
            "song", "bank", "wild", 7, [arrange.Line(0, 1.0, 1, [word])]))
        return text.replace("# Words available",
                            f"#   keep    {header}\n# Words available")

    @pytest.mark.parametrize("header", ["30-24", "nan-nan", "inf-inf", "24-"])
    def test_a_hand_edited_header_is_held_to_the_same_rules(self, header):
        """Reversed, not a number, or unfinished: refused by name, never a
        take tagged as kept with words over the stretch, never a traceback."""
        from song_generator import arrange
        with pytest.raises(arrange.ArrangementError, match="kept ranges"):
            arrange.parse_text(self._log(header))

    def test_ranges_out_of_order_in_a_log_are_sorted_and_merged(self):
        from song_generator import arrange
        assert arrange.parse_text(self._log("63-69,24-30,65-70")).keep ==             [(24.0, 30.0), (63.0, 70.0)]

    def test_a_tiny_edge_survives_the_round_trip(self):
        """repr wrote 1e-05, which split on its own minus sign."""
        from song_generator import arrange
        word = list(config.WORD_SYLLABLES)[0]
        arr = arrange.Arrangement("song", "bank", "wild", 7, [
            arrange.Line(0, 1.0, 1, [word])], keep=[(0.00001, 30.0)])
        assert arrange.parse_text(arrange.render_text(arr)).keep == [(0.00001, 30.0)]

    def test_ranges_that_cut_different_slots_get_different_names(self):
        assert keep.tag([(24.001, 30.0)]) != keep.tag([(24.004, 30.0)])
