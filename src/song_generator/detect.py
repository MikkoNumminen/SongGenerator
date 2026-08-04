"""Mode detection: does this song actually have a lead vocal to borrow from?

Two independent tests, because they fail on different things:

  loudness  - catches an instrumental whose "vocal" stem is essentially silence.
  voicing   - catches an instrumental whose vocal stem is NOT silent, because
              separation dragged a lead guitar or synth line into it. That
              residue is loud but mostly unvoiced/inharmonic in the way a sung
              line is not, so the voiced-frame fraction stays low.

Both must pass. The numbers behind the verdict are always reported, so when a
song is misclassified you can see which test drew the line and where.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np

from . import audio_io, config
from .util import resolve_device


@dataclass
class VocalReport:
    vocal_present: bool
    vocal_lufs: float
    mix_lufs: float
    rel_lu: float
    voiced_frac: float
    f0_backend: str
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "vocal_present": self.vocal_present,
            "vocal_lufs": round(self.vocal_lufs, 2) if np.isfinite(self.vocal_lufs) else None,
            "mix_lufs": round(self.mix_lufs, 2) if np.isfinite(self.mix_lufs) else None,
            "rel_lu": round(self.rel_lu, 2) if np.isfinite(self.rel_lu) else None,
            "voiced_frac": round(self.voiced_frac, 4),
            "f0_backend": self.f0_backend,
            "reasons": self.reasons,
        }


def integrated_lufs(audio: np.ndarray, sr: int = config.SAMPLE_RATE) -> float:
    """Integrated loudness of (channels, samples) audio. -inf for silence."""
    import pyloudnorm as pyln

    data = np.atleast_2d(audio).T  # pyloudnorm wants (samples, channels)
    if data.shape[0] < int(0.4 * sr):
        return float("-inf")
    if not np.any(np.abs(data) > 0):
        return float("-inf")

    meter = pyln.Meter(sr)
    with warnings.catch_warnings():
        # pyloudnorm warns when a stem is quieter than its own gating threshold,
        # which is exactly the case we are trying to measure.
        warnings.simplefilter("ignore")
        value = meter.integrated_loudness(data)
    return float(value)


def voiced_fraction(
    vocal: np.ndarray,
    sr: int = config.SAMPLE_RATE,
    device: str | None = None,
) -> tuple[float, str]:
    """Fraction of frames reading as confidently voiced, and the backend used."""
    mono = audio_io.to_mono(vocal)
    if mono.size < int(0.5 * sr) or not np.any(np.abs(mono) > 0):
        return 0.0, "none"

    try:
        return _voiced_fraction_crepe(mono, sr, device), "torchcrepe"
    except ImportError:
        return _voiced_fraction_pyin(mono, sr), "librosa-pyin"


def _voiced_fraction_crepe(mono: np.ndarray, sr: int, device: str | None) -> float:
    import torch
    import torchcrepe

    dev = resolve_device(device)
    hop_length = max(1, int(round(config.DETECT_HOP_S * sr)))
    audio = torch.from_numpy(mono)[None]

    with torch.no_grad():
        _, periodicity = torchcrepe.predict(
            audio,
            sr,
            hop_length=hop_length,
            fmin=config.F0_MIN_HZ,
            fmax=config.F0_MAX_HZ,
            model=config.DETECT_F0_MODEL,
            batch_size=512,
            device=dev,
            return_periodicity=True,
        )

    per = periodicity.squeeze(0).cpu().numpy()
    if per.size == 0:
        return 0.0
    return float(np.mean(per >= config.VOICED_PERIODICITY_MIN))


def _voiced_fraction_pyin(mono: np.ndarray, sr: int) -> float:
    """Fallback when torch/torchcrepe are unavailable. Slower, good enough."""
    import librosa

    target_sr = 16000
    signal = librosa.resample(mono, orig_sr=sr, target_sr=target_sr)
    _, voiced_flag, voiced_prob = librosa.pyin(
        signal,
        fmin=config.F0_MIN_HZ,
        fmax=config.F0_MAX_HZ,
        sr=target_sr,
        hop_length=max(1, int(round(config.DETECT_HOP_S * target_sr))),
    )
    if voiced_prob is None or len(voiced_prob) == 0:
        return 0.0
    confident = np.asarray(voiced_flag) & (np.asarray(voiced_prob) >= config.VOICED_PERIODICITY_MIN)
    return float(np.mean(confident))


def detect_vocal(
    vocal: np.ndarray,
    mix: np.ndarray,
    sr: int = config.SAMPLE_RATE,
    device: str | None = None,
) -> VocalReport:
    vocal_lufs = integrated_lufs(vocal, sr)
    mix_lufs = integrated_lufs(mix, sr)
    rel_lu = vocal_lufs - mix_lufs if np.isfinite(vocal_lufs) and np.isfinite(mix_lufs) else float("-inf")
    frac, backend = voiced_fraction(vocal, sr, device)

    reasons: list[str] = []
    if not np.isfinite(vocal_lufs):
        reasons.append("vocal stem is digital silence")
    else:
        if vocal_lufs < config.VOCAL_PRESENT_ABS_LUFS:
            reasons.append(
                f"vocal stem too quiet in absolute terms "
                f"({vocal_lufs:.1f} < {config.VOCAL_PRESENT_ABS_LUFS:.1f} LUFS)"
            )
        if rel_lu < config.VOCAL_PRESENT_REL_LU:
            reasons.append(
                f"vocal stem too quiet relative to the mix "
                f"({rel_lu:.1f} < {config.VOCAL_PRESENT_REL_LU:.1f} LU)"
            )
    if frac < config.VOCAL_PRESENT_VOICED_FRAC:
        reasons.append(
            f"too few voiced frames "
            f"({frac * 100:.1f}% < {config.VOCAL_PRESENT_VOICED_FRAC * 100:.1f}%)"
        )

    return VocalReport(
        vocal_present=not reasons,
        vocal_lufs=vocal_lufs,
        mix_lufs=mix_lufs,
        rel_lu=rel_lu,
        voiced_frac=frac,
        f0_backend=backend,
        reasons=reasons,
    )
