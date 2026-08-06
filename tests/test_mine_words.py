"""Mining candidates must stay reviewable even when a run dies halfway.

labels.tsv used to be written only after every clip had been cut, so an
interruption left a folder of candidate wavs with no labels file to review
them against. The file now lands whatever happens to the cutting: rows for
the clips that were cut carry their filenames, rows for the rest are still
there with their timings.
"""

import numpy as np
import pytest

from song_generator import audio_io, mine_words
from song_generator.extract_words import Candidate


def _candidate(i, start):
    return Candidate(i=i, start_s=start, end_s=start + 0.4, dur_s=0.4,
                     n_syllables=2, midi=53.0, rms_db=-20.0)


class _FakeStems:
    vocal = np.zeros((2, 4410), dtype=np.float32)


def test_labels_survive_a_cut_dying_halfway(tmp_path, monkeypatch):
    candidates = [_candidate(1, 0.0), _candidate(2, 1.0)]

    monkeypatch.setattr(mine_words, "separate",
                        lambda path, work, device=None: _FakeStems())
    monkeypatch.setattr(mine_words, "work_dir_for", lambda path: tmp_path / "wk")
    monkeypatch.setattr(mine_words, "find_candidates",
                        lambda *args, **kwargs: candidates)
    monkeypatch.setattr(mine_words, "cut",
                        lambda vocal, c: np.zeros((2, 512), dtype=np.float32))

    real_write = audio_io.write_wav
    calls = {"n": 0}

    def dying_write(path, audio):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk gone mid-run")
        return real_write(path, audio)

    monkeypatch.setattr(mine_words.audio_io, "write_wav", dying_write)

    from pathlib import Path

    with pytest.raises(OSError):
        mine_words.mine_one(Path("fake_source.mp4"), tmp_path / "out",
                            "cpu", None)

    labels = tmp_path / "out" / "fake_source" / "labels.tsv"
    assert labels.is_file(), "candidates with no labels file are unreviewable"

    rows = [line for line in labels.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith(("#", "word"))]
    assert len(rows) == 2, "every candidate keeps its row, cut or not"
    assert "c01__" in rows[0], "the clip that was cut is named in its row"
    assert rows[1].endswith("\t"), "the clip that was not cut has no filename yet"


def test_labels_are_written_once_when_nothing_goes_wrong(tmp_path, monkeypatch):
    """The ordinary run keeps its shape: clips first, labels landing last."""
    candidates = [_candidate(1, 0.0)]

    monkeypatch.setattr(mine_words, "separate",
                        lambda path, work, device=None: _FakeStems())
    monkeypatch.setattr(mine_words, "work_dir_for", lambda path: tmp_path / "wk")
    monkeypatch.setattr(mine_words, "find_candidates",
                        lambda *args, **kwargs: candidates)
    monkeypatch.setattr(mine_words, "cut",
                        lambda vocal, c: np.zeros((2, 512), dtype=np.float32))

    from pathlib import Path

    result = mine_words.mine_one(Path("fake_source.mp4"), tmp_path / "out",
                                 "cpu", None)

    assert result.candidates == 1
    folder = tmp_path / "out" / "fake_source"
    assert (folder / "labels.tsv").is_file()
    assert candidates[0].path is not None
    assert candidates[0].path.name in (folder / "labels.tsv").read_text(encoding="utf-8")
