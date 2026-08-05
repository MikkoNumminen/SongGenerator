"""The command line surface, which is what anyone actually touches.

main() needs stems and a GPU, so it is not exercised here. The parser is, and
it is where a flag gets renamed and the documentation quietly stops being
true. These are cheap and they guard the part a person types.
"""

import pytest

from song_generator import config
from song_generator.cli import build_parser


def parse(*argv):
    return build_parser().parse_args(["song.mp4", *argv])


class TestDefaults:
    def test_no_level_means_every_level(self):
        """Both levels every time is the decision, so the default must be None
        rather than one of them: a named default would silently render one."""
        assert parse().play is None
        assert set(config.PLAY_BOTH_LEVELS) == {"conservative", "wild"}

    def test_no_seed_means_a_fresh_arrangement_each_run(self):
        assert parse().seed is None

    def test_the_standardised_tier_is_preferred_unless_refused(self):
        assert parse().raw_clips is False
        assert parse("--raw-clips").raw_clips is True

    def test_the_default_bank_exists_in_the_bank_table(self):
        assert parse().bank in config.BANKS


class TestChoicesAreRealValues:
    def test_every_playfulness_choice_is_a_defined_level(self):
        for level in config.PLAY_LEVELS:
            assert parse("--play", level).play == level

    def test_an_unknown_level_is_refused(self):
        with pytest.raises(SystemExit):
            parse("--play", "feral")

    def test_an_unknown_bank_is_refused(self):
        with pytest.raises(SystemExit):
            parse("--bank", "nosuchbank")

    def test_every_engine_choice_is_one_pitchshift_knows(self):
        for engine in ("world", "rubberband"):
            assert parse("--engine", engine).engine == engine


class TestFlagsTheDocsPromise:
    """WORKFLOWS.md lists these. A rename would make the runbook wrong."""

    @pytest.mark.parametrize("flag,attr", [
        ("--mimicry", "mimicry"),
        ("--play", "play"),
        ("--arrangement", "arrangement"),
        ("--bank", "bank"),
        ("--seed", "seed"),
        ("--raw-clips", "raw_clips"),
        ("--words-dir", "words_dir"),
        ("--no-shift", "no_shift"),
    ])
    def test_the_flag_exists(self, flag, attr):
        assert hasattr(parse(), attr), f"{flag} is documented but gone"

    def test_arrangement_takes_a_path(self):
        assert str(parse("--arrangement", "x.arr").arrangement) == "x.arr"


class TestBatchPassesThroughWhatItOffers:
    def test_batch_can_narrow_to_one_level(self):
        """Twenty songs at both levels is 280 files, so it has to be narrowable."""
        from song_generator.batch import build_parser as batch_parser

        args = batch_parser().parse_args(["input/*.mp4", "--play", "wild"])
        assert args.play == "wild"

    def test_batch_defaults_to_both_levels(self):
        from song_generator.batch import build_parser as batch_parser

        assert batch_parser().parse_args(["input/*.mp4"]).play is None
