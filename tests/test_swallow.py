"""--swallow: one bank syllable sounding across several of the original's.

Rap gives a note to every syllable, and a bank syllable on each of them was
far too many words far too fast. These pin how notes are folded into longer
slots, and how the flag reaches the filename so a swallowed take never lands
on top of the plain one.
"""

import pytest

from factories import make_unit
from song_generator import cli, config
from song_generator.cli import build_parser
from song_generator.mapping import Slot, swallow_slots


def parse(*argv):
    return build_parser().parse_args(["song.mp4", *argv])


def notes(n, phrase=0, start=0.0, dur=0.15, gap=0.02, gaps=None):
    """n back-to-back notes, pitch rising by one semitone each."""
    out, at = [], start
    for i in range(n):
        out.append(Slot(at, at + dur, 50.0 + i, phrase))
        at += dur + (gaps[i] if gaps and i < len(gaps) else gap)
    return out


class TestSwallowSlots:
    def test_every_group_holds_lo_to_hi_notes_and_the_span_is_kept(self):
        slots = notes(20)
        out = swallow_slots(slots, 2, 4)
        assert out[0].onset_s == slots[0].onset_s
        assert out[-1].offset_s == slots[-1].offset_s
        assert 20 / 4 <= len(out) <= 20 / 2

    def test_a_group_ends_at_the_widest_gap_it_may_end_at(self):
        """The nearest thing to a word boundary in a stream of syllables."""
        gaps = [0.01, 0.01, 0.30, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01]
        slots = notes(10, gaps=gaps)
        out = swallow_slots(slots, 2, 4)
        assert out[0].offset_s == slots[2].offset_s

    def test_groups_never_cross_a_phrase(self):
        slots = notes(5, phrase=0) + notes(5, phrase=1, start=5.0)
        out = swallow_slots(slots, 2, 3)
        assert {s.phrase for s in out} == {0, 1}
        assert all(not (s.onset_s < 5.0 < s.offset_s) for s in out)

    def test_a_short_remainder_joins_the_group_before_it(self):
        out = swallow_slots(notes(7), 3, 3)
        assert [round(s.dur_s, 3) for s in out][-1] > 3 * 0.15

    def test_a_phrase_shorter_than_lo_becomes_one_group(self):
        out = swallow_slots(notes(2), 3, 4)
        assert len(out) == 1

    def test_the_group_takes_the_pitch_of_its_longest_note(self):
        """The one the rapper leant on."""
        slots = notes(3)
        slots[1].offset_s += 0.3
        out = swallow_slots(slots, 3, 3)
        assert out[0].midi == slots[1].midi

    def test_one_note_per_group_changes_nothing(self):
        slots = notes(6)
        out = swallow_slots(slots, 1, 1)
        assert [(s.onset_s, s.offset_s, s.midi) for s in out] == \
            [(s.onset_s, s.offset_s, s.midi) for s in slots]

    def test_an_impossible_range_is_refused(self):
        with pytest.raises(ValueError):
            swallow_slots(notes(4), 3, 2)


class TestSwallowFlag:
    def test_off_unless_asked(self):
        assert parse().swallow is None

    def test_a_range_and_a_single_count_both_parse(self):
        assert parse("--swallow", "2-4").swallow == (2, 4)
        assert parse("--swallow", "3").swallow == (3, 3)

    @pytest.mark.parametrize("bad", ["0-2", "4-2", "two", "2-x"])
    def test_nonsense_is_refused(self, bad):
        with pytest.raises(SystemExit):
            parse("--swallow", bad)

    def test_the_filename_says_it_was_swallowed(self):
        """A swallowed take must not replace the plain one."""
        assert cli.variant_tag(parse("--swallow", "2-4")) == "swallow2-4"
        assert cli.variant_tag(parse("--swallow", "3")) == "swallow3"
        assert cli.variant_tag(parse("--swallow", "2-4", "--mimicry", "0.6")) \
            == "mim0p60.swallow2-4"
        assert cli.variant_tag(parse()) is None

    def test_words_become_notes_through_the_bank_s_own_word_length(self):
        a, b, c = list(config.WORD_SYLLABLES)[:3]
        units = [make_unit([a]), make_unit([b, c])]
        per_word = sum(u.syllables for u in units) / 3
        lo, hi = cli.swallow_notes((2, 4), units)
        assert lo == round(2 * config.RAP_WORD_SYLLABLES / per_word)
        assert hi == round(4 * config.RAP_WORD_SYLLABLES / per_word)
