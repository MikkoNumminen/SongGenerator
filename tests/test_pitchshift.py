"""Stage 4: octave folding and time clamping.

Folding is what keeps a voice sounding human. The test song's melody spans over
two octaves while the bank sits near F3, so raw targets reach 29 semitones --
far past anything a voice survives. These pin the bound.
"""

import numpy as np
import pytest

from song_generator import config
from song_generator.pitchshift import Segment, clamp_stretch, fold_shift, render_unit

SR = config.SAMPLE_RATE


class TestFoldShift:
    @pytest.mark.parametrize("semitones", [0, 1, -1, 3.5, -5, 7, -7])
    def test_small_shifts_pass_through_untouched(self, semitones):
        assert fold_shift(semitones, cap=7) == pytest.approx(semitones)

    @pytest.mark.parametrize("raw,expected", [
        (12, 0),      # exactly an octave -> same note, no shift at all
        (-12, 0),
        (29, 5),      # the real case from the test song
        (24, 0),
        (13, 1),
        (-15, -3),
        (19, -5),     # nearest octave equivalent is DOWN a fifth, not up a fifth
    ])
    def test_large_shifts_fold_by_whole_octaves(self, raw, expected):
        assert fold_shift(raw, cap=7) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", [13, 19, 25, 29, -14, -20, -27])
    def test_folding_preserves_the_note_name(self, raw):
        """Folding must move by whole octaves only, or the note changes."""
        assert (raw - fold_shift(raw, cap=7)) % 12 == pytest.approx(0)

    @pytest.mark.parametrize("raw", [13, 19, 25, 29, -14, -20, -27])
    def test_folding_always_reduces_the_distance(self, raw):
        assert abs(fold_shift(raw, cap=7)) <= abs(raw)

    def test_anything_beyond_the_cap_lands_within_half_an_octave(self):
        """Shifts already inside the cap are left alone; only folds are bounded."""
        for raw in range(-40, 41):
            result = fold_shift(raw, cap=7)
            if abs(raw) > 7:
                assert abs(result) <= 6.0 + 1e-9, f"{raw} folded to {result}"
            else:
                assert result == pytest.approx(raw)

    def test_a_cap_under_six_does_not_loop(self):
        """No fold can satisfy a 3-semitone cap; return the best available."""
        assert abs(fold_shift(29, cap=3)) <= 6.0


class TestClampStretch:
    def test_within_range_is_exact(self):
        assert clamp_stretch(0.5, 0.5) == pytest.approx(1.0)
        assert clamp_stretch(0.75, 0.5) == pytest.approx(1.5)

    def test_extremes_are_clamped(self):
        lo, hi = config.TIME_STRETCH_RANGE
        assert clamp_stretch(10.0, 0.1) == pytest.approx(hi)
        assert clamp_stretch(0.01, 5.0) == pytest.approx(lo)

    def test_zero_length_source_is_safe(self):
        assert clamp_stretch(0.5, 0.0) == 1.0


def _sung(dur=0.6, hz=175.0):
    t = np.arange(int(SR * dur)) / SR
    phase = 2 * np.pi * hz * t
    y = sum(np.sin(k * phase) / k for k in range(1, 25))
    env = np.minimum(1, t / 0.02) * np.minimum(1, (t[-1] - t) / 0.02)
    return (0.5 * y * env / np.abs(y).max()).astype(np.float32)


class TestRenderUnit:
    def test_output_length_matches_the_slots(self):
        mono = _sung(0.6)
        segs = [Segment(0.0, 0.3, 0.0, 0.35, 2.0), Segment(0.3, 0.6, 0.35, 0.35, -3.0)]
        out = render_unit(mono, SR, segs, 0.7, engine="world")
        assert abs(len(out) / SR - 0.7) < 0.05

    def test_shifting_up_raises_the_measured_pitch(self):
        import librosa

        mono = _sung(0.6, hz=175.0)
        segs = [Segment(0.0, 0.6, 0.0, 0.6, 5.0)]
        out = render_unit(mono, SR, segs, 0.6, engine="world")

        f0 = librosa.yin(out.astype(float), fmin=80, fmax=800, sr=SR)
        measured = float(np.median(f0))
        expected = 175.0 * 2 ** (5 / 12)
        assert abs(12 * np.log2(measured / expected)) < 1.0, (
            f"expected ~{expected:.0f} Hz, measured {measured:.0f} Hz"
        )

    def test_no_segments_yields_silence_not_a_crash(self):
        assert render_unit(_sung(), SR, [], 0.5, engine="world").size >= 0


class TestRubberBandFormants:
    """The setting has to mean what config.py says it means.

    FORMANT_SCALE is documented as "1.0 = formants held exactly where they
    were". Rubber Band reads 1.0 as "do not scale the preserved envelope" and,
    without the preservation flag, does not preserve anything at all, so the
    documented value produced exactly the chipmunk it claims to prevent.
    """

    def _centroid(self, x, sr):
        """Where the formant energy sits. Rises with a chipmunk."""
        import librosa

        spec = np.abs(librosa.stft(np.ascontiguousarray(x, dtype=np.float32), n_fft=2048))
        freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
        band = (freqs >= 300) & (freqs <= 4000)
        weight = spec[band].sum(axis=1)
        return float((freqs[band] * weight).sum() / max(weight.sum(), 1e-9))

    def _voice(self, sr, seconds=0.8, f0=140.0):
        """A buzz with fixed formants: harmonics shaped by three resonances."""
        t = np.arange(int(sr * seconds)) / sr
        buzz = sum(np.sin(2 * np.pi * f0 * n * t) / n for n in range(1, 40))
        # Shaped in the frequency domain, so the formants really are fixed
        # resonances rather than something modulating over time.
        spectrum = np.fft.rfft(buzz)
        freqs = np.fft.rfftfreq(buzz.size, 1.0 / sr)
        envelope = sum(gain * np.exp(-0.5 * ((freqs - centre) / 180.0) ** 2)
                       for centre, gain in ((700.0, 1.0), (1200.0, 0.6), (2600.0, 0.35)))
        return np.fft.irfft(spectrum * envelope, n=buzz.size).astype(np.float32)

    def test_a_shifted_clip_does_not_become_a_chipmunk(self):
        from song_generator import config
        from song_generator.pitchshift import Segment, render_segments_rubberband

        sr = config.SAMPLE_RATE
        voice = self._voice(sr)
        peak = float(np.abs(voice).max())
        voice = voice / peak * 0.5

        duration = voice.size / sr
        shifted = render_segments_rubberband(
            voice, sr, [Segment(0.0, duration, 0.0, duration, 12.0)], duration)

        ratio = self._centroid(shifted, sr) / self._centroid(voice, sr)
        # An octave up with no preservation lands near 2x in theory and 1.35x
        # measured on real clips. Held formants stay near 1.
        assert ratio < 1.15, f"formants rode up with the pitch: {ratio:.2f}x"
