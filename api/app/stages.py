"""Which stage a run has reached, read from the lines it prints.

The pipeline has no progress callback. It prints a fixed set of headers as it
moves, and those lines are the only signal a front end can have without
changing pipeline code, which is out of scope by instruction.

So this module is deliberately small, pure, and the one place that knows those
strings. Everything else takes a `Stage` and never sees stdout. When the
pipeline's wording changes, exactly one file and its tests are wrong, and they
are wrong loudly rather than silently reporting a run stuck at separation.

What this can honestly report:

- Which stage is running. Every transition below is a line the pipeline
  already prints.
- A real percentage during separation only, because the separator prints one.
  Nothing else in the run reports progress within a stage, so nothing else
  gets a bar. An invented one would be worst exactly where runs are slowest.
- That a song was refused as having no vocal to work from, which is a normal
  outcome rather than a failure, and needs its own answer in the UI.

Timings, for the estimate a front end shows instead of a fake bar. Separation
is about 0.45x realtime and is cached, so a second run of the same song skips
it entirely and is dramatically faster. Rendering both playfulness levels costs
roughly 50 seconds of resynthesis on a two and a half minute song, which is
what a run from here does: one file per level, at full mimicry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
# Windows, and pure. Pure because this splits a string the pipeline printed
# and must not ask the filesystem anything. Windows because that is the only
# platform the pipeline runs on, and PurePath is PurePosixPath everywhere
# else: read on Linux it takes no backslash for a separator, so the whole of
# `D:\repo\output\song\bank\song.wild.mp3` is one name whose parent is `.`,
# and the folder came back as the directory the run was started in.
from pathlib import PureWindowsPath


class Stage(str, Enum):
    """The coarsest description of a run that is honestly observable."""

    QUEUED = "queued"
    SEPARATING = "separating"
    ANALYSING = "analysing"
    ARRANGING = "arranging"
    RENDERING = "rendering"
    DONE = "done"
    REFUSED = "refused"   # no vocal to borrow from; the pipeline's mode B
    FAILED = "failed"


# Ordered, because a stage may only move forward. The separator prints progress
# lines after the analysis header has scrolled past in some backends, and a
# status that flickered backwards would read as a stuck run.
_ORDER = {
    Stage.QUEUED: 0,
    Stage.SEPARATING: 1,
    Stage.ANALYSING: 2,
    Stage.ARRANGING: 3,
    Stage.RENDERING: 4,
    Stage.DONE: 5,
    Stage.REFUSED: 5,
    Stage.FAILED: 5,
}

# Each marker is a line the pipeline prints today. Anchored at the start so a
# path or a song title containing the same word cannot trigger one.
_MARKERS: tuple[tuple[str, Stage], ...] = (
    ("  separator ", Stage.SEPARATING),
    ("  stems ", Stage.ANALYSING),
    ("  bank ", Stage.ARRANGING),
    ("  play ", Stage.RENDERING),
    ("  wrote ", Stage.DONE),
)

_REFUSED = "MODE B -- no vocals"

# Where a finished run says it put its files. Two shapes, because the pipeline
# says it two ways: a folder when it wrote more than one rendering, and the
# file itself when it wrote exactly one (`--play wild`, or a single rung).
# Ordered, since the folder form also matches the looser file pattern.
_WROTE_FOLDER = re.compile(r"^ {2}wrote \d+ versions? to (.+)$")
_WROTE_FILE = re.compile(r"^ {2}wrote\s+(\S.*)$")

# The separator's own progress, the only within-stage number that is real.
_PERCENT = re.compile(r"(\d{1,3})(?:\.\d+)?%")


def _wrote_to(text: str) -> str | None:
    """The folder a `wrote` line names, whichever way it was phrased.

    The one-file form names the file, so its folder is the parent. Both are
    returned exactly as the pipeline spelled them, relative or absolute:
    making that absolute needs the directory the run was started in, which is
    the runner's business rather than this parser's.
    """
    folder = _WROTE_FOLDER.match(text)
    if folder:
        return folder.group(1).strip()
    one = _WROTE_FILE.match(text)
    if one:
        # PureWindowsPath accepts a forward slash as a separator too, so this
        # reads a path the pipeline spelled either way.
        return str(PureWindowsPath(one.group(1).strip()).parent)
    return None


@dataclass(frozen=True)
class Progress:
    """What a run has told us so far."""

    stage: Stage = Stage.QUEUED
    percent: int | None = None      # separation only, None everywhere else
    detail: str | None = None       # the line that moved it, for the log view
    #: Where the run said it wrote, as the pipeline spelled it. Taken from the
    #: run's own words rather than worked out from the request, because the
    #: pipeline decides where it puts things and nothing here should have a
    #: second opinion. Without it the edge could list a finished run's files
    #: and always answered with none.
    wrote_to: str | None = None

    def advance(self, line: str) -> Progress:
        """Fold one line of output in. Never moves backwards."""
        text = line.rstrip()

        if _REFUSED in text:
            return Progress(Stage.REFUSED, None, text.strip(), self.wrote_to)

        for marker, stage in _MARKERS:
            if text.startswith(marker):
                if _ORDER[stage] < _ORDER[self.stage]:
                    return self
                return Progress(stage, None, text.strip(),
                                _wrote_to(text) or self.wrote_to)

        if self.stage is Stage.SEPARATING:
            found = _PERCENT.search(text)
            if found:
                pct = min(100, int(found.group(1)))
                return Progress(self.stage, pct, self.detail, self.wrote_to)

        return self


def read(lines: object) -> Progress:
    """Fold a whole run's output into one progress. Mostly for tests."""
    progress = Progress()
    for line in lines:  # type: ignore[attr-defined]
        progress = progress.advance(str(line))
    return progress


def final_stage(exit_code: int, reached: Stage) -> Stage:
    """What the run actually ended as, once the exit code is known.

    The exit code is the authority, not the last line seen. A run killed
    mid-render prints nothing to say so, and one refused as having no vocal
    exits 3 having printed its verdict.
    """
    if exit_code == 0:
        return Stage.DONE if reached is not Stage.REFUSED else Stage.REFUSED
    if exit_code == 3:
        return Stage.REFUSED
    return Stage.FAILED
