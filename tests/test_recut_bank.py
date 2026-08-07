"""Locating a clip inside the stem it was cut from.

This is where the offset bug lived: clip timestamps in a filename are not always
where the audio starts, so re-cutting from the name lopped 50 ms off the front
of every shout. The fix was to take only the SOURCE from the name and always
derive the OFFSET by correlation. These pin that, since the module had no tests
at all when the bug shipped.

Correlation is exact here rather than approximate. A clip is a verbatim slice of
the stem, so the right position scores near 1.0 and nothing else comes close.
"""

import json
from pathlib import Path

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


class TestRecutWillNotClobberHandNamedClips:
    """--out defaulted to the directory this tool created, back when nothing
    else lived there.

    A bank gets hand-curated afterwards: clips renamed by ear, new ones added,
    none of it regenerable. On this machine the default run would have written
    over eighteen of them and replaced the index, which is exactly the work
    AGENTS.md says can never be recreated.
    """

    def _sources(self, tmp_path, monkeypatch):
        """A work directory with both stems, and WORK_DIR pointed at it.

        The guard only fires for clips the run has located, and locating one
        takes a stem to correlate against. work/ is gitignored, so a fresh
        checkout has none, and without this setup the run finds nothing and
        returns success before the guard is ever reached.
        """
        d = tmp_path / "work" / "asource"
        d.mkdir(parents=True)
        stem = _stem()
        audio_io.write_wav(d / "vocal.wav", stem)
        audio_io.write_wav(d / "vocal_hq.wav", stem)
        monkeypatch.setattr(config, "WORK_DIR", str(tmp_path / "work"))
        return stem

    def _bank(self, path, stem, names):
        """Clips are verbatim slices of the stem, so correlation finds them."""
        path.mkdir(parents=True, exist_ok=True)
        index = {}
        for i, name in enumerate(names):
            audio_io.write_wav(path / name, _slice(stem, 1.0 + i, 0.8))
            index[name] = {"words": [name.split("_")[0]], "syllables": 2,
                           "duration_s": 0.8, "midi": 53.0,
                           "syllable_bounds_s": [0.4]}
        (path / "words.json").write_text(json.dumps(index), encoding="utf-8")
        return path

    def test_it_refuses_when_the_output_already_holds_those_clips(
            self, tmp_path, monkeypatch, capsys):
        from song_generator.recut_bank import main

        stem = self._sources(tmp_path, monkeypatch)
        source = self._bank(tmp_path / "words", stem, ["bravo_1.wav"])
        out = self._bank(tmp_path / "words_hq", stem, ["bravo_1.wav"])
        before = (out / "bravo_1.wav").read_bytes()

        code = main(["--bank", str(source), "--out", str(out)])
        assert code == 2
        assert "already exist" in capsys.readouterr().err
        assert (out / "bravo_1.wav").read_bytes() == before

    def test_the_refusal_names_what_would_be_lost(
            self, tmp_path, monkeypatch, capsys):
        from song_generator.recut_bank import main

        stem = self._sources(tmp_path, monkeypatch)
        source = self._bank(tmp_path / "words", stem,
                            ["bravo_1.wav", "tango_1.wav"])
        out = self._bank(tmp_path / "words_hq", stem, ["bravo_1.wav"])

        main(["--bank", str(source), "--out", str(out)])
        said = capsys.readouterr().err
        assert "bravo_1.wav" in said
        assert "--overwrite" in said

    def test_an_empty_output_directory_is_not_refused(self, tmp_path, monkeypatch):
        """The ordinary case still works: nothing there, nothing to lose."""
        from song_generator.recut_bank import main

        stem = self._sources(tmp_path, monkeypatch)
        source = self._bank(tmp_path / "words", stem, ["bravo_1.wav"])
        code = main(["--bank", str(source), "--out", str(tmp_path / "fresh")])
        assert code == 0


class TestTheGuardRunsAgainAtWriteTime:
    """The clash check snapshots --out once, before the write loop, and
    write_wav overwrites without asking.

    A clip renamed by ear into --out while the loop runs is the same hand
    work the snapshot guard exists to protect, and it appeared after the
    snapshot, so without a second check at write time it was clobbered with
    the guard never having seen it.
    """

    def _sources(self, tmp_path, monkeypatch):
        """A work directory with both stems, and WORK_DIR pointed at it."""
        d = tmp_path / "work" / "asource"
        d.mkdir(parents=True)
        stem = _stem()
        audio_io.write_wav(d / "vocal.wav", stem)
        audio_io.write_wav(d / "vocal_hq.wav", stem)
        monkeypatch.setattr(config, "WORK_DIR", str(tmp_path / "work"))
        return stem

    def _bank(self, tmp_path, stem):
        bank = tmp_path / "words"
        bank.mkdir()
        index = {}
        for name, start in (("bravo_1.wav", 1.0), ("tango_1.wav", 3.0)):
            audio_io.write_wav(bank / name, _slice(stem, start, 0.8))
            index[name] = {"words": [name.split("_")[0]], "syllables": 2,
                           "duration_s": 0.8, "midi": 53.0}
        (bank / "words.json").write_text(json.dumps(index), encoding="utf-8")
        return bank

    def _plant_during_the_write_loop(self, monkeypatch, out):
        """Drop a hand-named clip into --out the moment the loop starts.

        The loop's first read of the better stem is the earliest point that
        is provably after the snapshot was taken.
        """
        real = audio_io.read_wav

        def read_and_plant(path):
            if Path(path).name == "vocal_hq.wav" and not (out / "tango_1.wav").exists():
                (out / "tango_1.wav").write_bytes(b"hand work, mid-run")
            return real(path)

        monkeypatch.setattr(audio_io, "read_wav", read_and_plant)

    def test_a_clip_that_appears_mid_run_is_not_clobbered(self, tmp_path, monkeypatch, capsys):
        from song_generator.recut_bank import main

        stem = self._sources(tmp_path, monkeypatch)
        bank = self._bank(tmp_path, stem)
        out = tmp_path / "fresh"
        self._plant_during_the_write_loop(monkeypatch, out)

        code = main(["--bank", str(bank), "--out", str(out)])

        assert code == 0
        assert (out / "tango_1.wav").read_bytes() == b"hand work, mid-run"
        assert "left untouched" in capsys.readouterr().err
        assert (out / "bravo_1.wav").is_file(), "the clean clip is still re-cut"

        index = json.loads((out / "words.json").read_text(encoding="utf-8"))
        assert "bravo_1.wav" in index
        assert "tango_1.wav" not in index, (
            "the index must not describe hand work with this tool's numbers"
        )

    def test_overwrite_still_means_overwrite(self, tmp_path, monkeypatch):
        from song_generator.recut_bank import main

        stem = self._sources(tmp_path, monkeypatch)
        bank = self._bank(tmp_path, stem)
        out = tmp_path / "fresh"
        self._plant_during_the_write_loop(monkeypatch, out)

        code = main(["--bank", str(bank), "--out", str(out), "--overwrite"])

        assert code == 0
        assert (out / "tango_1.wav").read_bytes() != b"hand work, mid-run"


class TestTheIndexOnlyNamesWhatWasWritten:
    """words.json is what load_bank believes. A span that collapses against
    the better stem writes no file, so leaving its entry in the index would
    describe a clip that is not there, and a render would go looking for it.

    The protected mid-run path already dropped its entries; this pins the
    degenerate-span path doing the same, and the run saying out loud which
    words the exclusions cost and how to get them back.
    """

    def _sources(self, tmp_path, monkeypatch):
        """vocal.wav is the full stem; vocal_hq.wav only its first second,
        so a clip located late in the source has nowhere to be cut from."""
        d = tmp_path / "work" / "asource"
        d.mkdir(parents=True)
        stem = _stem()
        audio_io.write_wav(d / "vocal.wav", stem)
        audio_io.write_wav(d / "vocal_hq.wav", stem[:, :SR])
        monkeypatch.setattr(config, "WORK_DIR", str(tmp_path / "work"))
        return stem

    def _bank(self, tmp_path, stem):
        bank = tmp_path / "words"
        bank.mkdir()
        index = {}
        for name, start in (("bravo_1.wav", 0.0), ("tango_1.wav", 3.0)):
            audio_io.write_wav(bank / name, _slice(stem, start, 0.8))
            index[name] = {"words": [name.split("_")[0]], "syllables": 2,
                           "duration_s": 0.8, "midi": 53.0}
        (bank / "words.json").write_text(json.dumps(index), encoding="utf-8")
        return bank

    def test_a_degenerate_span_takes_its_entry_out_of_the_index(
            self, tmp_path, monkeypatch):
        from song_generator.recut_bank import main

        stem = self._sources(tmp_path, monkeypatch)
        bank = self._bank(tmp_path, stem)
        out = tmp_path / "fresh"

        code = main(["--bank", str(bank), "--out", str(out)])

        assert code == 0
        assert (out / "bravo_1.wav").is_file(), "the clip that fits is re-cut"
        assert not (out / "tango_1.wav").exists(), (
            "nothing can be cut for a span past the end of the stem"
        )
        index = json.loads((out / "words.json").read_text(encoding="utf-8"))
        assert "bravo_1.wav" in index
        assert "tango_1.wav" not in index, (
            "the index must not name a file that was never written"
        )

    def test_the_exclusion_notice_names_the_clip_and_the_fix(
            self, tmp_path, monkeypatch, capsys):
        from song_generator.recut_bank import main

        stem = self._sources(tmp_path, monkeypatch)
        bank = self._bank(tmp_path, stem)

        main(["--bank", str(bank), "--out", str(tmp_path / "fresh")])
        said = capsys.readouterr().err

        assert "tango_1.wav" in said, "the excluded clip is named"
        assert "absent" in said, "the consequence is stated, not implied"
        assert "build_bank" in said, "the fix is a command, not a shrug"
