"""Stretches of the original vocal that stay as they were: --keep-original.

Some of what a separator calls vocals is not words. "Suomalainen metsä" has
whistling in it; the separator put it in the vocal stem with the singing, the
analysis found notes in it, and the planner sang swear words over it. The
whistling was part of the song and the words were not an improvement.

So a render can be told where to leave the original alone. Inside a kept
range no slot is given a word, and the original vocal stem is laid back onto
the bed, faded in and out over KEEP_ORIGINAL_FADE_S so it does not click.
Because it goes into the bed before the bed is levelled, it sits against the
band exactly as it did in the original.

The ranges are given by hand. A detector was tried: a whistle is a nearly
pure tone, so frames whose energy sits almost entirely in one peak above
500 Hz, with nothing an octave below it, were marked. On this song it found
the whistling, and across 40 other cached songs it also fired on long sung
notes, 88 seconds of them in one Avantasia song. Run by default it would have
put real singing back into renders all over the library, so the decision
stays with the person who has heard the song.
"""

from __future__ import annotations

import re
from typing import Sequence

import numpy as np

from . import config

_TIME = r"(?:(\d+):)?(\d+(?:\.\d+)?)"
_RANGE = re.compile(rf"^\s*{_TIME}\s*-\s*{_TIME}\s*$")


class KeepError(ValueError):
    pass


def _seconds(minutes: str | None, seconds: str) -> float:
    return (int(minutes) * 60 if minutes else 0) + float(seconds)


def parse_ranges(text: str) -> list[tuple[float, float]]:
    """ "0:24-0:30, 1:03-1:09.5" as sorted, merged (start, end) seconds.

    m:ss or plain seconds on either side. A range that ends before it starts
    is refused rather than swapped: it is a typo, and a guess at what was
    meant would keep the wrong stretch without saying so.
    """
    ranges = []
    for part in filter(None, (p.strip() for p in text.split(","))):
        m = _RANGE.match(part)
        if not m:
            raise KeepError(f"expected ranges like 0:24-0:30, got {part!r}")
        start = _seconds(m.group(1), m.group(2))
        end = _seconds(m.group(3), m.group(4))
        if end <= start:
            raise KeepError(f"{part!r} ends before it starts")
        ranges.append((start, end))
    if not ranges:
        raise KeepError("no ranges given")
    return merge(ranges)


def merge(ranges: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def outside(slots: list, ranges: Sequence[tuple[float, float]]) -> tuple[list, int]:
    """The slots that touch no kept range, and how many were dropped.

    Touching at all is enough to drop one. A word that began before a kept
    stretch would ring on into it, over the very thing being kept.
    """
    kept = [s for s in slots
            if not any(s.onset_s < e and s.offset_s > b for b, e in ranges)]
    return kept, len(slots) - len(kept)


def mask(ranges: Sequence[tuple[float, float]], n_samples: int, sr: int,
         fade_s: float | None = None) -> np.ndarray:
    """1.0 inside the kept ranges, 0.0 outside, with linear fades at the edges.

    The fades sit inside each range, so nothing from outside a kept range is
    ever let through.
    """
    fade = int((config.KEEP_ORIGINAL_FADE_S if fade_s is None else fade_s) * sr)
    m = np.zeros(n_samples, dtype=np.float32)
    for s, e in ranges:
        a, b = max(0, int(s * sr)), min(n_samples, int(e * sr))
        if b <= a:
            continue
        m[a:b] = 1.0
        f = min(fade, (b - a) // 2)
        if f > 0:
            ramp = np.linspace(0.0, 1.0, f, dtype=np.float32)
            m[a:a + f] = ramp
            m[b - f:b] = ramp[::-1]
    return m


def with_original(instrumental: np.ndarray, vocal: np.ndarray,
                  ranges: Sequence[tuple[float, float]],
                  sr: int = config.SAMPLE_RATE) -> np.ndarray:
    """The bed, with the original vocal put back inside the kept ranges."""
    n = min(instrumental.shape[-1], vocal.shape[-1])
    m = mask(ranges, n, sr)
    bed = np.array(instrumental[..., :n], dtype=np.float32)
    bed += vocal[..., :n] * m
    return bed
