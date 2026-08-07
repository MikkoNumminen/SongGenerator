"""Test-wide setup.

Disables the local vocabulary override before anything imports the package, so
the suite always runs against the example vocabulary shipped in config.py.
Without this a machine with its own word bank would fail tests that assert the
example words, and a machine without one would pass, which makes the suite a
statement about the installation rather than about the code.

pytest imports conftest before test modules, which is early enough: the module
level constants built from the vocabulary are computed at import time. The
environment variable is set before the imports below for the same reason.

Also home to the clip factory that `test_arrange.py` and `test_determinism.py`
share. It lives here rather than in one test module imported by the other for
two reasons. Cross-module test imports only resolve under pytest's default
prepend import mode, so adopting importlib mode would break them. Worse, the
determinism pins assert the exact arrangement built from this factory's
output, so a private helper owned by another test file could be innocently
refactored and silently redefine the pinned bank. A conftest fixture makes
the dependency explicit and survives both.
"""

import os

os.environ["SONG_GENERATOR_NO_LOCAL_VOCAB"] = "1"

import numpy as np
import pytest

from song_generator import config
from song_generator.mapping import Unit

SR = config.SAMPLE_RATE


def _tone(seconds: float, freq: float = 220.0, amp: float = 0.4) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    mono = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([mono, mono])


def make_unit(words, per_word=0.4, name=None) -> Unit:
    """A clip holding the given words, with honest boundaries."""
    syllables = [config.WORD_SYLLABLES[w] for w in words]
    total = sum(syllables) * (per_word / 2)
    audio = _tone(total)
    bounds, at = [], 0.0
    for n in sum(([w] * config.WORD_SYLLABLES[w] for w in words), []):
        at += per_word / 2
        bounds.append(round(at, 4))
    return Unit(
        name=name or ("-".join(words) + "_1.wav"),
        words=list(words),
        syllables=sum(syllables),
        duration_s=audio.shape[1] / SR,
        midi=53.0,
        audio=audio,
        bounds_s=bounds[:-1],
        syllable_midi=[53.0] * sum(syllables),
    )


@pytest.fixture
def unit():
    """The shared clip factory, injected so no test module imports another."""
    return make_unit
