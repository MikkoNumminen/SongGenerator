"""Small shared helpers."""

from __future__ import annotations

import glob
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

from . import config


def resolve_device(requested: str | None = None) -> str:
    """Pick a torch device: explicit request, then config, then autodetect."""
    choice = requested or config.DEVICE
    if choice:
        return choice
    try:
        import torch
    except ImportError:
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def slugify(name: str) -> str:
    """Filesystem-safe stem for a song title, used to name its work dir."""
    slug = re.sub(r"[^\w\-]+", "_", Path(name).stem, flags=re.UNICODE).strip("_")
    return (slug or "song").lower()[:80]


def work_dir_for(input_path: str | Path, root: str | Path = config.WORK_DIR) -> Path:
    d = Path(root) / slugify(Path(input_path).name)
    d.mkdir(parents=True, exist_ok=True)
    return d


def fmt_duration(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"


def expand(patterns: list[str]) -> list[Path]:
    """Files matching a list of globs, in order, deduped, misses warned about.

    Every batch tool takes the same command line gesture, so they must read it
    the same way: a pattern that matches nothing earns a warning rather than
    silence, and a file reached through two patterns is processed once. This
    used to exist as three copies, and the third had quietly lost both of
    those properties.
    """
    found: list[Path] = []
    for pattern in patterns:
        hits = [Path(p) for p in glob.glob(pattern)]
        if hits:
            found.extend(sorted(hits))
        elif Path(pattern).is_file():
            found.append(Path(pattern))
        else:
            print(f"  warning: nothing matched {pattern!r}", file=sys.stderr)

    # Dedupe while keeping order.
    seen, out = set(), []
    for p in found:
        key = p.resolve()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def word_similarity(heard: str, target: str) -> float:
    """How much a recognised token resembles one bank word, 0..1.

    Both labelling stages score the same clips with this: label_words when it
    matches a whole-vocal transcript against the bank, precheck when it
    guesses clip by clip. One function, so retuning one stage cannot quietly
    leave the other behind.

    A long target heard as one of its own leading syllables ("kilo" for
    "kilometer") scores poorly on whole-word ratio but is still very likely
    that word, so a clean prefix is rewarded too. The numbers live in
    config.py with the reasoning; see MATCH_PREFIX_SCORE.
    """
    ratio = SequenceMatcher(None, heard, target).ratio()
    if len(heard) >= config.MATCH_PREFIX_MIN_LEN and target.startswith(heard):
        ratio = max(ratio, config.MATCH_PREFIX_SCORE)
    return ratio
