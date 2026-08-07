"""The clip factory the test suite builds its banks from.

A real module rather than a helper inside one test file, and rather than
conftest. Two test modules already reached for it, and a third arrived later
importing it from whichever file happened to own it, which broke collection the
moment that file stopped owning it.

It matters more here than tidiness usually would: `test_determinism.py` pins
the exact arrangement built from these clips, so anything that quietly changes
this output changes what those pins mean. A private helper owned by a test file
can be refactored innocently and redefine the pinned bank without anyone
connecting the two. A module that exists for this and nothing else cannot be
refactored by accident.

What this does NOT solve, stated plainly because an earlier version of this
comment implied otherwise: importing it still relies on pytest's default
prepend import mode putting `tests/` on the path. Adopting importlib mode would
break `from factories import ...` exactly as it would have broken importing
from another test module. Take the `unit` fixture from `conftest.py` where you
can, since a fixture survives either mode; import from here only where a
module-level helper needs it, which a fixture cannot serve.
"""

from __future__ import annotations

import numpy as np

from song_generator import config
from song_generator.mapping import Unit

SR = config.SAMPLE_RATE


def tone(seconds: float, freq: float = 220.0, amp: float = 0.4) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    mono = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([mono, mono])


def make_unit(words, per_word=0.4, name=None) -> Unit:
    """A clip holding the given words, with honest boundaries."""
    syllables = [config.WORD_SYLLABLES[w] for w in words]
    total = sum(syllables) * (per_word / 2)
    audio = tone(total)
    bounds, at = [], 0.0
    # One boundary per syllable. This used to flatten the words into a list of
    # repeated entries and walk it, without ever reading the entry, so all it
    # ever did was count. Counting says so.
    for _ in range(sum(syllables)):
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
