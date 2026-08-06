"""The Roformer batch pass, without the Roformer.

The model itself is an optional dependency and takes minutes to load, so
these drive main() with a stand-in separator. What they pin is the batch
shape: the model is loaded once for the whole run rather than once per
source, which is what the loop used to pay for.
"""

from pathlib import Path

import numpy as np

from song_generator import audio_io, config, separate_hq


class _FakeSeparator:
    def __init__(self, staging):
        self.staging = Path(staging)

    def separate(self, path):
        name = Path(path).stem + "_(Vocals)_model.wav"
        audio_io.write_wav(self.staging / name,
                           np.zeros((2, 512), dtype=np.float32))
        return [name]


def _sources(tmp_path, n=2):
    out = []
    for i in range(n):
        p = tmp_path / f"song{i}.mp4"
        p.write_bytes(b"x")
        out.append(str(p))
    return out


def test_the_model_is_loaded_once_for_the_whole_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORK_DIR", str(tmp_path / "work"))

    made = []

    def fake_make(staging):
        made.append(staging)
        return _FakeSeparator(staging)

    monkeypatch.setattr(separate_hq, "make_separator", fake_make)

    code = separate_hq.main(_sources(tmp_path))

    assert code == 0
    assert len(made) == 1, "the model was loaded per source file"
    for i in range(2):
        assert (tmp_path / "work" / f"song{i}" / "vocal_hq.wav").is_file()


def test_sources_already_done_do_not_load_the_model_at_all(tmp_path, monkeypatch):
    """A re-run over finished work must stay free: the skip happens before
    the model is ever built."""
    monkeypatch.setattr(config, "WORK_DIR", str(tmp_path / "work"))
    for i in range(2):
        audio_io.write_wav(tmp_path / "work" / f"song{i}" / "vocal_hq.wav",
                           np.zeros((2, 512), dtype=np.float32))

    def exploding_make(staging):
        raise AssertionError("nothing needed separating")

    monkeypatch.setattr(separate_hq, "make_separator", exploding_make)

    assert separate_hq.main(_sources(tmp_path)) == 0


def test_cleanup_leaves_another_run_s_stems_alone(tmp_path, monkeypatch):
    """Staging is shared, so the sweep must name what it removes.

    The model loads once now, which meant one staging directory for the whole
    batch. Deleting every wav in it would delete a concurrent run's stems in
    the gap between its separator writing them and its copy reading them, and
    that run would find no vocal, return None, and be counted neither done nor
    failed.
    """
    monkeypatch.setattr(config, "WORK_DIR", str(tmp_path / "work"))
    staging = tmp_path / "staging"
    staging.mkdir()

    stranger = staging / "someone_elses_(Vocals)_model.wav"
    audio_io.write_wav(stranger, np.zeros((2, 256), dtype=np.float32))

    source = tmp_path / "mine.mp4"
    source.write_bytes(b"x")

    out = separate_hq.separate_one(source, _FakeSeparator(staging), staging)

    assert out is not None and out.is_file(), "this run must still succeed"
    assert stranger.is_file(), (
        "the sweep removed a file this call did not produce, which is the "
        "concurrent-run failure the named cleanup exists to prevent"
    )
    assert not list(staging.glob("mine_*")), "its own stems are still cleaned up"


class TestForBankStillTakesSources:
    """--for-bank is a filter over the sources you pass, not a way to find
    them. The bank records which work directories its clips separated into,
    not where the source media lives, so the module cannot invent the paths.

    The docstring used to show a bare `--for-bank` invocation, which printed
    "nothing to separate" and exited 2 before the flag was ever consulted.
    """

    def test_the_documented_invocations_all_carry_sources(self):
        examples = [line.strip() for line in separate_hq.__doc__.splitlines()
                    if "python -m song_generator.separate_hq" in line]
        assert examples, "the docstring shows how to run this"
        for example in examples:
            tail = example.split("separate_hq", 1)[1]
            positional = [a for a in tail.split() if not a.startswith("--")]
            assert positional, f"documented with nothing to separate: {example}"

    def test_bare_for_bank_says_what_is_missing_before_opening_the_bank(
            self, tmp_path, capsys):
        """The generic "nothing to separate" hid the real problem. And the
        answer is knowable without paying for correlation over the bank, so
        it must arrive before that starts."""
        code = separate_hq.main(["--for-bank", "--bank", str(tmp_path)])
        assert code == 2
        err = capsys.readouterr().err
        assert "--for-bank" in err, "the flag at fault is named"
        assert "separate_hq --for-bank" in err, "a working invocation is shown"

    def test_for_bank_filters_to_what_the_bank_was_cut_from(
            self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "WORK_DIR", str(tmp_path / "work"))
        monkeypatch.setattr(separate_hq, "sources_needed_by_bank",
                            lambda bank: {"song0"})
        monkeypatch.setattr(separate_hq, "make_separator",
                            lambda staging: _FakeSeparator(staging))

        code = separate_hq.main(["--for-bank", *_sources(tmp_path)])

        assert code == 0
        assert (tmp_path / "work" / "song0" / "vocal_hq.wav").is_file()
        assert not (tmp_path / "work" / "song1" / "vocal_hq.wav").exists(), (
            "a source the bank was not cut from is not paid for"
        )

    def test_for_bank_with_no_matching_sources_says_so(
            self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(separate_hq, "sources_needed_by_bank",
                            lambda bank: {"somethingelse"})
        code = separate_hq.main(["--for-bank", *_sources(tmp_path)])
        assert code == 2
        assert "none of the given sources" in capsys.readouterr().err
