"""Stage 2 against synthesised singing with known ground truth.

The repeated-note case is the important one. Two syllables sung on the same
pitch produce no movement in the F0 contour at all, so if the onset detector
stops contributing they merge silently and every word after that point lands in
the wrong place. That failure is invisible in aggregate accuracy numbers, so it
gets its own test.
"""

import json

import numpy as np
import pytest
from scipy.signal import lfilter

from luokkaretki import config
from luokkaretki.analysis import (
    Analysis, analyse, hz_to_midi, midi_to_hz, note_name, report,
)

SR = config.SAMPLE_RATE
SYL = 0.42


def _formant(x, f, bw):
    r = np.exp(-np.pi * bw / SR)
    theta = 2 * np.pi * f / SR
    return lfilter([1 - r], [1, -2 * r * np.cos(theta), r * r], x)


def sing(midi_notes, syl_dur=SYL, gap=0.0):
    """Source-filter synthesis of a sung line: glottal saw through formants."""
    vowels = [(730, 1090), (270, 2290), (300, 870)]
    out = []
    for i, m in enumerate(midi_notes):
        n = int(SR * syl_dur)
        t = np.arange(n) / SR
        f0 = 440 * 2 ** ((m - 69) / 12)
        phase = 2 * np.pi * np.cumsum(np.full(n, f0)) / SR
        src = sum(np.sin(k * phase) / k for k in range(1, 40))
        f1, f2 = vowels[i % len(vowels)]
        sig = _formant(_formant(_formant(src, f1, 80), f2, 110), 2800, 160)
        env = np.minimum(1, t / 0.03) * np.exp(-t * 1.2)
        env[int(n * 0.88):] *= np.linspace(1, 0, n - int(n * 0.88))
        out.append(sig * env)
        if gap:
            out.append(np.zeros(int(SR * gap)))
    y = np.concatenate(out)
    return np.stack([y, y]).astype(np.float32) / (np.abs(y).max() + 1e-9)


def _match_pitches(analysis, truth, syl_dur=SYL, gap=0.0):
    """Pitch error for each true syllable, matched by nearest onset."""
    errors = []
    for i, m in enumerate(truth):
        expected = i * (syl_dur + gap)
        near = [n for n in analysis.notes if abs(n.onset_s - expected) < syl_dur / 2]
        if near:
            best = min(near, key=lambda n: abs(n.onset_s - expected))
            errors.append(best.midi - m)
    return np.array(errors)


def test_midi_hz_round_trip():
    assert midi_to_hz(69) == pytest.approx(440.0)
    assert hz_to_midi(440.0) == pytest.approx(69.0)
    assert hz_to_midi(midi_to_hz(53.7)) == pytest.approx(53.7)
    assert note_name(69) == "A4"
    assert note_name(60) == "C4"


@pytest.fixture(scope="module")
def distinct():
    melody = [67, 69, 71, 69, 67]
    return melody, analyse(sing(melody))


def test_finds_every_syllable(distinct):
    melody, a = distinct
    errors = _match_pitches(a, melody)
    assert len(errors) == len(melody), "a syllable went unmatched"


def test_pitch_is_accurate(distinct):
    melody, a = distinct
    errors = _match_pitches(a, melody)
    assert np.abs(errors).max() < 0.5, f"worst pitch error {np.abs(errors).max():.3f} semitones"


def test_repeated_notes_still_produce_separate_slots():
    """No pitch movement here at all -- only the onset detector can see these."""
    melody = [67, 67, 67, 67]
    a = analyse(sing(melody))
    errors = _match_pitches(a, melody)
    assert len(errors) == len(melody), (
        f"only matched {len(errors)}/{len(melody)} repeated notes -- "
        "the onset detector is no longer contributing boundaries"
    )
    from_onset = [n for n in a.notes if n.source in ("onset", "both")]
    assert from_onset, "no boundary came from onset detection"


def test_silence_between_phrases_splits_them():
    melody = [67, 69]
    a = analyse(sing(melody, gap=config.PHRASE_GAP_S * 2))
    assert len(a.phrases) >= 2, f"expected a phrase break, got {len(a.phrases)}"
    assert all(n.phrase >= 0 for n in a.notes), "a note was left unassigned to a phrase"


def test_notes_are_ordered_and_non_overlapping(distinct):
    _, a = distinct
    for prev, nxt in zip(a.notes, a.notes[1:]):
        assert nxt.onset_s >= prev.onset_s
        assert prev.offset_s <= nxt.onset_s + 1e-6
        assert prev.dur_s > 0


def test_silence_yields_no_notes():
    a = analyse(np.zeros((2, SR * 2), dtype=np.float32))
    assert a.notes == []
    assert "no sung notes found" in report(a)


def test_analysis_json_round_trip(tmp_path, distinct):
    _, a = distinct
    path = a.to_json(tmp_path / "analysis.json")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["notes"] and "f0" in loaded
    assert {"onset_s", "dur_s", "midi", "midi_q", "conf", "phrase", "source"} <= set(loaded["notes"][0])

    slim = json.loads(Analysis.to_json(a, tmp_path / "slim.json", include_f0=False)
                      .read_text(encoding="utf-8"))
    assert "f0" not in slim


class TestRegressionsFromTheRealScene:
    """Both of these passed every synthetic test and still shredded a real vocal.

    On the source scene, 64 of 96 detected notes were the start of their own
    voiced run and the median note was 90 ms -- sustained singing was coming out
    as a burst of fragments. These pin the two causes.
    """

    def test_brief_voicing_dropout_does_not_split_a_note(self):
        """A consonant or breath mid-note must not end it."""
        from luokkaretki.analysis import bridge_voicing_gaps

        hop = 0.01
        hz = np.full(200, 220.0)
        voiced = np.ones(200, dtype=bool)
        hz[100:104] = np.nan          # 40 ms dropout, well inside the note
        voiced[100:104] = False

        filled_hz, filled_voiced = bridge_voicing_gaps(hz, voiced, hop)
        assert filled_voiced[100:104].all(), "short dropout was not bridged"
        assert np.isfinite(filled_hz[100:104]).all(), "bridged frames left as NaN"
        assert filled_hz[101] == pytest.approx(220.0, abs=1.0), "bridge did not interpolate"

    def test_real_silence_still_ends_a_note(self):
        from luokkaretki.analysis import bridge_voicing_gaps

        hop = 0.01
        hz = np.full(200, 220.0)
        voiced = np.ones(200, dtype=bool)
        hz[80:150] = np.nan           # 700 ms -- a genuine rest
        voiced[80:150] = False

        _, filled_voiced = bridge_voicing_gaps(hz, voiced, hop)
        assert not filled_voiced[80:150].any(), "a real rest was bridged away"

    def test_leading_silence_is_not_bridged(self):
        """Nothing precedes it, so there is no note to continue."""
        from luokkaretki.analysis import bridge_voicing_gaps

        hz = np.full(100, 220.0)
        voiced = np.ones(100, dtype=bool)
        hz[:3] = np.nan
        voiced[:3] = False

        _, filled = bridge_voicing_gaps(hz, voiced, 0.01)
        assert not filled[:3].any()

    def test_pitch_between_two_semitones_stays_one_note(self):
        """The scene sits at MIDI 53.5, where rounding flips F3/F#3 endlessly."""
        midi = 53.5
        hz = 440.0 * 2 ** ((midi - 69) / 12)
        t = np.arange(int(SR * 1.2)) / SR
        rng = np.random.default_rng(3)
        # Vibrato plus tracker-scale jitter, straddling the semitone boundary.
        f0 = hz * (1 + 0.004 * np.sin(2 * np.pi * 5.0 * t) + 0.002 * rng.standard_normal(len(t)))
        phase = 2 * np.pi * np.cumsum(f0) / SR
        src = sum(np.sin(k * phase) / k for k in range(1, 30))
        env = np.minimum(1, t / 0.03) * np.minimum(1, (t[-1] - t) / 0.05)
        audio = np.stack([src * env, src * env]).astype(np.float32)
        audio /= np.abs(audio).max()

        a = analyse(audio)
        assert len(a.notes) <= 3, (
            f"one steady note between two semitones fragmented into {len(a.notes)} "
            "-- the splitter is quantising to a semitone grid again"
        )
        assert all(abs(n.midi - midi) < 0.6 for n in a.notes)


def test_report_mentions_the_stage_three_decisions(distinct):
    _, a = distinct
    text = report(a)
    assert "boundary source" in text
    assert "stage-3 cleanup" in text
    assert config.ODD_SLOT_POLICY in text
