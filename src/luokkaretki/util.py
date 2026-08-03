"""Small shared helpers."""

from __future__ import annotations

import re
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
