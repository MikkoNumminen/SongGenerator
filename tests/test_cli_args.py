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


class TestHelpTextIsNotAPromiseTheToolBreaks:
    """Help text is documentation that ships inside the binary.

    --output once promised output/<stem>.song_generator.mp3 while the tool
    wrote <stem>.<level>.mim<N>.mp3, so the one place a user looks for the
    answer had the wrong one.
    """

    def _help_for(self, flag):
        parser = build_parser()
        for action in parser._actions:
            if flag in action.option_strings:
                return action.help or ""
        raise AssertionError(f"{flag} is gone")

    def test_output_help_mentions_what_is_added_to_the_name(self):
        said = self._help_for("--output")
        assert "level" in said and "mim" in said

    def test_play_help_says_both_are_the_default(self):
        assert "both" in self._help_for("--play")

    def test_seed_help_says_a_run_is_fresh_by_default(self):
        said = self._help_for("--seed").lower()
        assert "new one each run" in said or "fresh" in said


class TestOutputGoesInItsOwnFolder:
    """A run writes fourteen files and there are a dozen songs.

    Flat, that is nearly two hundred files sorted by name, which interleaves
    every song's levels and rungs and makes finding one take a scroll.
    """

    def test_the_default_lands_in_a_folder_named_for_the_song(self):
        from pathlib import Path

        from song_generator.cli import output_path

        got = output_path(None, Path("input/musicHyva.mp4"), "curated")
        assert got.parent.name == "curated"
        assert got.parent.parent.name == "musicHyva"
        assert got.parent.parent.parent.name == "output"

    def test_the_filename_still_names_the_song(self):
        """So a file dragged out of its folder still says what it is."""
        from pathlib import Path

        from song_generator.cli import output_path

        got = output_path(None, Path("input/musicHyva.mp4"), "curated")
        assert got.name == "musicHyva.mp3"

    def test_an_explicit_output_is_folded_the_same_way(self):
        """Otherwise batch, which passes -o per song, would stay flat."""
        from pathlib import Path

        from song_generator.cli import output_path

        got = output_path(Path("elsewhere/song.mp3"), Path("input/x.mp4"), "curated")
        assert got.parent.name == "curated"
        assert got.parent.parent.name == "song"
        assert got.parent.parent.parent.name == "elsewhere"
        assert got.name == "song.mp3"
