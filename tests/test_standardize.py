"""The standardisation pass: trim math, levels, traceability, and the guard.

Nothing here asserts how a clip sounds. That is a listening question and the
pass writes samples to a scratch directory for it. What IS testable is that the
arithmetic is right, that a derivative can be traced back to its source, and
that a source can never be written over -- the last one being the reason the
tier exists at all.
"""

import numpy as np
import pytest

from song_generator import audio_io, config
from song_generator.standardize import (
    StandardizeError, apply_trim, check_destination, find_trim, shift_bounds,
    write_derivative,
)

SR = config.SAMPLE_RATE


def _clip(sound_s: float = 0.5, head_s: float = 0.0, tail_s: float = 0.0,
          amp: float = 0.5, freq: float = 220.0) -> np.ndarray:
    """Silence, then a steady tone, then silence. Edges exactly where stated."""
    t = np.arange(int(SR * sound_s)) / SR
    tone = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    head = np.zeros(int(SR * head_s), dtype=np.float32)
    tail = np.zeros(int(SR * tail_s), dtype=np.float32)
    mono = np.concatenate([head, tone, tail])
    return np.stack([mono, mono])


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------

@pytest.fixture
def bank(tmp_path):
    """A source bank with one clip in it."""
    d = tmp_path / "words_hq"
    d.mkdir()
    audio_io.write_wav(d / "bravo_1.wav", _clip())
    return d


def test_refuses_writing_into_the_source_itself(bank):
    with pytest.raises(StandardizeError, match="is the source bank"):
        check_destination(bank, [bank])


def test_refuses_a_destination_inside_the_source(bank):
    with pytest.raises(StandardizeError, match="is inside the source bank"):
        check_destination(bank / "std", [bank])


def test_refuses_a_destination_containing_the_source(bank):
    with pytest.raises(StandardizeError, match="contains the source bank"):
        check_destination(bank.parent, [bank])


def test_accepts_a_sibling(bank):
    out = bank.with_name(bank.name + config.STD_SUFFIX)
    assert check_destination(out, [bank]) == out.resolve()


def test_guard_runs_before_anything_is_written(bank):
    before = (bank / "bravo_1.wav").read_bytes()
    with pytest.raises(StandardizeError):
        write_derivative(bank, "bravo_1.wav", _clip(amp=0.9), [bank])
    assert (bank / "bravo_1.wav").read_bytes() == before


def test_refuses_a_name_that_climbs_out(bank, tmp_path):
    out = tmp_path / "words_hq.std"
    with pytest.raises(StandardizeError, match="not inside"):
        write_derivative(out, "../escaped.wav", _clip(), [bank])
    assert not (tmp_path / "escaped.wav").exists()


def test_refuses_a_path_listed_as_a_source(bank, tmp_path):
    out = tmp_path / "words_hq.std"
    protected = {(out / "bravo_1.wav").resolve()}
    with pytest.raises(StandardizeError, match="source clip in the manifest"):
        write_derivative(out, "bravo_1.wav", _clip(), [bank], protected=protected)


def test_writes_a_sibling_normally(bank, tmp_path):
    out = tmp_path / "words_hq.std"
    written = write_derivative(out, "bravo_1.wav", _clip(), [bank])
    assert written.is_file()
    assert written.parent.resolve() == out.resolve()


def test_symlinked_destination_pointing_back_is_caught(bank, tmp_path):
    link = tmp_path / "sneaky"
    try:
        link.symlink_to(bank, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need privileges this machine does not grant")
    with pytest.raises(StandardizeError):
        check_destination(link, [bank])


# ---------------------------------------------------------------------------
# Trim
# ---------------------------------------------------------------------------

def _mono(clip):
    return audio_io.to_mono(clip)


def test_trim_leaves_the_guard_in_front_of_the_sound():
    # Head silence kept under STD_HEAD_CAP_S, so the guard is what is measured
    # here rather than the cap. The cap has its own test below.
    trim = find_trim(_mono(_clip(head_s=0.10, tail_s=0.30)))
    assert trim.head_s == pytest.approx(0.10 - config.STD_HEAD_GUARD_S, abs=0.006)
    assert trim.tail_s == pytest.approx(0.30 - config.STD_TAIL_GUARD_S, abs=0.006)


def test_trim_never_reaches_the_sound():
    """The cut must land before the first sample of the tone, always."""
    for head in (0.05, 0.12, 0.4, 1.0):
        trim = find_trim(_mono(_clip(head_s=head, tail_s=0.2)))
        assert trim.head_s < head, f"trimmed into the sound with {head}s of silence"


def test_trim_does_nothing_when_there_is_no_silence():
    trim = find_trim(_mono(_clip(head_s=0.0, tail_s=0.0)))
    assert trim.head_s == 0.0
    assert trim.tail_s == 0.0


def test_head_cap_binds_on_a_long_silence():
    trim = find_trim(_mono(_clip(head_s=2.0, tail_s=0.0)))
    assert trim.head_s == config.STD_HEAD_CAP_S


def test_tail_is_uncapped_because_dead_air_is_dead_air():
    trim = find_trim(_mono(_clip(sound_s=0.6, tail_s=2.0)))
    assert trim.tail_s > 1.5


def test_a_silent_clip_is_passed_through_untouched():
    silence = np.zeros((2, int(SR * 0.5)), dtype=np.float32)
    trim = find_trim(_mono(silence))
    assert trim == find_trim(_mono(silence))
    assert not trim.any


def test_trim_never_takes_a_clip_below_the_word_floor():
    # Almost all silence: an unguarded trim would leave nearly nothing.
    clip = _mono(_clip(sound_s=0.05, head_s=0.5, tail_s=0.5))
    trim = find_trim(clip)
    left = clip.shape[0] / SR - trim.head_s - trim.tail_s
    assert left >= config.WORD_MIN_S - 1e-6


def test_apply_trim_removes_exactly_what_was_asked_for():
    clip = _clip(sound_s=0.5, head_s=0.2, tail_s=0.2)
    out = apply_trim(clip, Trim := find_trim(_mono(clip)))
    expected = clip.shape[1] - int(round(Trim.head_s * SR)) - int(round(Trim.tail_s * SR))
    assert out.shape[1] == expected
    assert out.shape[0] == clip.shape[0]


def test_apply_trim_fades_both_edges_but_not_the_middle():
    clip = _clip(sound_s=0.5)
    out = apply_trim(clip, find_trim(_mono(clip)))
    assert abs(out[0, 0]) < 1e-6
    assert abs(out[0, -1]) < 1e-6
    middle = out[0, out.shape[1] // 2 - 200: out.shape[1] // 2 + 200]
    assert np.abs(middle).max() > 0.4


def test_the_interior_of_a_clip_is_never_touched():
    """A gap in the middle survives, which is what protects a sung transition."""
    t = np.arange(int(SR * 0.4)) / SR
    tone = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    gap = np.zeros(int(SR * 0.12), dtype=np.float32)
    mono = np.concatenate([np.zeros(int(SR * 0.2), dtype=np.float32), tone, gap, tone,
                           np.zeros(int(SR * 0.2), dtype=np.float32)])
    clip = np.stack([mono, mono])

    out = apply_trim(clip, find_trim(mono))
    quiet = np.abs(out[0]) < 1e-3
    # The interior gap is still there: a run of near-silence well inside.
    interior = quiet[int(SR * 0.05): -int(SR * 0.05)]
    assert interior.sum() > int(SR * 0.10)


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------

def test_bounds_shift_by_the_head_trim():
    assert shift_bounds([0.30, 0.60, 0.90], 0.05, 1.5) == [0.25, 0.55, 0.85]


def test_bounds_keep_their_count_even_when_crushed():
    """Count is what tells the mapper how many syllables the clip holds."""
    out = shift_bounds([0.01, 0.02, 0.03], 0.10, 0.50)
    assert len(out) == 3


def test_bounds_stay_ordered_and_inside_the_clip():
    out = shift_bounds([0.01, 0.02, 0.9, 1.4], 0.08, 1.0)
    assert out == sorted(out)
    assert all(0.0 < b < 1.0 for b in out)


def test_bounds_survive_a_zero_trim_unchanged():
    assert shift_bounds([0.2, 0.4], 0.0, 1.0) == [0.2, 0.4]


def test_no_bounds_stays_no_bounds():
    assert shift_bounds([], 0.05, 1.0) == []


def test_bounds_are_consistent_with_the_trimmed_clip():
    """The invariant load_bank depends on: 0 < every bound < duration_s."""
    clip = _clip(sound_s=1.2, head_s=0.15, tail_s=0.3)
    trim = find_trim(_mono(clip))
    out = apply_trim(clip, trim)
    duration_s = out.shape[1] / SR

    bounds = shift_bounds([0.30, 0.60, 0.90], trim.head_s, duration_s)
    assert len(bounds) == 3
    assert bounds == sorted(bounds)
    assert all(0.0 < b < duration_s for b in bounds)
    # And the spans they imply are all real spans, which is what
    # Unit.syllable_spans builds.
    edges = [0.0] + bounds + [duration_s]
    assert all(b > a for a, b in zip(edges[:-1], edges[1:]))
