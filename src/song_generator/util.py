"""Small shared helpers."""

from __future__ import annotations

import glob
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

from . import config


def resolve_device(requested: str | None = None) -> str:
    """Pick a torch device: explicit request, then config, then autodetect.

    Also caps how much of the card this process may take. Every GPU user in the
    pipeline resolves its device through here, so this is the one place that
    has to know.
    """
    choice = requested or config.DEVICE
    if not choice:
        try:
            import torch
        except ImportError:
            return "cpu"
        choice = "cuda" if torch.cuda.is_available() else "cpu"

    if choice.startswith("cuda"):
        cap_gpu_memory(choice)
    return choice


def cap_gpu_memory(device: str = "cuda") -> bool:
    """Leave part of the card free for whatever else is using it.

    Returns whether a cap was applied, so a caller can say so rather than
    assume it.

    The machine this runs on also hosts other GPU work, and a separator that
    takes the whole card either evicts that or is evicted by it.

    A cap below what separation actually needs is refused rather than applied,
    because it does not protect anything: it just turns a working render into
    an out-of-memory error while the card sits half empty. That is not
    hypothetical. At 0.15 on a 12 GB card roformer died with "1.80 GiB allowed"
    while 6.25 GiB was free. SEPARATION_PEAK_MIB carries the measured figure it
    has to clear.

    Torch's limit is PER PROCESS, which is the right shape here only because
    the pipeline separates one song at a time. Running several separations at
    once would give each of them the same share and overrun the card between
    them, so keep separation serialised.

    Exceeding the cap raises an out-of-memory error rather than spilling, which
    is the honest failure: a song that genuinely needs more says so instead of
    quietly dragging the whole machine.
    """
    fraction = getattr(config, "GPU_MEMORY_FRACTION", 0.0)
    if not 0.0 < fraction < 1.0:
        return False
    try:
        import torch

        index = torch.device(device).index or 0
        total_mib = torch.cuda.get_device_properties(index).total_memory / 1024 ** 2
        if total_mib * fraction < getattr(config, "SEPARATION_PEAK_MIB", 0):
            # Too small to be a cap. Leaving the card uncapped is the lesser
            # harm: the alternative is a render that cannot run at all.
            return False
        torch.cuda.set_per_process_memory_fraction(fraction, index)
    except (ImportError, RuntimeError, ValueError, AssertionError, AttributeError):
        # No torch, no CUDA, a device that does not exist, or a torch build
        # without one of these calls. Capping is a courtesy to other work on
        # the card, never a reason to fail a render.
        return False
    return True


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
