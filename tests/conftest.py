"""Test-wide setup.

Disables the local vocabulary override before anything imports the package, so
the suite always runs against the example vocabulary shipped in config.py.
Without this a machine with its own word bank would fail tests that assert the
example words, and a machine without one would pass, which makes the suite a
statement about the installation rather than about the code.

pytest imports conftest before test modules, which is early enough: the module
level constants built from the vocabulary are computed at import time. The
environment variable is set before the imports below for the same reason.

The clip factory the suite shares lives in `factories.py`, next door. It is
re-exported here as a fixture for modules that want it injected; modules that
need it inside a module-level helper import it from there directly, which a
fixture cannot serve.
"""

import os

os.environ["SONG_GENERATOR_NO_LOCAL_VOCAB"] = "1"

# Deliberately after the assignment above, not sorted with it: the package
# reads that variable at import time, so sorting these together would
# silently re-enable the local vocabulary this file exists to disable.
import pytest

from factories import make_unit

__all__ = ["make_unit"]


@pytest.fixture
def unit():
    """The shared clip factory, injected so no test module imports another."""
    return make_unit
