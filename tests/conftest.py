"""Test-wide setup.

Disables the local vocabulary override before anything imports the package, so
the suite always runs against the example vocabulary shipped in config.py.
Without this a machine with its own word bank would fail tests that assert the
example words, and a machine without one would pass, which makes the suite a
statement about the installation rather than about the code.

pytest imports conftest before test modules, which is early enough: the module
level constants built from the vocabulary are computed at import time. The
environment variable is set before the imports below for the same reason.

The clip factory the suite shares lives in `factories.py`, next door, exposed
here as the `unit` fixture. Prefer the fixture: it resolves under any pytest
import mode, where importing `factories` directly needs the default prepend
mode. A module-level helper cannot take a fixture, so those import it, and
`factories.py` records that limit.
"""

import os

os.environ["SONG_GENERATOR_NO_LOCAL_VOCAB"] = "1"

# Deliberately after the assignment above, not sorted with it: the package
# reads that variable at import time, so sorting these together would
# silently re-enable the local vocabulary this file exists to disable.
import pytest

from factories import make_unit


@pytest.fixture
def unit():
    """The shared clip factory, injected so no test module imports another."""
    return make_unit
