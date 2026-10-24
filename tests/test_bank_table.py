"""The bank table and its default, as a local override leaves them.

The real banks are registered in a gitignored vocabulary_local.py, which may
set BANKS without DEFAULT_BANK. argparse never checks a default against its
choices, so a default the table does not hold used to surface as a KeyError on
every run without --bank.
"""

import importlib
import importlib.abc
import importlib.machinery
import sys
import types

import pytest

from song_generator import config
from song_generator.config import resolve_banks

LOCAL = "song_generator.vocabulary_local"


def test_a_named_default_is_kept_and_listed_first():
    banks, default = resolve_banks({"a": "words_a", "b": "words_b"}, "b",
                                   {"BANKS": ..., "DEFAULT_BANK": "b"})
    assert default == "b"
    assert list(banks) == ["b", "a"]
    assert banks == {"a": "words_a", "b": "words_b"}


def test_an_override_naming_no_default_takes_its_first_bank():
    # Even when the shipped placeholder's name is among its banks: the
    # placeholder was inherited, not chosen.
    banks, default = resolve_banks({"mine": "words_mine", "example": "words"},
                                   "example", {"BANKS": ...})
    assert default == "mine"
    assert list(banks) == ["mine", "example"]


def test_a_named_default_the_table_lacks_is_refused():
    with pytest.raises(ValueError, match="DEFAULT_BANK 'z'"):
        resolve_banks({"x": "words_x", "y": "words_y"}, "z",
                      {"BANKS": ..., "DEFAULT_BANK": "z"})


def test_a_table_with_no_bank_is_refused():
    with pytest.raises(ValueError, match="no bank"):
        resolve_banks({}, "example", {"BANKS": {}})


@pytest.fixture
def reload_config(monkeypatch):
    """Reload config with the local override on, then put it back as it was."""
    monkeypatch.delenv("SONG_GENERATOR_NO_LOCAL_VOCAB", raising=False)
    yield lambda: importlib.reload(config)
    monkeypatch.setenv("SONG_GENERATOR_NO_LOCAL_VOCAB", "1")
    sys.modules.pop(LOCAL, None)
    importlib.reload(config)


def test_the_override_s_banks_reach_the_table(reload_config, monkeypatch):
    local = types.ModuleType(LOCAL)
    local.BANKS = {"mine": "words_mine", "spare": "words_spare"}
    monkeypatch.setitem(sys.modules, LOCAL, local)

    reload_config()

    assert config.BANKS == {"mine": "words_mine", "spare": "words_spare"}
    assert config.DEFAULT_BANK == "mine"


class _Broken(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """A vocabulary_local.py that exists and fails inside, on a missing import."""

    def find_spec(self, name, path=None, target=None):
        if name == LOCAL:
            return importlib.machinery.ModuleSpec(name, self)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        raise ModuleNotFoundError("No module named 'not_installed'",
                                  name="not_installed")


def test_an_override_that_fails_inside_is_not_mistaken_for_none(reload_config, monkeypatch):
    sys.modules.pop(LOCAL, None)
    finder = _Broken()
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])

    with pytest.raises(ModuleNotFoundError, match="not_installed"):
        reload_config()
