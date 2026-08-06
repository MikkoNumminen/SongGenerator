"""Partial failure must not report success.

batch, mine_words and precheck all keep going when one item fails, which is
right: one bad song must not end a twenty-song run. All three then used to
exit 0, so a shell or a CI step read a mostly-failed run as a clean one.
These pin the contract from both sides: every item is still attempted, and
the exit code is non-zero when any of them failed.
"""

import sys
import types
from pathlib import Path

import numpy as np
import pytest

from song_generator import audio_io, batch, config, mine_words, precheck


def _sources(tmp_path, n=3):
    paths = []
    for i in range(n):
        p = tmp_path / f"song{i}.mp4"
        p.write_bytes(b"x")
        paths.append(p)
    return paths


class TestBatchExitCode:
    def _run(self, tmp_path, monkeypatch, render):
        songs = _sources(tmp_path)
        monkeypatch.setattr("song_generator.cli.main", render)
        return batch.main([str(s) for s in songs] + ["-o", str(tmp_path / "out")])

    def test_one_failing_song_makes_the_batch_nonzero(self, tmp_path, monkeypatch):
        """19 of 20 rendering is not success, and the failure must not stop
        the rest from being attempted either."""
        attempted = []

        def render(argv):
            attempted.append(Path(argv[0]).stem)
            return 1 if attempted[-1] == "song1" else 0

        assert self._run(tmp_path, monkeypatch, render) != 0
        assert attempted == ["song0", "song1", "song2"]

    def test_a_crash_in_one_song_counts_as_a_failure_too(self, tmp_path, monkeypatch):
        attempted = []

        def render(argv):
            attempted.append(Path(argv[0]).stem)
            if attempted[-1] == "song1":
                raise RuntimeError("separation died")
            return 0

        assert self._run(tmp_path, monkeypatch, render) != 0
        assert attempted == ["song0", "song1", "song2"]

    def test_a_clean_batch_exits_zero(self, tmp_path, monkeypatch):
        assert self._run(tmp_path, monkeypatch, lambda argv: 0) == 0

    def test_mode_b_refusals_alone_are_not_failures(self, tmp_path, monkeypatch):
        """A song with no vocal is refused as designed, not botched."""
        def render(argv):
            return 3 if "song1" in argv[0] else 0

        assert self._run(tmp_path, monkeypatch, render) == 0

    def test_a_batch_that_rendered_nothing_is_not_a_success(self, tmp_path, monkeypatch):
        assert self._run(tmp_path, monkeypatch, lambda argv: 3) != 0


class TestMineWordsExitCode:
    def _run(self, tmp_path, monkeypatch, mine):
        sources = _sources(tmp_path)
        monkeypatch.setattr(mine_words, "mine_one", mine)
        monkeypatch.setattr(mine_words, "resolve_device", lambda d: "cpu")
        return mine_words.main(
            [str(s) for s in sources] + ["-o", str(tmp_path / "cand")])

    def test_one_failed_source_is_nonzero_and_the_rest_still_mine(
            self, tmp_path, monkeypatch):
        """Success used to mean ANY source mined, so one dead source out of
        twenty vanished into exit 0."""
        mined = []

        def mine(path, out_root, device, thresholds, asr_matches=None):
            mined.append(path.stem)
            if path.stem == "song1":
                raise RuntimeError("separation died")
            return mine_words.SourceResult(name=path.name, candidates=2)

        assert self._run(tmp_path, monkeypatch, mine) != 0
        assert mined == ["song0", "song1", "song2"]

    def test_every_source_mined_is_zero(self, tmp_path, monkeypatch):
        def mine(path, out_root, device, thresholds, asr_matches=None):
            return mine_words.SourceResult(name=path.name, candidates=2)

        assert self._run(tmp_path, monkeypatch, mine) == 0


class TestPrecheckExitCode:
    """A Whisper batch that dies leaves its clips unguessed. That is worth
    continuing past, and worth reporting: exit 0 said every clip had been
    checked when some never were."""

    def _clip(self, folder, name):
        # Short of SHOUT_MIN_S on purpose, so the clip counts as speech and
        # actually reaches a transcription batch.
        n = int(0.2 * config.SAMPLE_RATE)
        tone = 0.5 * np.sin(np.linspace(0.0, 2 * np.pi * 220 * 0.2, n))
        audio_io.write_wav(folder / name, tone.astype(np.float32))

    def _run(self, tmp_path, monkeypatch, transcribe):
        folder = tmp_path / "candidates"
        folder.mkdir()
        self._clip(folder, "AI_bravo__c01__0.00-0.20.wav")

        fake = types.ModuleType("whisper")

        class Model:
            def transcribe(self, *a, **k):
                return transcribe()

        fake.load_model = lambda *a, **k: Model()
        monkeypatch.setitem(sys.modules, "whisper", fake)
        monkeypatch.setattr(precheck, "resolve_device", lambda d: "cpu")
        return precheck.main(["--folder", str(folder)])

    def test_a_failed_batch_exits_nonzero(self, tmp_path, monkeypatch):
        def boom():
            raise RuntimeError("CUDA fell over")

        assert self._run(tmp_path, monkeypatch, boom) != 0

    def test_a_clean_pass_exits_zero(self, tmp_path, monkeypatch):
        assert self._run(tmp_path, monkeypatch, lambda: {"segments": []}) == 0
