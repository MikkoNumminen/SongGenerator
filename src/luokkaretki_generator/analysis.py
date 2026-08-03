"""Stage 2: pull the melody and the syllable timing out of the original vocal.

This is where Mode A gets everything it needs. The original singer already
decided when each syllable starts, how long it lasts and what note it lands on;
this module recovers those decisions so stage 3 can put different words on them.

Slot boundaries come from two independent signals, because neither alone is
enough:

  pitch change - a new note in the F0 contour. Misses two syllables sung on the
                 same note ("pa-pa"), which produce no pitch movement at all.
  onset        - a consonant attack in the energy envelope. Misses a slurred
                 pitch change that arrives with no new attack.

Their union is the slot grid. Musical cleanup of that grid (merging blips,
splitting held notes) deliberately happens later, in stage 3, so that
analysis.json stays a faithful record of what was actually heard rather than
something already massaged toward a mapping decision.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import audio_io, config
from .util import resolve_device

A4_MIDI = 69
A4_HZ = 440.0


def hz_to_midi(hz: np.ndarray | float) -> np.ndarray | float:
    return A4_MIDI + 12.0 * np.log2(np.asarray(hz, dtype=float) / A4_HZ)


def midi_to_hz(midi: np.ndarray | float) -> np.ndarray | float:
    return A4_HZ * 2.0 ** ((np.asarray(midi, dtype=float) - A4_MIDI) / 12.0)


@dataclass
class Note:
    i: int
    onset_s: float
    offset_s: float
    dur_s: float
    midi: float      # unrounded, so stage 4 can shift to the real pitch
    midi_q: int      # nearest semitone, for reporting and for key estimates
    hz: float
    conf: float      # mean periodicity across the note
    rms_db: float
    phrase: int
    source: str      # "pitch", "onset" or "both" -- which signal opened it


@dataclass
class Phrase:
    i: int
    start_s: float
    end_s: float
    n_notes: int


@dataclass
class Analysis:
    sr: int
    duration_s: float
    tempo_bpm: float
    beats_s: list[float]
    f0_hop_s: float
    f0_hz: list[float]
    f0_voiced: list[bool]
    notes: list[Note] = field(default_factory=list)
    phrases: list[Phrase] = field(default_factory=list)

    def to_json(self, path: Path, include_f0: bool = True) -> Path:
        payload = {
            "sr": self.sr,
            "duration_s": round(self.duration_s, 3),
            "tempo_bpm": round(self.tempo_bpm, 2),
            "beats_s": [round(b, 4) for b in self.beats_s],
            "notes": [_round_note(asdict(n)) for n in self.notes],
            "phrases": [asdict(p) for p in self.phrases],
        }
        if include_f0:
            payload["f0"] = {
                "hop_s": self.f0_hop_s,
                "hz": [round(v, 2) for v in self.f0_hz],
                "voiced": self.f0_voiced,
            }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path


def _round_note(d: dict) -> dict:
    for k in ("onset_s", "offset_s", "dur_s"):
        d[k] = round(d[k], 4)
    for k in ("midi", "conf"):
        d[k] = round(d[k], 3)
    d["hz"] = round(d["hz"], 2)
    d["rms_db"] = round(d["rms_db"], 1)
    return d


# ---------------------------------------------------------------------------
# F0
# ---------------------------------------------------------------------------

def extract_f0(
    mono: np.ndarray,
    sr: int = config.SAMPLE_RATE,
    device: str | None = None,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Return (hz, periodicity, hop_s). hz is NaN where unvoiced."""
    method = config.F0_METHOD
    if method == "crepe":
        hz, per, hop_s = _f0_crepe(mono, sr, device)
    elif method == "pyin":
        hz, per, hop_s = _f0_pyin(mono, sr)
    else:
        raise ValueError(
            f"F0_METHOD={method!r} is not implemented.\n"
            "    Working values: 'crepe' (default, GPU) or 'pyin' (CPU fallback).\n"
            "    'rmvpe' and 'fcpe' are named in config.py as future options only.\n"
            "    Set it in the STAGE 2 block of src/luokkaretki_generator/config.py."
        )

    hz = np.where(per >= config.VOICED_PERIODICITY_MIN, hz, np.nan)
    return hz, per, hop_s


def _f0_crepe(mono, sr, device):
    import torch
    import torchcrepe

    hop_length = max(1, int(round(config.F0_HOP_S * sr)))
    audio = torch.from_numpy(np.ascontiguousarray(mono))[None]

    with torch.no_grad():
        pitch, periodicity = torchcrepe.predict(
            audio, sr,
            hop_length=hop_length,
            fmin=config.F0_MIN_HZ,
            fmax=config.F0_MAX_HZ,
            model=config.F0_MODEL,
            batch_size=512,
            device=resolve_device(device),
            return_periodicity=True,
        )
        # A 3-frame median on periodicity is the standard torchcrepe cleanup:
        # it removes single-frame voicing dropouts that would otherwise chop a
        # sustained note into several slots.
        periodicity = torchcrepe.filter.median(periodicity, 3)

    return (
        pitch.squeeze(0).cpu().numpy().astype(float),
        periodicity.squeeze(0).cpu().numpy().astype(float),
        hop_length / sr,
    )


def _f0_pyin(mono, sr):
    import librosa

    hop_length = max(1, int(round(config.F0_HOP_S * sr)))
    hz, voiced_flag, voiced_prob = librosa.pyin(
        mono, fmin=config.F0_MIN_HZ, fmax=config.F0_MAX_HZ, sr=sr, hop_length=hop_length
    )
    per = np.where(np.asarray(voiced_flag), np.asarray(voiced_prob), 0.0)
    return np.nan_to_num(np.asarray(hz), nan=0.0), per, hop_length / sr


# ---------------------------------------------------------------------------
# Slot boundaries
# ---------------------------------------------------------------------------

def bridge_voicing_gaps(
    hz: np.ndarray, voiced: np.ndarray, hop_s: float
) -> tuple[np.ndarray, np.ndarray]:
    """Fill brief unvoiced dropouts inside a sung region.

    A pitch tracker loses voicing on consonants, breaths and rough phonation.
    Left alone, each dropout ends one note and starts another, so a single held
    syllable comes out as a burst of 60 ms fragments. Only gaps bounded by
    voicing on BOTH sides are bridged -- the silence before and after a phrase
    must stay a real boundary.
    """
    max_gap = max(1, int(round(config.VOICED_GAP_FILL_S / hop_s)))
    voiced = voiced.copy()
    hz = hz.copy()

    start = None
    for i, v in enumerate(voiced):
        if not v and start is None:
            start = i
        elif v and start is not None:
            if start > 0 and (i - start) <= max_gap:
                # Interpolate across the gap so the semitone contour stays
                # continuous and does not read as a pitch jump.
                lo, hi = hz[start - 1], hz[i]
                if np.isfinite(lo) and np.isfinite(hi):
                    hz[start:i] = np.linspace(lo, hi, i - start + 2)[1:-1]
                    voiced[start:i] = True
            start = None

    return hz, voiced


def _voiced_runs(voiced: np.ndarray, min_frames: int) -> list[tuple[int, int]]:
    """Contiguous [start, end) index ranges where voiced is True."""
    runs, start = [], None
    for i, v in enumerate(voiced):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_frames:
                runs.append((start, i))
            start = None
    if start is not None and len(voiced) - start >= min_frames:
        runs.append((start, len(voiced)))
    return runs


def _smooth_semitones(sem: np.ndarray, hop_s: float) -> np.ndarray:
    from scipy.ndimage import median_filter

    width = max(1, int(round(config.F0_MEDIAN_S / hop_s)))
    if width % 2 == 0:
        width += 1
    return median_filter(sem, size=width, mode="nearest")


def _pitch_split_points(sem_smooth: np.ndarray, hop_s: float) -> list[int]:
    """Indices (relative to the run) where the sustained pitch changes.

    Compares the contour against the running median of the current note rather
    than against a quantised semitone grid. Rounding to the nearest semitone
    looks reasonable until a singer sits between two of them -- the source scene
    hovers at MIDI 53.5, where rounding flips between F3 and F#3 on tracker
    noise alone and manufactures a boundary every few frames.

    A deviation must also persist for NOTE_SPLIT_SUSTAIN_S before it counts,
    so vibrato overshoot and the scoop into a note do not split it.
    """
    sustain = max(1, int(round(config.NOTE_SPLIT_SUSTAIN_S / hop_s)))
    # Bound the reference window so cost stays linear on long held notes.
    max_window = max(sustain, int(round(0.5 / hop_s)))

    splits: list[int] = []
    anchor = 0
    deviating = 0

    for i in range(1, len(sem_smooth)):
        window = sem_smooth[max(anchor, i - max_window):i]
        if window.size == 0:
            continue
        reference = float(np.median(window))

        if abs(sem_smooth[i] - reference) >= config.NOTE_SPLIT_SEMITONES:
            deviating += 1
            if deviating >= sustain:
                # Date the boundary from where the deviation began, not from
                # where it was confirmed, or every onset lands late.
                start = i - deviating + 1
                splits.append(start)
                anchor = start
                deviating = 0
        else:
            deviating = 0

    return splits


def detect_onsets(mono: np.ndarray, sr: int, hop_s: float) -> np.ndarray:
    """Onset times in seconds, from spectral flux on the vocal stem."""
    import librosa

    hop_length = max(1, int(round(hop_s * sr)))
    return librosa.onset.onset_detect(
        y=mono, sr=sr, hop_length=hop_length, units="time",
        backtrack=config.ONSET_BACKTRACK, delta=config.ONSET_DELTA,
    )


def analyse(
    vocal: np.ndarray,
    instrumental: np.ndarray | None = None,
    sr: int = config.SAMPLE_RATE,
    device: str | None = None,
) -> Analysis:
    import librosa

    mono = audio_io.to_mono(vocal)
    duration = len(mono) / sr

    hz, per, hop_s = extract_f0(mono, sr, device)
    hz, voiced = bridge_voicing_gaps(hz, np.isfinite(hz), hop_s)
    sem = hz_to_midi(np.where(voiced, hz, np.nan))

    rms = librosa.feature.rms(
        y=mono, frame_length=2048, hop_length=max(1, int(round(hop_s * sr)))
    )[0]

    onset_times = detect_onsets(mono, sr, hop_s)
    onset_frames = set(int(round(t / hop_s)) for t in onset_times)

    min_frames = max(2, int(round(0.03 / hop_s)))
    merge_frames = max(1, int(round(config.BOUNDARY_MERGE_S / hop_s)))

    notes: list[Note] = []
    for start, end in _voiced_runs(voiced, min_frames):
        run_sem = _smooth_semitones(sem[start:end], hop_s)

        splits = set(_pitch_split_points(run_sem, hop_s))
        sources = {s: "pitch" for s in splits}
        for f in onset_frames:
            rel = f - start
            if min_frames <= rel < (end - start) - min_frames:
                near = [s for s in splits if abs(s - rel) <= merge_frames]
                if near:
                    sources[near[0]] = "both"
                else:
                    splits.add(rel)
                    sources[rel] = "onset"

        bounds = [0] + sorted(splits) + [end - start]
        # Collapse boundaries that ended up closer together than the merge
        # window, which the union of two detectors makes easy to produce.
        kept = [bounds[0]]
        for b in bounds[1:]:
            if b - kept[-1] >= merge_frames:
                kept.append(b)
        if kept[-1] != bounds[-1]:
            kept[-1] = bounds[-1]

        for a, b in zip(kept[:-1], kept[1:]):
            if b - a < min_frames:
                continue
            seg = slice(start + a, start + b)
            seg_sem = sem[seg]
            valid = np.isfinite(seg_sem)
            if valid.sum() < min_frames:
                continue
            midi = float(np.median(seg_sem[valid]))
            seg_rms = rms[seg] if seg.stop <= len(rms) else rms[seg.start:]
            level = float(np.sqrt(np.mean(np.square(seg_rms)))) if len(seg_rms) else 0.0

            notes.append(Note(
                i=len(notes),
                onset_s=(start + a) * hop_s,
                offset_s=(start + b) * hop_s,
                dur_s=(b - a) * hop_s,
                midi=midi,
                midi_q=int(round(midi)),
                hz=float(midi_to_hz(midi)),
                conf=float(np.mean(per[seg])),
                rms_db=float(20 * np.log10(level + 1e-9)),
                phrase=-1,
                source=sources.get(a, "pitch" if a else "start"),
            ))

    phrases = _group_phrases(notes)

    tempo, beats = _track_beats(
        instrumental if instrumental is not None else vocal, sr
    )

    return Analysis(
        sr=sr,
        duration_s=duration,
        tempo_bpm=tempo,
        beats_s=beats,
        f0_hop_s=hop_s,
        f0_hz=[float(v) if np.isfinite(v) else 0.0 for v in hz],
        f0_voiced=[bool(v) for v in voiced],
        notes=notes,
        phrases=phrases,
    )


def _group_phrases(notes: list[Note]) -> list[Phrase]:
    phrases: list[Phrase] = []
    if not notes:
        return phrases

    start_idx = 0
    for i in range(1, len(notes) + 1):
        ends = i == len(notes)
        gap = None if ends else notes[i].onset_s - notes[i - 1].offset_s
        if ends or gap > config.PHRASE_GAP_S:
            pi = len(phrases)
            for n in notes[start_idx:i]:
                n.phrase = pi
            phrases.append(Phrase(
                i=pi,
                start_s=round(notes[start_idx].onset_s, 4),
                end_s=round(notes[i - 1].offset_s, 4),
                n_notes=i - start_idx,
            ))
            start_idx = i
    return phrases


def _track_beats(audio: np.ndarray, sr: int) -> tuple[float, list[float]]:
    import librosa

    mono = audio_io.to_mono(audio)
    tempo, beat_frames = librosa.beat.beat_track(y=mono, sr=sr, units="frames")
    beats = librosa.frames_to_time(beat_frames, sr=sr)
    return float(np.atleast_1d(tempo)[0]), [float(b) for b in beats]


# ---------------------------------------------------------------------------
# Human-readable report -- the point of stage 2
# ---------------------------------------------------------------------------

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(midi_q: int) -> str:
    return f"{NOTE_NAMES[midi_q % 12]}{midi_q // 12 - 1}"


def report(analysis: Analysis, max_rows: int = 12) -> str:
    notes = analysis.notes
    lines: list[str] = []
    add = lines.append

    add("  melody + timing extraction")
    if not notes:
        add("    no sung notes found -- nothing to map words onto")
        return "\n".join(lines)

    durs = np.array([n.dur_s for n in notes])
    midis = np.array([n.midi for n in notes])
    confs = np.array([n.conf for n in notes])
    sources = [n.source for n in notes]
    sung = float(durs.sum())

    add(f"    tempo             {analysis.tempo_bpm:.1f} BPM, {len(analysis.beats_s)} beats")
    add(f"    notes found       {len(notes)} in {len(analysis.phrases)} phrases")
    add(f"    sung coverage     {sung:.1f}s of {analysis.duration_s:.1f}s "
        f"({sung / analysis.duration_s * 100:.0f}%)")
    add(f"    note duration     median {np.median(durs) * 1000:.0f} ms, "
        f"range {durs.min() * 1000:.0f}-{durs.max() * 1000:.0f} ms")
    add(f"    pitch range       {note_name(int(round(midis.min())))} to "
        f"{note_name(int(round(midis.max())))} "
        f"({midis.max() - midis.min():.1f} semitones)")
    add(f"    confidence        median {np.median(confs):.2f}")
    add(f"    boundary source   {sources.count('pitch')} pitch, "
        f"{sources.count('onset')} onset, {sources.count('both')} both, "
        f"{sources.count('start')} phrase-start")

    # The two numbers that decide how much work stage 3's mapping rule does.
    short = int((durs < config.MIN_SYLLABLE_S).sum())
    long_ = int((durs > config.MAX_SYLLABLE_S).sum())
    add(f"    stage-3 cleanup   {short} slots to merge (<{config.MIN_SYLLABLE_S * 1000:.0f} ms), "
        f"{long_} to split (>{config.MAX_SYLLABLE_S * 1000:.0f} ms)")

    odd = sum(1 for p in analysis.phrases if p.n_notes % 2)
    add(f"    phrase lengths    {odd} of {len(analysis.phrases)} phrases are odd "
        f"-> ODD_SLOT_POLICY={config.ODD_SLOT_POLICY!r} applies there")

    add("")
    add("    first notes:")
    add("      #   onset   dur    note    midi   conf  src")
    for n in notes[:max_rows]:
        add(f"      {n.i:<3} {n.onset_s:6.2f} {n.dur_s * 1000:5.0f}ms  "
            f"{note_name(n.midi_q):<5} {n.midi:6.2f} {n.conf:6.2f}  {n.source}")
    if len(notes) > max_rows:
        add(f"      ... {len(notes) - max_rows} more")

    return "\n".join(lines)
