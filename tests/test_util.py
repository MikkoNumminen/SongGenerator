"""The helpers every batch tool shares.

expand() existed three times: batch and mine_words carried identical copies,
and separate_hq an abridged inline one that had lost both the warning for a
pattern matching nothing and the dedupe. The same command line gesture then
behaved differently depending on which tool got it. One copy lives in util.py
now, and these pin what all three callers rely on.

word_similarity() is the same story one layer down: label_words and precheck
score the same clips at different stages, and the tuned core (ratio plus a
prefix reward) was copied between them, so retuning one would leave the other
behind.
"""

import pytest

from song_generator import config
from song_generator.util import expand, word_similarity


class TestExpand:
    def test_a_pattern_that_matches_nothing_warns(self, tmp_path, capsys):
        """Silence here reads as 'the batch ran', when in fact it ran on less
        than was asked for."""
        got = expand([str(tmp_path / "no_such_thing*.mp4")])
        assert got == []
        assert "nothing matched" in capsys.readouterr().err

    def test_a_plain_file_path_needs_no_glob(self, tmp_path, capsys):
        p = tmp_path / "song.mp4"
        p.write_bytes(b"x")
        assert expand([str(p)]) == [p]
        assert capsys.readouterr().err == ""

    def test_a_file_reached_through_two_patterns_is_processed_once(self, tmp_path):
        """A source separated twice costs the slowest stage twice for nothing."""
        p = tmp_path / "song.mp4"
        p.write_bytes(b"x")
        assert expand([str(p), str(tmp_path / "*.mp4")]) == [p]

    def test_matches_are_sorted_within_a_pattern(self, tmp_path):
        for name in ("b.mp4", "a.mp4", "c.mp4"):
            (tmp_path / name).write_bytes(b"x")
        got = expand([str(tmp_path / "*.mp4")])
        assert [p.name for p in got] == ["a.mp4", "b.mp4", "c.mp4"]


class TestEveryBatchToolSharesExpand:
    """Three copies is how the third one quietly diverged."""

    def test_batch_and_mine_words_use_the_shared_copy(self):
        from song_generator import batch, mine_words, util

        assert batch.expand is util.expand
        assert mine_words.expand is util.expand

    def test_separate_hq_now_warns_like_the_others(self, tmp_path, capsys):
        """Its inline copy swallowed a pattern that matched nothing."""
        from song_generator.separate_hq import main

        code = main([str(tmp_path / "no_such_thing*.mp4")])
        assert code == 2
        assert "nothing matched" in capsys.readouterr().err


class TestWordSimilarity:
    def test_a_clean_prefix_of_a_long_word_is_rewarded(self):
        """"kilo" scores poorly on whole-word ratio against "kilometer" yet is
        very likely that word sung and clipped."""
        assert word_similarity("kilo", "kilometer") >= config.MATCH_PREFIX_SCORE

    def test_short_fragments_earn_no_prefix_reward(self):
        """Two or three letters prefix-match half the recogniser's noise."""
        assert word_similarity("kil", "kilometer") < config.MATCH_PREFIX_SCORE

    def test_a_non_prefix_is_scored_on_ratio_alone(self):
        from difflib import SequenceMatcher

        assert word_similarity("bravu", "bravo") == pytest.approx(
            SequenceMatcher(None, "bravu", "bravo").ratio())

    @pytest.mark.parametrize("stage_score", [
        lambda heard: __import__("song_generator.label_words", fromlist=["x"])
        .best_target(heard)[1],
        lambda heard: __import__("song_generator.precheck", fromlist=["x"])
        .match_single(heard, 4)[1],
    ], ids=["label_words", "precheck"])
    def test_both_stages_follow_the_config_constants(self, monkeypatch, stage_score):
        """Retuning the prefix reward must move label_words AND precheck.

        That is the point of the consolidation: the two stages score the same
        clips, and while each held its own copy of the numbers, a retune of
        one silently left the other behind.
        """
        monkeypatch.setattr(config, "MATCH_PREFIX_SCORE", 0.93)
        assert stage_score("kilo") == pytest.approx(0.93)
