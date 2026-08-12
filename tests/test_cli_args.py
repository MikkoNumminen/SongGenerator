"""The command line surface, which is what anyone actually touches.

main() needs stems and a GPU, so it is not exercised here. The parser is, and
it is where a flag gets renamed and the documentation quietly stops being
true. These are cheap and they guard the part a person types.
"""

from pathlib import Path

import pytest

from song_generator import cli, config
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

        got = output_path(None, Path("input/musicHyva.mp4"), "ppbank")
        assert got.parent.name == "ppbank"
        assert got.parent.parent.name == "musicHyva"
        assert got.parent.parent.parent.name == "output"

    def test_the_filename_still_names_the_song(self):
        """So a file dragged out of its folder still says what it is."""
        from pathlib import Path

        from song_generator.cli import output_path

        got = output_path(None, Path("input/musicHyva.mp4"), "ppbank")
        assert got.name == "musicHyva.mp3"

    def test_an_explicit_output_is_folded_the_same_way(self):
        """Otherwise batch, which passes -o per song, would stay flat."""
        from pathlib import Path

        from song_generator.cli import output_path

        got = output_path(Path("elsewhere/song.mp3"), Path("input/x.mp4"), "ppbank")
        assert got.parent.name == "ppbank"
        assert got.parent.parent.name == "song"
        assert got.parent.parent.parent.name == "elsewhere"
        assert got.name == "song.mp3"


class TestARunWritesTwoFiles:
    """The ladder is asked for by name, never arrived at by default.

    A run used to render all seven mimicry rungs at both levels, so one song
    became fourteen files per bank. Two of them were listened to; the rest
    were deleted by hand afterwards, once they had been noticed. The default
    moving back is the failure these guard.
    """

    def test_the_default_walks_no_ladder(self):
        assert cli.mimicry_targets(parse()) == [None]

    def test_the_default_rung_is_the_top_of_the_ladder(self):
        """Full mimicry, not merely some single value: the two files are the
        ones that sing the tune as closely as the song allows."""
        assert cli.single_mimicry(parse()) == config.FULL_MIMICRY
        assert config.FULL_MIMICRY == 1.0
        assert config.FULL_MIMICRY == max(config.MIMICRY_VARIANTS)

    def test_the_default_is_named_the_way_the_site_names_it(self):
        """The site renders by passing --mimicry 1, which writes
        `song.wild.mp3`. A default that walked a one-rung ladder instead would
        write `song.wild.mim1p00.mp3` for the same audio, and one song would
        sit in the library twice under two names."""
        assert cli.mimicry_targets(parse()) == cli.mimicry_targets(parse("--mimicry", "1"))
        assert cli.single_mimicry(parse()) == cli.single_mimicry(parse("--mimicry", "1"))

    def test_the_ladder_comes_back_when_it_is_asked_for(self):
        assert cli.mimicry_targets(parse("--ladder")) == \
            list(config.MIMICRY_VARIANTS)

    def test_one_named_setting_writes_one_file(self):
        assert cli.mimicry_targets(parse("--mimicry", "0.6")) == [None]
        assert cli.single_mimicry(parse("--mimicry", "0.6")) == 0.6

    def test_a_run_driving_the_shift_itself_solves_for_no_rung(self):
        """--mix and --no-shift say what to shift outright, so there is
        nothing to solve for and full mimicry must not be imposed on top."""
        assert cli.mimicry_targets(parse("--mix", "0.5")) == [None]
        assert cli.single_mimicry(parse("--mix", "0.5")) is None
        assert cli.mimicry_targets(parse("--no-shift")) == [None]
        assert cli.single_mimicry(parse("--no-shift")) is None

    @pytest.mark.parametrize("argv", [
        ("--ladder", "--mimicry", "0.6"),
        ("--ladder", "--mimicry", "1"),
        ("--ladder", "--no-shift"),
        ("--ladder", "--mix", "0.5"),
    ])
    def test_asking_for_the_ladder_and_one_rung_at_once_is_refused(self, argv):
        """Resolved silently, whichever lost lost without a word. `--ladder
        --mimicry 1` wrote the two plain takes over the two already there and
        reported "2 versions" as though that had been the request."""
        with pytest.raises(SystemExit):
            cli.main(["song.mp4", *argv])


class TestEveryFilenameCarriesTheLevel:
    """Both write sites, one function, no way to disagree.

    The level went into the name at the mimicry-sweep site and not the
    single-render one, so `--play conservative --mimicry 0.6` and then
    `--play wild --mimicry 0.6` wrote the same filename and the second run
    silently replaced the first. The same failure as two banks sharing a
    filename, one layer down, for the second time.
    """

    def test_two_single_level_runs_cannot_collide(self):
        from pathlib import Path

        from song_generator.cli import versioned_name

        out = Path("output/song/ppbank/song.mp3")
        a = versioned_name(out, "conservative")
        b = versioned_name(out, "wild")
        assert a != b
        assert a.name == "song.conservative.mp3"
        assert b.name == "song.wild.mp3"

    def test_the_mimicry_rung_joins_the_level(self):
        from pathlib import Path

        from song_generator.cli import versioned_name

        out = Path("output/song/ppbank/song.mp3")
        got = versioned_name(out, "wild", tag="mim0p60")
        assert got.name == "song.wild.mim0p60.mp3"

    def test_an_output_already_naming_the_level_is_not_doubled(self):
        from pathlib import Path

        from song_generator.cli import versioned_name

        out = Path("output/song/ppbank/song.wild.mp3")
        assert versioned_name(out, "wild").name == "song.wild.mp3"
        assert versioned_name(out, "wild", tag="mim0p60").name == \
            "song.wild.mim0p60.mp3"


class TestOnlyThePlainTakeGetsThePlainName:
    """A one-off render must not land on the filename of the kept take.

    This used to hold for free: the default walked the ladder and every file
    it wrote carried a rung, while a one-off carried none. Once the default
    became two files with no rung in the name, every one-off started writing
    the default's own names, so `--no-shift` on a song replaced the take
    somebody had decided to keep.
    """

    def test_a_plain_run_is_not_tagged(self):
        assert cli.variant_tag(parse()) is None

    def test_full_mimicry_asked_for_by_name_is_still_the_plain_take(self):
        """It is the same audio, and the site renders by asking for it."""
        assert cli.variant_tag(parse("--mimicry", "1")) is None

    def test_a_lesser_rung_says_so(self):
        assert cli.variant_tag(parse("--mimicry", "0.6")) == "mim0p60"
        assert cli.variant_tag(parse("--mimicry", "0")) == "mim0p00"

    def test_the_other_two_ways_of_naming_a_shift_say_so_too(self):
        assert cli.variant_tag(parse("--no-shift")) == "noshift"
        assert cli.variant_tag(parse("--mix", "0.5")) == "mix0p50"

    def test_a_replay_is_not_the_take_it_was_replayed_from(self):
        """--arrangement is advertised as the way to edit what gets sung, so
        the usual replay is a different rendering wearing the same level."""
        assert cli.variant_tag(parse("--arrangement", "w.arr")) == "replay"

    def test_a_rung_a_hair_below_full_cannot_take_the_ladder_s_top_name(self):
        """0.999 is not 1.0, but both spell mim1p00, which is the name the
        ladder gives its own full-mimicry rung."""
        assert cli.variant_tag(parse("--mimicry", "0.999")) is None
        assert cli.variant_tag(parse("--mimicry", "0.994")) == "mim0p99"

    def test_no_one_off_shares_a_name_with_the_plain_take(self):
        from pathlib import Path

        from song_generator.cli import versioned_name

        out = Path("output/song/ppbank/song.mp3")
        plain = versioned_name(out, "wild", tag=cli.variant_tag(parse()))
        others = [
            versioned_name(out, "wild", tag=cli.variant_tag(parse(*argv)))
            for argv in (("--mimicry", "0.6"), ("--no-shift",), ("--mix", "0.5"))
        ]
        assert plain.name == "song.wild.mp3"
        assert plain not in others
        assert len(set(others)) == len(others)

    def test_every_rung_of_a_ladder_is_told_apart(self):
        from pathlib import Path

        from song_generator.cli import rung_word, versioned_name

        out = Path("output/song/ppbank/song.mp3")
        names = {versioned_name(out, "wild", tag=rung_word(t)).name
                 for t in config.MIMICRY_VARIANTS}
        assert len(names) == len(config.MIMICRY_VARIANTS)
        assert "song.wild.mim1p00.mp3" in names, "the name the ladder has always used"


# ---------------------------------------------------------------------------
# Keeping the take a render replaces
# ---------------------------------------------------------------------------


class TestOneGenerationBack:
    """A render wrote straight over the take that was there, so a run that came
    out worse than the last one had nothing to go back to.

    One generation, per song, bank and level, which is what the naming already
    separates. Exactly one: two takes is a rollback, and fifteen is the
    situation this repository just deleted seven gigabytes of.
    """

    def _take(self, folder: Path, body: bytes) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "song.wild.mp3"
        target.write_bytes(body)
        return target

    def test_the_take_that_was_there_is_kept(self, tmp_path):
        target = self._take(tmp_path / "song" / "nbank", b"the old one")

        kept = cli.keep_the_one_it_replaces(target)

        assert kept is not None
        assert kept.read_bytes() == b"the old one"
        assert kept.parent.name == cli.PREVIOUS_DIR
        # Moved, not copied: what is left is the slot the new render fills.
        assert not target.exists()

    def test_nothing_to_keep_is_not_an_error(self, tmp_path):
        """The first render of a song has no predecessor, which is ordinary."""
        folder = tmp_path / "song" / "nbank"
        folder.mkdir(parents=True)

        assert cli.keep_the_one_it_replaces(folder / "song.wild.mp3") is None

    def test_only_one_generation_is_kept(self, tmp_path):
        """A second re-render replaces the backup rather than adding to it.

        On Windows a plain rename refuses to overwrite an existing file, so
        this is the case that would raise instead of rotating.
        """
        folder = tmp_path / "song" / "nbank"
        target = self._take(folder, b"first")
        cli.keep_the_one_it_replaces(target)
        self._take(folder, b"second")

        cli.keep_the_one_it_replaces(target)

        kept = list((folder / cli.PREVIOUS_DIR).glob("*.mp3"))
        assert len(kept) == 1
        assert kept[0].read_bytes() == b"second"

    def test_the_rollback_flag_restores_without_rendering(self, tmp_path, capsys):
        """End to end through main. The point of the flag is that it needs no
        stems, no bank and no GPU, so it must return before any of that."""
        song = tmp_path / "song.mp4"
        song.write_bytes(b"not actually read")
        out = tmp_path / "out" / "song.mp3"
        folder = out.parent / "song" / "ppbank"
        folder.mkdir(parents=True)
        for level in ("wild", "conservative"):
            take = folder / f"song.{level}.mp3"
            take.write_bytes(f"good {level}".encode())
            cli.keep_the_one_it_replaces(take)
            take.write_bytes(f"bad {level}".encode())

        code = cli.main([str(song), "--bank", "ppbank", "--output", str(out),
                         "--rollback"])

        assert code == cli.EXIT_OK
        assert (folder / "song.wild.mp3").read_bytes() == b"good wild"
        assert (folder / "song.conservative.mp3").read_bytes() == (
            b"good conservative")

    def test_the_rollback_flag_reports_when_there_is_nothing_kept(
            self, tmp_path, capsys):
        song = tmp_path / "song.mp4"
        song.write_bytes(b"not actually read")

        code = cli.main([str(song), "--bank", "ppbank",
                         "--output", str(tmp_path / "out" / "song.mp3"),
                         "--rollback"])

        assert code == cli.EXIT_ERROR
        assert "nothing kept" in capsys.readouterr().err

    def test_rolling_back_puts_the_previous_take_in_place(self, tmp_path):
        """The other half of keeping one. Without this the backup is a file in
        a folder and the rollback is done in Explorer."""
        folder = tmp_path / "song" / "nbank"
        target = self._take(folder, b"the good one")
        cli.keep_the_one_it_replaces(target)
        self._take(folder, b"the bad re-render")

        assert cli.restore_the_previous(target) == target
        assert target.read_bytes() == b"the good one"

    def test_rolling_back_twice_returns_to_where_it_started(self, tmp_path):
        """Somebody comparing two takes by ear will press this repeatedly, and
        neither take may be the one that gets thrown away."""
        folder = tmp_path / "song" / "nbank"
        target = self._take(folder, b"first")
        cli.keep_the_one_it_replaces(target)
        self._take(folder, b"second")

        cli.restore_the_previous(target)
        cli.restore_the_previous(target)

        assert target.read_bytes() == b"second"
        assert (folder / cli.PREVIOUS_DIR / target.name).read_bytes() == b"first"
        # The swap leaves nothing behind it.
        assert sorted(p.name for p in (folder / cli.PREVIOUS_DIR).iterdir()) == [
            target.name
        ]

    def test_rolling_back_with_nothing_kept_says_so(self, tmp_path):
        folder = tmp_path / "song" / "nbank"
        target = self._take(folder, b"the only one")

        assert cli.restore_the_previous(target) is None
        assert target.read_bytes() == b"the only one"

    def test_rolling_back_a_deleted_take_is_a_plain_restore(self, tmp_path):
        """The safety guard against deleting by accident: the kept take comes
        back even when there is nothing left to swap it with."""
        folder = tmp_path / "song" / "nbank"
        target = self._take(folder, b"deleted by hand")
        cli.keep_the_one_it_replaces(target)

        assert cli.restore_the_previous(target) == target
        assert target.read_bytes() == b"deleted by hand"
        assert not (folder / cli.PREVIOUS_DIR / target.name).exists()

    def test_a_backup_is_kept_per_level_and_per_bank(self, tmp_path):
        """A wild render must not evict the conservative backup, nor one bank
        another's. Those are the slots the naming already separates."""
        song = tmp_path / "song"
        for bank in ("nbank", "ppbank"):
            for level in ("wild", "conservative"):
                folder = song / bank
                folder.mkdir(parents=True, exist_ok=True)
                take = folder / f"song.{level}.mp3"
                take.write_bytes(f"{bank}/{level}".encode())
                cli.keep_the_one_it_replaces(take)

        kept = sorted(p.relative_to(song).as_posix()
                      for p in song.rglob(f"{cli.PREVIOUS_DIR}/*.mp3"))
        assert kept == [
            "nbank/previous/song.conservative.mp3",
            "nbank/previous/song.wild.mp3",
            "ppbank/previous/song.conservative.mp3",
            "ppbank/previous/song.wild.mp3",
        ]

    def test_the_kept_take_is_not_listed_as_a_rendering(self, tmp_path):
        """The songs page walks `<song>/<bank>/*.mp3`. A backup saved beside
        the take as `song.wild.previous.mp3` would appear there as a second
        take called "previous"; a directory inside the bank does not."""
        folder = tmp_path / "song" / "nbank"
        target = self._take(folder, b"old")

        cli.keep_the_one_it_replaces(target)

        assert list(folder.glob("*.mp3")) == []
