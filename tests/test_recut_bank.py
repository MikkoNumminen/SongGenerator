"""Locating a clip inside the stem it was cut from.

This is where the offset bug lived: clip timestamps in a filename are not always
where the audio starts, so re-cutting from the name lopped 50 ms off the front
of every shout. The fix was to take only the SOURCE from the name and always
derive the OFFSET by correlation. These pin that, since the module had no tests
at all when the bug shipped.

Correlation is exact here rather than approximate. A clip is a verbatim slice of
the stem, so the right position scores near 1.0 and nothing else comes close.
"""

import numpy as np
import pytest

from song_generator import audio_io, config
from song_generator.recut_bank import Origin, by_correlation, from_name

SR = config.SAMPLE_RATE


def _stem(seconds: float = 6.0, seed: int = 0) -> np.ndarray:
    """A stereo signal with enough structure to correlate against."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    tone = sum(np.sin(2 * np.pi * f * t) / (i + 1)
               for i, f in enumerate((110, 220, 441, 887)))
    noise = 0.25 * rng.standard_normal(t.size)
    env = 0.5 + 0.5 * np.sin(2 * np.pi * 0.7 * t)
    y = ((tone / 4 + noise) * env).astype(np.float32)
    return np.stack([y, y])


@pytest.fixture
def source(tmp_path):
    """A work directory holding a stem, as recut_bank expects to find one."""
    d = tmp_path / "asource"
    d.mkdir()
    stem = _stem()
    audio_io.write_wav(d / "vocal.wav", stem)
    return d, stem


def _slice(stem: np.ndarray, start_s: float, dur_s: float) -> np.ndarray:
    lo = int(start_s * SR)
    return np.array(stem[:, lo:lo + int(dur_s * SR)], dtype=np.float32)


class TestByCorrelation:
    @pytest.mark.parametrize("start_s", [0.0, 0.75, 2.5, 4.9])
    def test_finds_where_a_slice_came_from(self, source, start_s):
        d, stem = source
        clip = _slice(stem, start_s, 0.8)
        found = by_correlation(clip, {"asource": d}, {}, only=d)
        assert found is not None
        assert abs(found.start_s - start_s) < 0.01, (
            f"located at {found.start_s:.3f}s, expected {start_s:.3f}s"
        )

    def test_recovers_the_span_the_clip_covers(self, source):
        d, stem = source
        clip = _slice(stem, 1.25, 0.6)
        found = by_correlation(clip, {"asource": d}, {}, only=d)
        assert abs((found.end_s - found.start_s) - 0.6) < 0.01

    def test_picks_the_right_source_out_of_several(self, tmp_path):
        """The clip belongs to exactly one stem, and must not match a sibling."""
        dirs = {}
        stems = {}
        for i, name in enumerate(("one", "two", "three")):
            d = tmp_path / name
            d.mkdir()
            stems[name] = _stem(seed=i + 1)
            audio_io.write_wav(d / "vocal.wav", stems[name])
            dirs[name] = d

        clip = _slice(stems["two"], 2.0, 0.9)
        found = by_correlation(clip, dirs, {})
        assert found is not None
        assert found.work_dir.name == "two", f"matched {found.work_dir.name}"
        assert abs(found.start_s - 2.0) < 0.01

    def test_unrelated_audio_is_rejected(self, source):
        """Better to report nothing than to place a clip at a wrong offset."""
        d, _ = source
        rng = np.random.default_rng(99)
        alien = (0.4 * rng.standard_normal((2, int(SR * 0.7)))).astype(np.float32)
        assert by_correlation(alien, {"asource": d}, {}, only=d) is None

    def test_silence_is_rejected_rather_than_matched_anywhere(self, source):
        d, _ = source
        silence = np.zeros((2, int(SR * 0.5)), dtype=np.float32)
        assert by_correlation(silence, {"asource": d}, {}, only=d) is None

    def test_the_cache_does_not_change_the_answer(self, source):
        """A shared cache across many clips must not leak between lookups."""
        d, stem = source
        cache = {}
        first = by_correlation(_slice(stem, 1.0, 0.7), {"asource": d}, cache, only=d)
        second = by_correlation(_slice(stem, 3.4, 0.7), {"asource": d}, cache, only=d)
        assert abs(first.start_s - 1.0) < 0.01
        assert abs(second.start_s - 3.4) < 0.01


class TestFromName:
    """The name identifies the source. It is not evidence of the offset."""

    def test_reads_source_and_span_from_a_generated_name(self, source):
        d, _ = source
        origin = from_name("EEE_then__asource__12.30-15.10.wav", {"asource": d})
        assert origin is not None
        assert origin.work_dir == d
        assert (origin.start_s, origin.end_s) == (12.30, 15.10)

    @pytest.mark.parametrize("name", ["bravo1.wav", "", "no_timestamps_here.wav"])
    def test_returns_nothing_when_the_name_carries_no_span(self, name, source):
        d, _ = source
        assert from_name(name, {"asource": d}) is None

    def test_returns_nothing_for_an_unknown_source(self):
        assert from_name("clip__missing__1.00-2.00.wav", {}) is None

    def test_the_name_is_not_trusted_for_the_offset(self, source):
        """The bug itself: the recorded timestamp differed from the real start.

        A clip padded 50 ms earlier than its filename says still has to be
        located where the audio actually is, which only correlation can do.
        """
        d, stem = source
        real_start = 2.00
        clip = _slice(stem, real_start, 0.8)

        from_the_name = from_name("x__asource__2.05-2.85.wav", {"asource": d})
        assert from_the_name.start_s == 2.05, "name says one thing"

        measured = by_correlation(clip, {"asource": d}, {}, only=d)
        assert abs(measured.start_s - real_start) < 0.01, "audio says another"
        assert abs(measured.start_s - from_the_name.start_s) > 0.02, (
            "this test is only meaningful while the two disagree"
        )
