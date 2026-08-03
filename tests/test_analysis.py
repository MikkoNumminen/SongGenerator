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


def test_report_mentions_the_stage_three_decisions(distinct):
    _, a = distinct
    text = report(a)
    assert "boundary source" in text
    assert "stage-3 cleanup" in text
    assert config.ODD_SLOT_POLICY in text
