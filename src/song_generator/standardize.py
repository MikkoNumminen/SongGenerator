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

from pathlib import Path

import numpy as np

from . import audio_io, config


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
