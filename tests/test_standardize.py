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
    StandardizeError, check_destination, write_derivative,
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
