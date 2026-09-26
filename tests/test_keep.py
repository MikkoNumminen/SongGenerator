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
    def test_the_word_bus_is_silent_inside_whatever_was_placed(self):
        """The last guarantee: a word ringing on from before a range, from
        any planner, is cut there."""
        sr = 1000
        bus = np.ones((2, 3 * sr), dtype=np.float32)
        out = keep.silence_words(bus, [(1.0, 2.0)], sr)
        assert out[:, int(1.5 * sr)].max() == 0.0
        assert out[:, int(0.5 * sr)].min() == 1.0


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

    def test_replaying_onto_kept_ranges_is_refused(self):
        with pytest.raises(SystemExit):
            cli.main(["song.mp4", "--keep-original", "0:24-0:30",
                      "--arrangement", "w.arr"])
