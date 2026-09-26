"""Stretches of the original vocal that stay as they were: --keep-original.

Some of what a separator calls vocals is not words. "Suomalainen metsä" has
whistling in it; the separator put it in the vocal stem with the singing, the
analysis found notes in it, and the planner sang swear words over it. The
whistling was part of the song and the words were not an improvement. The same
flag makes a piece that is half the original: keep the choruses, and the bank
sings the verses.

Inside a kept range the original vocal stem is laid back onto the bed, and no
word may sound. Three things make that hold whatever the planner does:

- every slot touching a range is dropped, and the range is widened to cover
  those slots whole, so the note the singer started before the edge is kept
  from its start rather than faded in halfway;
- the slots on either side of a range are put in different phrases, because
  every planner groups by phrase: swallowing would otherwise fold the last
  note before a range and the first after it into one slot spanning it, and
  reciting would carry straight through a short one;
- the word bus is silenced inside the ranges before mixing, with the same
  fades, which catches any word still ringing on from before one.

The ranges are given by hand. A detector was tried: a whistle is a nearly
pure tone, so frames whose energy sits almost entirely in one peak above
500 Hz, with nothing an octave below it, were marked. On this song it found
the whistling, and across 40 other cached songs it also fired on long sung
notes, 88 seconds of them in one Avantasia song. Run by default it would have
put real singing back into renders all over the library, so the decision
stays with the person who has heard the song.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from typing import Sequence

import numpy as np

from . import config
from .arrange import unclock

# m:ss(.s) or plain seconds. The clock format arrange.py writes and reads, and
# unclock does the reading; this only decides what is shaped like a time.
_CLOCK = re.compile(r"^\d+(?::[0-5]?\d)?(?:\.\d+)?$")


class KeepError(ValueError):
    pass


def _time(text: str, part: str) -> float:
    text = text.strip()
    if not _CLOCK.match(text):
        raise KeepError(f"expected a time like 0:24 or 24.5 in {part!r}, got {text!r}")
    return unclock(text) if ":" in text else float(text)


def parse_ranges(text: str) -> list[tuple[float, float]]:
    """ "0:24-0:30, 1:03-1:09.5" as sorted, merged (start, end) seconds.

    m:ss or plain seconds on either side. A range that ends before it starts
    is refused rather than swapped: it is a typo, and a guess at what was
    meant would keep the wrong stretch without saying so.
    """
    ranges = []
    for part in filter(None, (p.strip() for p in text.split(","))):
        sides = part.split("-")
        if len(sides) != 2:
            raise KeepError(f"expected ranges like 0:24-0:30, got {part!r}")
        start, end = (_time(side, part) for side in sides)
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


def refuse_past_the_end(ranges: Sequence[tuple[float, float]],
                        duration_s: float) -> None:
    """A range that starts after the song ends is a typo, never a request.

    "10:24" for "1:02.4" would otherwise keep nothing, drop nothing, and
    write a take tagged as kept with words sung straight over the part that
    was meant to be left alone.
    """
    late = [(s, e) for s, e in ranges if s >= duration_s]
    if late:
        shown = ", ".join(f"{s:g}-{e:g}s" for s, e in late)
        raise KeepError(f"{shown} starts after the song ends at {duration_s:.1f}s")


def outside(slots: list, ranges: Sequence[tuple[float, float]]
            ) -> tuple[list, int, list[tuple[float, float]]]:
    """The slots left to sing, how many were dropped, and the ranges widened.

    A slot touching a range at all is dropped: a word begun before the range
    would ring on into it. Its whole span joins the range, so what is put
    back starts where the singer's note did and nothing is left as a hole
    with neither a word nor the original in it.

    The kept slots are renumbered into phrases that never span a range, so no
    planner can join the notes on either side of one.
    """
    kept, spans = [], list(ranges)
    for s in slots:
        if any(s.onset_s < e and s.offset_s > b for b, e in ranges):
            spans.append((s.onset_s, s.offset_s))
        else:
            kept.append(s)
    widened = merge(spans)

    renumbered, phrase, previous = [], -1, None
    for s in kept:
        crossed = previous is not None and any(
            previous.offset_s <= b and s.onset_s >= e for b, e in widened)
        if previous is None or s.phrase != previous.phrase or crossed:
            phrase += 1
        renumbered.append(replace(s, phrase=phrase))
        previous = s
    return renumbered, len(slots) - len(kept), widened


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


def _fit(audio: np.ndarray, n: int) -> np.ndarray:
    """audio cut or zero-padded to n samples, so no stem shortens the song."""
    audio = np.asarray(audio, dtype=np.float32)
    if audio.shape[-1] >= n:
        return audio[..., :n]
    pad = [(0, 0)] * (audio.ndim - 1) + [(0, n - audio.shape[-1])]
    return np.pad(audio, pad)


def with_original(instrumental: np.ndarray, vocal: np.ndarray,
                  ranges: Sequence[tuple[float, float]],
                  sr: int = config.SAMPLE_RATE) -> np.ndarray:
    """The bed, with the original vocal put back inside the kept ranges.

    As long as the instrumental: a vocal stem a few samples short would
    otherwise cut the end off every kept take.
    """
    n = instrumental.shape[-1]
    bed = np.array(instrumental, dtype=np.float32)
    bed += _fit(vocal, n) * mask(ranges, n, sr)
    return bed


def silence_words(word_bus: np.ndarray, ranges: Sequence[tuple[float, float]],
                  sr: int = config.SAMPLE_RATE) -> np.ndarray:
    """The word bus with nothing inside the kept ranges, whatever was placed."""
    return (word_bus * (1.0 - mask(ranges, word_bus.shape[-1], sr))).astype(np.float32)


def tag(ranges: Sequence[tuple[float, float]]) -> str:
    """The filename word for these ranges: keep, and a short hash of them.

    Two sets of ranges are two different pieces, the whistling kept and the
    whole chorus kept, and a bare "keep" had the second replace the first.
    """
    text = ",".join(f"{s:.2f}-{e:.2f}" for s, e in merge(ranges))
    return "keep" + hashlib.sha1(text.encode()).hexdigest()[:6]
