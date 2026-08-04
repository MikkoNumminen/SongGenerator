"""Standardise a finished bank into a derivative tier that sits together.

    python -m song_generator.standardize

The hand-recorded clips are the source of truth and are never written to. This
pass reads them and produces NEW files in a sibling directory, each traceable
back to the clip it came from. Delete the tier and nothing is lost; run it
again and the same clips come back.

What it does is assembly, not enhancement: trim the dead air off each end, fade
the cut so it does not click, and bring the levels into line. What a word
SOUNDS like is the whole point of the bank, so nothing here touches timbre --
no denoise, no EQ, no compression, no resynthesis.

The guard below is the load-bearing part. Every write in this module goes
through write_derivative, which refuses any destination that could be a source
clip. Overwriting a hand-recorded original is meant to be impossible rather
than merely avoided.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import audio_io, config

# Envelope resolution for edge detection. Finer than the 256 used elsewhere:
# this measures a boundary rather than finding a region, and 2.9 ms of
# quantisation on a 25 ms guard would be a tenth of the thing being decided.
TRIM_HOP = 128


class StandardizeError(RuntimeError):
    pass


def _resolved(path: Path) -> Path:
    """Absolute, symlinks followed, so containment checks cannot be fooled."""
    return Path(path).expanduser().resolve()


def _relation(a: Path, b: Path) -> str | None:
    """How two directories overlap, or None when they are unrelated."""
    if a == b:
        return "is"
    if a in b.parents:
        return "contains"
    if b in a.parents:
        return "is inside"
    return None


def check_destination(root: Path, sources: list[Path]) -> Path:
    """Refuse an output directory that could reach a source clip.

    Three ways a derivative could land on top of an original, all refused
    before anything is written:

      --out words_hq          the tier IS the source
      --out words_hq/std      the tier is inside the source, so a later
                              rglob over the source sweeps derivatives up
      --out .                 the tier contains the source

    Checked on resolved paths, so a symlink pointing back at the source is
    caught as well as a literal path.
    """
    root_r = _resolved(root)
    for source in sources:
        source_r = _resolved(source)
        how = _relation(root_r, source_r)
        if how is not None:
            raise StandardizeError(
                f"refusing to write derivatives into {root_r}:\n"
                f"    that directory {how} the source bank {source_r}.\n"
                "    The recorded clips are the source of truth and this pass "
                "never writes to them.\n"
                "    Pick an --out that is a sibling, e.g. "
                f"{source_r.name}{config.STD_SUFFIX}"
            )
    return root_r


def write_derivative(root: Path, name: str, audio: np.ndarray,
                     sources: list[Path], protected: set[Path] | None = None) -> Path:
    """The only way this module puts a file on disk.

    Re-checks the destination on every call rather than trusting a check made
    once at startup: a guard that runs at the moment of writing cannot be
    skipped by a later code path that forgot about it.
    """
    root_r = check_destination(root, sources)
    dest = _resolved(root_r / name)

    if root_r not in dest.parents:
        raise StandardizeError(
            f"refusing to write {dest}: it is not inside {root_r}. "
            f"A clip name may not climb out of the output directory."
        )
    if protected and dest in protected:
        raise StandardizeError(
            f"refusing to write {dest}: that path is a source clip in the manifest."
        )

    root_r.mkdir(parents=True, exist_ok=True)
    return audio_io.write_wav(dest, audio)


# ---------------------------------------------------------------------------
# Trim
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Trim:
    """How much silence to remove from each end, in seconds."""
    head_s: float
    tail_s: float

    @property
    def any(self) -> bool:
        return self.head_s > 0.0 or self.tail_s > 0.0


def find_trim(mono: np.ndarray, sr: int = config.SAMPLE_RATE) -> Trim:
    """Where the sound really starts and ends, judged conservatively.

    Deliberately biased toward leaving silence in. The envelope is compared
    against the clip's own peak, a guard is subtracted from each end so the
    cut never lands on the first sound itself, and the head trim is capped
    outright. Trimming a hair short costs nothing; trimming into a soft word
    start removes the attack and cannot be undone.

    Only the two outer boundaries move. Nothing in here can reach the middle
    of a clip, which is what keeps the sung transition inside a multi-word
    clip structurally safe rather than safe by good behaviour.
    """
    from .extract_words import _envelope_db

    mono = np.asarray(mono, dtype=np.float32)
    dur_s = mono.shape[0] / sr
    if dur_s <= 0:
        return Trim(0.0, 0.0)

    env = _envelope_db(mono, sr, TRIM_HOP)
    live = np.flatnonzero(env > env.max() + config.STD_DEAD_AIR_DB)
    if live.size == 0:
        # Nothing rises above its own floor: a clip of pure silence or pure
        # noise. Neither is safe to trim, so it is passed through untouched.
        return Trim(0.0, 0.0)

    hop_s = TRIM_HOP / sr
    head = max(0.0, float(live[0]) * hop_s - config.STD_HEAD_GUARD_S)
    tail = max(0.0, float(len(env) - 1 - live[-1]) * hop_s - config.STD_TAIL_GUARD_S)

    head = min(head, config.STD_HEAD_CAP_S)

    # Never trim a clip below the length that counts as a word at all. The tail
    # gives way first: it is dead air by construction, while the head is next
    # to the attack.
    room = dur_s - config.WORD_MIN_S
    if head + tail > room:
        tail = max(0.0, min(tail, room))
        head = max(0.0, min(head, room - tail))

    return Trim(round(head, 6), round(tail, 6))


def apply_trim(clip: np.ndarray, trim: Trim, sr: int = config.SAMPLE_RATE) -> np.ndarray:
    """Cut the ends off, then fade the cuts so they do not click."""
    clip = np.atleast_2d(np.asarray(clip, dtype=np.float32))
    n = clip.shape[1]
    lo = min(int(round(trim.head_s * sr)), n)
    hi = max(lo, n - int(round(trim.tail_s * sr)))
    out = np.array(clip[:, lo:hi], dtype=np.float32)

    width = out.shape[1]
    if width == 0:
        return out

    fade_in = min(int(config.STD_FADE_IN_S * sr), width // 2)
    fade_out = min(int(config.STD_FADE_OUT_S * sr), width // 2)
    if fade_in > 0:
        out[:, :fade_in] *= np.linspace(0.0, 1.0, fade_in, dtype=np.float32)
    if fade_out > 0:
        out[:, -fade_out:] *= np.linspace(1.0, 0.0, fade_out, dtype=np.float32)
    return out


def shift_bounds(bounds: list[float], head_s: float, duration_s: float) -> list[float]:
    """Move syllable boundaries to match a clip that lost time off its front.

    syllable_bounds_s are absolute offsets into the clip, so trimming the head
    invalidates every one of them. Getting this wrong is quiet and expensive:
    a boundary off by 30 ms lands a syllable on the wrong note in stage 3, and
    nothing reports it.

    The count is preserved whatever happens. A boundary is what tells the
    mapper how many syllables the clip holds, so dropping one because it
    landed badly would change the word rather than fix it.
    """
    if not bounds:
        return []

    eps = 1e-4
    out: list[float] = []
    previous = 0.0
    for b in bounds:
        value = min(max(float(b) - head_s, previous + eps), max(duration_s - eps, eps))
        out.append(round(value, 4))
        previous = value
    return out
