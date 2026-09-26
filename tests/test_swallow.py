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
    def test_the_pace_asked_for_is_the_pace_delivered(self):
        """A phrase of N notes becomes round(N / per_syllable) slots, so a
        quarter fewer notes per syllable is a quarter more syllables."""
        slots = notes(60)
        assert len(swallow_slots(slots, 3.0)) == 20
        assert len(swallow_slots(slots, 2.4)) == 25

    def test_the_whole_phrase_is_still_covered(self):
        slots = notes(20)
        out = swallow_slots(slots, 3.0)
        assert out[0].onset_s == slots[0].onset_s
        assert out[-1].offset_s == slots[-1].offset_s
        assert all(a.offset_s <= b.onset_s for a, b in zip(out, out[1:]))

    def test_a_boundary_moves_to_a_wider_gap_within_reach(self):
        """The nearest thing to a word boundary in a stream of syllables."""
        gaps = [0.01] * 9
        gaps[3] = 0.30          # the gap after the fourth note
        slots = notes(10, gaps=gaps)
        out = swallow_slots(slots, 10 / 3)   # even split would end at 3
        assert out[0].offset_s == slots[3].offset_s

    def test_a_boundary_does_not_travel_further_than_it_may(self):
        gaps = [0.01] * 11
        gaps[8] = 0.30
        slots = notes(12, gaps=gaps)
        out = swallow_slots(slots, 4.0)
        assert out[0].offset_s != slots[8].offset_s

    def test_groups_never_cross_a_phrase(self):
        slots = notes(5, phrase=0) + notes(5, phrase=1, start=5.0)
        out = swallow_slots(slots, 2.5)
        assert {s.phrase for s in out} == {0, 1}
        assert all(not (s.onset_s < 5.0 < s.offset_s) for s in out)

    def test_a_phrase_shorter_than_one_group_is_one_slot(self):
        assert len(swallow_slots(notes(2), 4.0)) == 1

    def test_the_group_takes_the_pitch_of_its_longest_note(self):
        """The one the rapper leant on."""
        slots = notes(3)
        slots[1].offset_s += 0.3
        out = swallow_slots(slots, 3.0)
        assert out[0].midi == slots[1].midi

    def test_one_note_per_syllable_changes_nothing(self):
        slots = notes(6)
        out = swallow_slots(slots, 1.0)
        assert [(s.onset_s, s.offset_s, s.midi) for s in out] ==             [(s.onset_s, s.offset_s, s.midi) for s in slots]

    def test_under_one_note_is_refused(self):
        with pytest.raises(ValueError):
            swallow_slots(notes(4), 0.5)


def voices_pair():
    return sorted(config.BANKS)[:2]


class TestSwallowFlag:
    def test_off_unless_asked(self):
        assert parse().swallow is None
        assert cli.swallow_words(parse(), "anybody") is None

    def test_a_range_a_count_and_a_voice_s_own_all_parse(self):
        assert parse("--swallow", "2-4").swallow == [(None, 2.0, 4.0)]
        assert parse("--swallow", "3").swallow == [(None, 3.0, 3.0)]
        assert parse("--swallow", "2-4", "abc=2.4").swallow ==             [(None, 2.0, 4.0), ("abc", 2.4, 2.4)]

    @pytest.mark.parametrize("bad", ["0-2", "4-2", "two", "2-x", "v=", "v=0"])
    def test_nonsense_is_refused(self, bad):
        with pytest.raises(SystemExit):
            parse("--swallow", bad)

    def test_a_voice_s_own_pace_wins_over_everybody_s(self):
        a, b = voices_pair()
        args = parse("--voices", a, b, "--swallow", "2-4", f"{b}=2.4")
        assert cli.swallow_words(args, a) == 3.0
        assert cli.swallow_words(args, b) == 2.4

    def test_a_voice_given_no_pace_and_no_default_is_not_swallowed(self):
        a, b = voices_pair()
        args = parse("--voices", a, b, "--swallow", f"{b}=2")
        assert cli.swallow_words(args, a) is None

    def test_contradictions_are_refused(self):
        a, b = voices_pair()
        parser = build_parser()
        for argv in (["--swallow", "2", "3"],
                     ["--voices", a, b, "--swallow", f"{a}=2", f"{a}=3"],
                     ["--voices", a, b, "--swallow", "nosuchvoice=2"]):
            args = parser.parse_args(["song.mp4", *argv])
            with pytest.raises(SystemExit):
                cli.refuse_contradicting_swallow(parser, args)

    def test_a_consistent_request_passes(self):
        a, b = voices_pair()
        parser = build_parser()
        args = parser.parse_args(["song.mp4", "--voices", a, b,
                                  "--swallow", "2-4", f"{b}=2.4"])
        cli.refuse_contradicting_swallow(parser, args)

    def test_the_filename_says_it_was_swallowed(self):
        """A swallowed take must not replace the plain one."""
        assert cli.variant_tag(parse("--swallow", "2-4")) == "swallow2-4"
        assert cli.variant_tag(parse("--swallow", "3")) == "swallow3"
        assert cli.variant_tag(parse("--swallow", "2-4", "abc=2.4")) ==             "swallow2-4-abc2p4"
        assert cli.variant_tag(parse("--swallow", "2-4", "--mimicry", "0.6"))             == "mim0p60.swallow2-4"
        assert cli.variant_tag(parse()) is None

    def test_words_become_notes_through_the_bank_s_own_word_length(self):
        a, b, c = list(config.WORD_SYLLABLES)[:3]
        units = [make_unit([a]), make_unit([b, c])]
        per_word = sum(u.syllables for u in units) / 3
        assert cli.swallow_notes(3.0, units) == pytest.approx(
            max(1.0, 3.0 * config.RAP_WORD_SYLLABLES / per_word))
        assert cli.swallow_notes(0.01, units) == 1.0
