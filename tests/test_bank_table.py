"""The bank table and its default, as a local override leaves them.

The real banks are registered in a gitignored vocabulary_local.py, which may
set BANKS without DEFAULT_BANK. argparse never checks a default against its
choices, so a default the table does not hold used to surface as a KeyError on
every run without --bank.
"""

from song_generator import config
from song_generator.config import default_first


def test_a_named_default_is_kept_and_listed_first():
    banks, default = default_first({"a": "words_a", "b": "words_b"}, "b")
    assert default == "b"
    assert list(banks) == ["b", "a"]
    assert banks == {"a": "words_a", "b": "words_b"}


def test_banks_without_their_default_take_the_first():
    # The shipped placeholder default, left behind by an override that set
    # BANKS alone.
    banks, default = default_first({"mine": "words_mine", "spare": "words_spare"}, "example")
    assert default == "mine"
    assert list(banks) == ["mine", "spare"]


def test_an_empty_table_is_left_alone():
    assert default_first({}, "example") == ({}, "example")


def test_the_active_table_holds_its_default_at_the_top():
    assert config.DEFAULT_BANK in config.BANKS
    assert next(iter(config.BANKS)) == config.DEFAULT_BANK
