"""What audio_io must guarantee: a write is atomic, and ffmpeg cannot hang.

Two properties, one shape. Both are failures that used to leave no trace of
themselves. A write interrupted halfway left a truncated wav at the final
name, which every stale-cache check in the pipeline then trusted, and the
clips it would corrupt are hand-recorded and cannot be regenerated. An ffmpeg
call with no ceiling froze a batch run indefinitely with no output at all.

Samples are compared by decoding, never by file bytes: libsndfile stamps the
wall-clock time of the write into a PEAK chunk, so byte comparison is flaky
by design (see AGENTS.md).
"""

import subprocess
from pathlib import Path

import numpy as np
import pytest

from song_generator import audio_io, config
from song_generator.audio_io import AudioError

SR = config.SAMPLE_RATE

def _clip(freq: float = 200.0, dur: float = 0.1) -> np.ndarray:
    t = np.arange(int(SR * dur)) / SR
    y = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([y, y])


class TestWriteWavIsAtomic:
    def test_success_leaves_only_the_destination(self, tmp_path):
        clip = _clip()
        out = audio_io.write_wav(tmp_path / "sub" / "bravo_1.wav", clip)

        assert out == tmp_path / "sub" / "bravo_1.wav"
        assert [p.name for p in (tmp_path / "sub").iterdir()] == ["bravo_1.wav"]
        np.testing.assert_allclose(audio_io.read_wav(out), clip, atol=1e-6)

    def test_a_failed_write_does_not_touch_the_existing_file(self, tmp_path, monkeypatch):
        original = _clip(freq=200.0)
        dest = audio_io.write_wav(tmp_path / "bravo_1.wav", original)

        def boom(target, *args, **kwargs):
            # Writes before it fails, which is the whole point: a fake that
            # raises without touching the file passes on the old code too,
            # since that also left the destination alone. Only a partial write
            # tells the two apart.
            Path(target).write_bytes(b"half a wav and then the power went")
            raise RuntimeError("disk full")

        monkeypatch.setattr(audio_io.sf, "write", boom)
        with pytest.raises(RuntimeError):
            audio_io.write_wav(dest, _clip(freq=440.0))

        np.testing.assert_allclose(audio_io.read_wav(dest), original, atol=1e-6)

    def test_a_failed_write_leaves_no_temp_file_behind(self, tmp_path, monkeypatch):
        def boom(target, *args, **kwargs):
            # Writes before it fails, which is the whole point: a fake that
            # raises without touching the file passes on the old code too,
            # since that also left the destination alone. Only a partial write
            # tells the two apart.
            Path(target).write_bytes(b"half a wav and then the power went")
            raise RuntimeError("disk full")

        monkeypatch.setattr(audio_io.sf, "write", boom)
        with pytest.raises(RuntimeError):
            audio_io.write_wav(tmp_path / "tango_1.wav", _clip())

        assert list(tmp_path.iterdir()) == []


def _hang_ffmpeg(monkeypatch):
    def run(cmd, **kwargs):
        assert kwargs.get("timeout") == config.FFMPEG_TIMEOUT_S, \
            "every ffmpeg call must carry the configured timeout"
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(audio_io.subprocess, "run", run)
    monkeypatch.setattr(audio_io.shutil, "which", lambda name: "ffmpeg")


def test_the_timeout_is_a_config_constant_not_a_hardcoded_number():
    """Project rule: no tunable lives outside config.py."""
    assert config.FFMPEG_TIMEOUT_S > 0


def test_a_hung_decode_is_an_error_naming_the_file(tmp_path, monkeypatch):
    _hang_ffmpeg(monkeypatch)
    stalled = tmp_path / "stalled.mp3"
    stalled.write_bytes(b"not audio")
    with pytest.raises(AudioError, match="stalled.mp3"):
        audio_io.decode(stalled)


def test_a_hung_encode_is_an_error_naming_the_file(tmp_path, monkeypatch):
    _hang_ffmpeg(monkeypatch)
    with pytest.raises(AudioError, match="out.mp3"):
        audio_io.encode_mp3(tmp_path / "out.mp3",
                            np.zeros((2, 64), dtype=np.float32))
