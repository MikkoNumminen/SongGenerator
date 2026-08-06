"""write_wav must be atomic.

Every stale-cache check in the pipeline trusts a wav that exists, and the
word bank gets overwritten in place, so a write interrupted halfway must
never leave a truncated file at the final name. The clips it would corrupt
are hand-recorded and cannot be regenerated.

Samples are compared by decoding, never by file bytes: libsndfile stamps the
wall-clock time of the write into a PEAK chunk, so byte comparison is flaky
by design (see AGENTS.md).
"""

import numpy as np
import pytest

from song_generator import audio_io, config

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

        def boom(*args, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(audio_io.sf, "write", boom)
        with pytest.raises(RuntimeError):
            audio_io.write_wav(dest, _clip(freq=440.0))

        np.testing.assert_allclose(audio_io.read_wav(dest), original, atol=1e-6)

    def test_a_failed_write_leaves_no_temp_file_behind(self, tmp_path, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(audio_io.sf, "write", boom)
        with pytest.raises(RuntimeError):
            audio_io.write_wav(tmp_path / "tango_1.wav", _clip())

        assert list(tmp_path.iterdir()) == []
