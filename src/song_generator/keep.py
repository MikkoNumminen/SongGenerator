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
- the first slot after a range is marked as a hard break, which every
  planner's phrase grouping respects: swallowing would otherwise fold the
  last note before a range and the first after it into one slot spanning it,
  and group_phrases would rebuild one phrase across a range narrower than
  PHRASE_GAP_S;
- a placement that would still sound inside a range, the last word of a
  phrase ringing on past its slot, is dropped whole before coverage is
  judged (rings_into, used through arrange.build's sings), never cut;
- the word bus is gated inside the ranges before mixing all the same, as the
  last guarantee; after the two above it removes nothing.

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


def merge(ranges: Sequence[tuple[float, float]],
          gap: float = 0.0) -> list[tuple[float, float]]:
    """Sorted, with overlapping ranges joined, and any closer than gap."""
    out: list[list[float]] = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1] + gap:
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
    # Two ranges closer than their two fades would dip to neither the
    # original nor a word between them, so they are joined.
    join = 2 * config.KEEP_ORIGINAL_FADE_S
    widened = merge(ranges, join)
    kept = list(slots)
    # Widening can take in a slot that did not touch the ranges as given (a
    # slot overlapping the one that straddled the edge), so the drop is
    # repeated against the widened ranges until nothing more is taken in.
    while True:
        touching = [s for s in kept
                    if any(s.onset_s < e and s.offset_s > b for b, e in widened)]
        if not touching:
            break
        widened = merge(widened + [(s.onset_s, s.offset_s) for s in touching], join)
        kept = [s for s in kept if s not in touching]

    renumbered, phrase, previous = [], -1, None
    for s in kept:
        crossed = previous is not None and any(
            previous.offset_s <= b and s.onset_s >= e for b, e in widened)
        if previous is None or s.phrase != previous.phrase or crossed:
            phrase += 1
        renumbered.append(replace(s, phrase=phrase,
                                  hard_break=s.hard_break or crossed))
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


def word_gate(ranges: Sequence[tuple[float, float]], n_samples: int,
              sr: int = config.SAMPLE_RATE) -> np.ndarray:
    """0.0 inside the kept ranges and 1.0 outside, to multiply the word bus by.

    Built once per run: the ranges and the song's length do not change
    between the renders a run writes.
    """
    return 1.0 - mask(ranges, n_samples, sr)


def rings_into(placement, ranges: Sequence[tuple[float, float]]) -> bool:
    """Whether this placement would still be sounding inside a kept range.

    Measured with sounding_s, what the render will actually play, not with
    the span the planner asked for.
    """
    from .mapping import sounding_s

    start = placement.onset_s
    end = start + sounding_s(placement)
    return any(start < e and end > b for b, e in ranges)


def tag(ranges: Sequence[tuple[float, float]]) -> str:
    """The filename word for these ranges: keep, and a short hash of them.

    Two sets of ranges are two different pieces, the whistling kept and the
    whole chorus kept, and a bare "keep" had the second replace the first.
    """
    text = ",".join(f"{s:.2f}-{e:.2f}" for s, e in merge(ranges))
    return "keep" + hashlib.sha1(text.encode()).hexdigest()[:6]
