"""Mode detection is the one bit of real judgement in commit 1, so it gets tests.

Synthetic stand-ins rather than real songs: a vibrato'd, enveloped tone for a
sung line, broadband noise at realistic level for the tonal bleed an
instrumental's "vocal" stem actually contains.

    .venv\\Scripts\\python.exe -m pytest tests/
"""

import numpy as np
import pytest

from luokkaretki import audio_io, config
from luokkaretki.detect import detect_vocal, integrated_lufs

SR = config.SAMPLE_RATE


def _stereo(mono: np.ndarray) -> np.ndarray:
    return np.stack([mono, mono]).astype(np.float32)


@pytest.fixture
def t():
    return np.arange(int(SR * 3.0)) / SR


@pytest.fixture
def sung(t):
    """A tone with vibrato and an amplitude envelope -- reads as voiced."""
    vibrato = 220 * (1 + 0.03 * np.sin(2 * np.pi * 5.5 * t))
    phase = 2 * np.pi * np.cumsum(vibrato) / SR
    envelope = 0.5 * (1 - np.cos(2 * np.pi * np.clip(t / t[-1], 0, 1)))
    return _stereo(0.4 * np.sin(phase) * envelope)


@pytest.fixture
def band(t):
    return _stereo(0.25 * np.sin(2 * np.pi * 110 * t))


def test_mode_a_when_vocal_present(sung, band):
    report = detect_vocal(sung, sung + band)
    assert report.vocal_present, report.reasons
    assert report.voiced_frac > config.VOCAL_PRESENT_VOICED_FRAC


def test_mode_b_when_stem_is_silent(band):
    report = detect_vocal(np.zeros_like(band), band)
    assert not report.vocal_present
    assert "digital silence" in " ".join(report.reasons)


def test_mode_b_when_stem_is_quiet_bleed(band):
    rng = np.random.default_rng(0)
    bleed = (0.0004 * rng.standard_normal(band.shape)).astype(np.float32)
    report = detect_vocal(bleed, band)
    assert not report.vocal_present


def test_mode_b_when_stem_is_loud_but_unvoiced(band):
    """The case absolute loudness alone would miss: loud, but not singing."""
    rng = np.random.default_rng(1)
    noise = (0.2 * rng.standard_normal(band.shape)).astype(np.float32)
    report = detect_vocal(noise, band + noise)
    assert not report.vocal_present
    assert any("voiced frames" in r for r in report.reasons)


def test_silence_reports_negative_infinity(band):
    assert integrated_lufs(np.zeros_like(band)) == float("-inf")
    assert np.isfinite(integrated_lufs(band))


def test_report_survives_json_round_trip(band):
    import json

    payload = detect_vocal(np.zeros_like(band), band).as_dict()
    assert json.loads(json.dumps(payload))["vocal_present"] is False


def test_mp3_round_trip_preserves_shape_and_rate(tmp_path, band):
    path = audio_io.encode_mp3(tmp_path / "x.mp3", band)
    decoded = audio_io.decode(path)
    assert decoded.dtype == np.float32
    assert decoded.shape[0] == 2
    assert abs(decoded.shape[1] / SR - band.shape[1] / SR) < 0.15


def test_decode_rejects_missing_file(tmp_path):
    with pytest.raises(audio_io.AudioError):
        audio_io.decode(tmp_path / "nope.mp3")
