"""--keep-original: stretches where the original vocal is left as it was.

Whistling came out of the separator in the vocal stem and was sung over with
words. These pin that a kept stretch gets no words, that the original comes
back only inside it, and that the flag says so in the filename.
"""

import numpy as np
import pytest

from song_generator import cli, keep
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

    @pytest.mark.parametrize("bad", ["", "0:30-0:24", "abc", "1:00", "0:10-0:10"])
    def test_nonsense_is_refused_rather_than_guessed(self, bad):
        with pytest.raises(keep.KeepError):
            keep.parse_ranges(bad)


class TestOutside:
    def test_a_slot_touching_a_kept_range_gets_no_word(self):
        """A word begun before the stretch would ring on into it."""
        slots = [Slot(0.0, 0.5, 60, 0), Slot(0.9, 1.1, 60, 0),
                 Slot(1.5, 1.8, 60, 0), Slot(2.1, 2.4, 60, 0)]
        kept, dropped = keep.outside(slots, [(1.0, 2.0)])
        assert [s.onset_s for s in kept] == [0.0, 2.1]
        assert dropped == 2

    def test_no_ranges_keeps_every_slot(self):
        slots = [Slot(0.0, 0.5, 60, 0)]
        assert keep.outside(slots, []) == (slots, 0)


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


class TestFlag:
    def test_off_unless_asked(self):
        assert parse().keep_original is None
        assert cli.variant_tag(parse()) is None

    def test_parses_into_ranges(self):
        assert parse("--keep-original", "0:24-0:30").keep_original == [(24.0, 30.0)]

    def test_a_bad_range_is_refused_by_the_parser(self):
        with pytest.raises(SystemExit):
            parse("--keep-original", "0:30-0:24")

    def test_the_filename_says_the_original_was_kept(self):
        """So a take with the whistling kept never replaces one without."""
        assert cli.variant_tag(parse("--keep-original", "0:24-0:30")) == "keep"
        assert cli.variant_tag(parse("--keep-original", "0:24-0:30",
                                     "--swallow", "2")) == "swallow2.keep"
