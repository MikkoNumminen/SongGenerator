"""Test-wide setup.

Disables the local vocabulary override before anything imports the package, so
the suite always runs against the example vocabulary shipped in config.py.
Without this a machine with its own word bank would fail tests that assert the
example words, and a machine without one would pass, which makes the suite a
statement about the installation rather than about the code.

pytest imports conftest before test modules, which is early enough: the module
level constants built from the vocabulary are computed at import time.
"""

import os

os.environ["SONG_GENERATOR_NO_LOCAL_VOCAB"] = "1"
