"""Source separation, behind a two-implementation interface.

Everything downstream reads these two stems, so separation quality sets the
ceiling for the whole tool: the vocal stem drives melody and syllable timing,
and any original-vocal residue left in the instrumental will sit audibly under
our own words. That is why there is a second backend rather than just demucs.

Results are cached as wavs in the song's work dir -- separation is by far the
slowest stage and iterating on later stages should not pay for it repeatedly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import audio_io, config
from .util import resolve_device


class SeparationError(RuntimeError):
    pass


@dataclass
class Stems:
    vocal: np.ndarray          # (channels, samples) float32
    instrumental: np.ndarray   # (channels, samples) float32
    sr: int
    backend: str
    cached: bool = False


def separate(
    input_path: str | Path,
    work_dir: Path,
    backend: str | None = None,
    device: str | None = None,
    force: bool = False,
) -> Stems:
    """Split a song into vocal and instrumental, using the cache when possible."""
    backend = backend or config.SEPARATOR
    vocal_path = work_dir / "vocal.wav"
    instr_path = work_dir / "instrumental.wav"

    if not force and vocal_path.is_file() and instr_path.is_file():
        return Stems(
            vocal=audio_io.read_wav(vocal_path),
            instrumental=audio_io.read_wav(instr_path),
            sr=config.SAMPLE_RATE,
            backend=backend,
            cached=True,
        )

    if backend == "demucs":
        vocal, instrumental = _separate_demucs(input_path, device)
    elif backend == "roformer":
        vocal, instrumental = _separate_roformer(input_path, work_dir, device)
    else:
        raise SeparationError(f"unknown separator backend: {backend!r} (expected 'demucs' or 'roformer')")

    audio_io.write_wav(vocal_path, vocal)
    audio_io.write_wav(instr_path, instrumental)

    return Stems(vocal=vocal, instrumental=instrumental, sr=config.SAMPLE_RATE, backend=backend)


def _separate_demucs(input_path: str | Path, device: str | None) -> tuple[np.ndarray, np.ndarray]:
    try:
        import torch
        from demucs.api import Separator
    except ImportError as exc:  # pragma: no cover - environment problem, not logic
        raise SeparationError(f"demucs backend unavailable: {exc}") from exc

    audio = audio_io.decode(input_path, sr=config.SAMPLE_RATE, channels=2)

    kwargs = {
        "model": config.DEMUCS_MODEL,
        "device": resolve_device(device),
        "shifts": config.DEMUCS_SHIFTS,
        "progress": True,
    }
    if config.DEMUCS_SEGMENT is not None:
        kwargs["segment"] = config.DEMUCS_SEGMENT

    separator = Separator(**kwargs)
    wav = torch.from_numpy(audio)
    _, stems = separator.separate_tensor(wav, config.SAMPLE_RATE)

    if "vocals" not in stems:
        raise SeparationError(
            f"demucs model {config.DEMUCS_MODEL!r} produced no 'vocals' stem "
            f"(got: {sorted(stems)})"
        )

    vocal = stems["vocals"].cpu().numpy().astype(np.float32)
    others = [t for name, t in stems.items() if name != "vocals"]
    instrumental = torch.stack(others).sum(dim=0).cpu().numpy().astype(np.float32)
    return vocal, instrumental


def _separate_roformer(
    input_path: str | Path, work_dir: Path, device: str | None
) -> tuple[np.ndarray, np.ndarray]:
    try:
        from audio_separator.separator import Separator
    except ImportError as exc:
        raise SeparationError(
            "the roformer backend needs the audio-separator package, which is not "
            "installed by default because it pulls in its own onnxruntime.\n"
            "    .venv\\Scripts\\pip install \"audio-separator[gpu]\"\n"
            "Then re-run with --separator roformer."
        ) from exc

    out_dir = work_dir / "roformer"
    out_dir.mkdir(parents=True, exist_ok=True)

    separator = Separator(output_dir=str(out_dir), output_format="wav")
    separator.load_model(model_filename=config.ROFORMER_MODEL)
    produced = separator.separate(str(input_path))

    # audio-separator names its outputs by stem role rather than returning them
    # in a fixed order, so match on the role rather than on position.
    paths = [out_dir / name for name in produced]
    vocal_path = _pick_stem(paths, "vocals")
    instr_path = _pick_stem(paths, "instrumental")

    return audio_io.read_wav(vocal_path), audio_io.read_wav(instr_path)


def _pick_stem(paths: list[Path], role: str) -> Path:
    for p in paths:
        if role.lower() in p.name.lower():
            return p
    raise SeparationError(
        f"could not find the {role!r} stem among audio-separator's output: "
        f"{[p.name for p in paths]}"
    )
