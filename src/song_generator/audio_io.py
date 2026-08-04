"""Audio decode/encode. ffmpeg for compressed formats, soundfile for wav.

Everything inside the pipeline is a float32 numpy array shaped (channels,
samples) at config.SAMPLE_RATE. These helpers are the only place that shape and
rate are established, so the rest of the code can assume both.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from . import config


class AudioError(RuntimeError):
    pass


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise AudioError(
            "ffmpeg not found on PATH. It is required to read and write mp3.\n"
            "    winget install Gyan.FFmpeg\n"
            "Then open a new terminal so PATH is picked up."
        )
    return exe


def decode(path: str | Path, sr: int = config.SAMPLE_RATE, channels: int = 2) -> np.ndarray:
    """Decode any ffmpeg-readable file to (channels, samples) float32."""
    path = Path(path)
    if not path.is_file():
        raise AudioError(f"input file not found: {path}")

    cmd = [
        _ffmpeg(), "-nostdin", "-v", "error",
        "-i", str(path),
        "-f", "f32le", "-acodec", "pcm_f32le",
        "-ac", str(channels), "-ar", str(sr),
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise AudioError(f"ffmpeg failed to decode {path.name}:\n{proc.stderr.decode(errors='replace')}")
    if not proc.stdout:
        raise AudioError(f"ffmpeg produced no audio for {path.name} (empty or corrupt file?)")

    flat = np.frombuffer(proc.stdout, dtype="<f4")
    # Trailing partial frame would break the reshape; ffmpeg should not emit
    # one, but a truncated pipe can.
    usable = (len(flat) // channels) * channels
    return np.ascontiguousarray(flat[:usable].reshape(-1, channels).T.astype(np.float32))


def encode_mp3(
    path: str | Path,
    audio: np.ndarray,
    sr: int = config.SAMPLE_RATE,
    bitrate: str = config.MP3_BITRATE,
) -> Path:
    """Write (channels, samples) float32 to mp3 via ffmpeg."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    audio = np.atleast_2d(np.asarray(audio, dtype=np.float32))

    cmd = [
        _ffmpeg(), "-nostdin", "-v", "error", "-y",
        "-f", "f32le", "-ar", str(sr), "-ac", str(audio.shape[0]),
        "-i", "-",
        "-codec:a", "libmp3lame", "-b:a", bitrate,
        str(path),
    ]
    raw = np.ascontiguousarray(audio.T).tobytes()
    proc = subprocess.run(cmd, input=raw, capture_output=True)
    if proc.returncode != 0:
        raise AudioError(f"ffmpeg failed to encode {path.name}:\n{proc.stderr.decode(errors='replace')}")
    return path


def write_wav(path: str | Path, audio: np.ndarray, sr: int = config.SAMPLE_RATE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    audio = np.atleast_2d(np.asarray(audio, dtype=np.float32))
    sf.write(str(path), audio.T, sr, subtype="FLOAT")
    return path


def read_wav(path: str | Path, sr: int = config.SAMPLE_RATE) -> np.ndarray:
    """Read a wav, resampling only if it disagrees with the pipeline rate."""
    path = Path(path)
    data, file_sr = sf.read(str(path), dtype="float32", always_2d=True)
    audio = np.ascontiguousarray(data.T)
    if file_sr != sr:
        # Rare enough (only hand-placed files) that shelling out beats pulling
        # a resampler into this module.
        return decode(path, sr=sr, channels=audio.shape[0])
    return audio


def to_mono(audio: np.ndarray) -> np.ndarray:
    """(channels, samples) -> (samples,) float32."""
    audio = np.atleast_2d(audio)
    return audio.mean(axis=0).astype(np.float32)
