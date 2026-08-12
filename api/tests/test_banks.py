"""A bank the front end cannot render must never look ready to render.

The picker is built from this, so the distinctions here are the ones that
decide whether pressing go works: named but not built, built but empty, built
but unreadable, and built with a standardised tier beside it.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.banks import catalog, inspect

SUFFIX = ".std"


def _build(directory: Path, clips: int = 3) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    index = {f"raw_{i:04d}.wav": {"words": ["raw"]} for i in range(clips)}
    (directory / "words.json").write_text(json.dumps(index), encoding="utf-8")
    return directory


def test_a_bank_that_was_never_built_is_reported_not_faulted(tmp_path):
    """The state of a fresh clone. The clips are gitignored, so every
    configured bank names an empty directory, and calling that an error would
    make a correct checkout look broken."""
    info = inspect("ppbank", tmp_path / "words_hq", SUFFIX)

    assert info.built is False
    assert info.problem is None, "not built yet is not a fault"
    assert info.usable is False


def test_a_built_bank_reports_how_many_clips_it_holds(tmp_path):
    info = inspect("ppbank", _build(tmp_path / "words_hq", clips=25), SUFFIX)

    assert info.built is True
    assert info.units == 25
    assert info.usable is True


def test_an_empty_index_is_built_but_not_usable(tmp_path):
    """A bank whose index parses and holds nothing renders nothing. It has to
    read as unusable, or the picker offers it and the run fails at the end."""
    info = inspect("ppbank", _build(tmp_path / "words_hq", clips=0), SUFFIX)

    assert info.built is True
    assert info.units == 0
    assert info.usable is False


def test_an_unreadable_index_says_so_rather_than_reading_as_empty(tmp_path):
    directory = tmp_path / "words_hq"
    directory.mkdir()
    (directory / "words.json").write_text("{ this is not json", encoding="utf-8")

    info = inspect("ppbank", directory, SUFFIX)

    assert info.built is True
    assert info.problem is not None
    assert "json" in info.problem.lower()
    assert info.usable is False, "a bank nobody can read is not a bank to offer"


def test_the_standardised_tier_beside_a_bank_is_noticed(tmp_path):
    """A render prefers the tier when it exists, so the front end has to be
    able to say which audio would actually be sung."""
    _build(tmp_path / "words_hq")
    plain = inspect("ppbank", tmp_path / "words_hq", SUFFIX)
    assert plain.standardised is False

    _build(tmp_path / ("words_hq" + SUFFIX))
    with_tier = inspect("ppbank", tmp_path / "words_hq", SUFFIX)
    assert with_tier.standardised is True


def test_the_catalog_keeps_the_configured_order(tmp_path):
    """The configuration names the default first. Sorting would put a bank
    somebody else has never heard of at the top of the picker."""
    for name in ("words_hq", "words_muslim", "words_chaos"):
        _build(tmp_path / name)

    banks = {"ppbank": "words_hq", "muslimbank": "words_muslim",
             "chaos": "words_chaos"}
    got = catalog(banks, tmp_path, SUFFIX)

    assert [b.name for b in got] == ["ppbank", "muslimbank", "chaos"]


def test_the_catalog_can_be_entirely_unbuilt(tmp_path):
    """A fresh clone. Every bank is configured, none is built, and the answer
    is a list of unusable banks rather than an exception."""
    banks = {"ppbank": "words_hq", "chaos": "words_chaos"}

    got = catalog(banks, tmp_path, SUFFIX)

    assert len(got) == 2
    assert all(not b.built for b in got)
    assert all(b.problem is None for b in got)
    assert not any(b.usable for b in got)


def test_reading_the_catalog_does_not_open_the_audio(tmp_path, monkeypatch):
    """Loading a bank's clips reads every wav in it. The front end asks for
    this list on every page load, so it must stay an index read."""
    _build(tmp_path / "words_hq")
    (tmp_path / "words_hq" / "raw_0000.wav").write_bytes(b"not really audio")

    opened: list[str] = []
    real_open = Path.open

    def watched(self, *a, **kw):
        opened.append(self.name)
        return real_open(self, *a, **kw)

    monkeypatch.setattr(Path, "open", watched)
    catalog({"ppbank": "words_hq"}, tmp_path, SUFFIX)

    assert not any(name.endswith(".wav") for name in opened), opened
