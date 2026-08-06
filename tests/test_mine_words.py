"""Mining candidates must stay reviewable even when a run dies halfway.

labels.tsv used to be written only after every clip had been cut, so an
interruption left a folder of candidate wavs with no labels file to review
them against. The file now lands whatever happens to the cutting: rows for
the clips that were cut carry their filenames, rows for the rest are still
there with their timings.

The other half of the same bargain: a labels.tsv already on disk may carry
hand-typed words from an earlier review, so an interrupted re-run must not
replace it with fresh auto rows. Those go to a partial file beside it.
"""

from pathlib import Path

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

    result = mine_words.mine_one(Path("fake_source.mp4"), tmp_path / "out",
                                 "cpu", None)

    assert result.candidates == 1
    folder = tmp_path / "out" / "fake_source"
    assert (folder / "labels.tsv").is_file()
    assert candidates[0].path is not None
    assert candidates[0].path.name in (folder / "labels.tsv").read_text(encoding="utf-8")


def _rig_a_dying_cut(tmp_path, monkeypatch):
    """mine_one wired to die on its second clip, like the first test does."""
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
    return tmp_path / "out" / "fake_source"


def test_an_interrupted_rerun_leaves_a_hand_edited_labels_file_alone(
        tmp_path, monkeypatch, capsys):
    """docs/DATA-FORMATS.md says people type words into this file by hand.

    A re-run over an already-reviewed folder used to write labels.tsv from
    its unwind path, replacing that hand work with fresh auto rows. The
    partial rows now land beside it, and the run says where.
    """
    folder = _rig_a_dying_cut(tmp_path, monkeypatch)
    folder.mkdir(parents=True)
    hand_edited = "word\tvariant\tstart\tend\tsyl\tpitch\tcandidate\nbravo\t\t0.1\t0.5\t2\tF3\tc01.wav\n"
    (folder / "labels.tsv").write_text(hand_edited, encoding="utf-8")

    with pytest.raises(OSError):
        mine_words.mine_one(Path("fake_source.mp4"), tmp_path / "out",
                            "cpu", None)

    assert (folder / "labels.tsv").read_text(encoding="utf-8") == hand_edited, (
        "the hand-edited file survives the unwind untouched"
    )
    partial = folder / "labels.partial.tsv"
    assert partial.is_file(), "the partial rows still land, just not on top"
    rows = [line for line in partial.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith(("#", "word"))]
    assert len(rows) == 2, "every candidate keeps its row, cut or not"

    err = capsys.readouterr().err
    assert "labels.partial.tsv" in err, "the run says where the rows went"
    assert "labels.tsv" in err, "and why they did not land on labels.tsv"


def test_a_second_interrupted_run_does_not_clobber_the_first_partial(
        tmp_path, monkeypatch):
    folder = _rig_a_dying_cut(tmp_path, monkeypatch)
    folder.mkdir(parents=True)
    (folder / "labels.tsv").write_text("hand work\n", encoding="utf-8")
    (folder / "labels.partial.tsv").write_text("first interruption\n",
                                               encoding="utf-8")

    with pytest.raises(OSError):
        mine_words.mine_one(Path("fake_source.mp4"), tmp_path / "out",
                            "cpu", None)

    assert (folder / "labels.partial.tsv").read_text(encoding="utf-8") == \
        "first interruption\n"
    assert (folder / "labels.partial2.tsv").is_file()


def test_a_failing_labels_write_does_not_mask_why_the_cut_died(
        tmp_path, monkeypatch, capsys):
    """The exception worth reading is the one that stopped the cut. A labels
    write failing during the unwind used to replace it, so the report said
    nothing about the disk and everything about a tsv nobody asked about."""
    folder = _rig_a_dying_cut(tmp_path, monkeypatch)

    def failing_write_labels(path, candidates):
        raise PermissionError("labels file is locked")

    monkeypatch.setattr(mine_words, "write_labels", failing_write_labels)

    with pytest.raises(OSError, match="disk gone mid-run"):
        mine_words.mine_one(Path("fake_source.mp4"), tmp_path / "out",
                            "cpu", None)

    assert "labels file is locked" in capsys.readouterr().err, (
        "the write failure is reported rather than swallowed"
    )
