"""Stage 4: move each clip onto the melody's notes, formants intact.

WORLD is the default engine because the material is exactly what it was built
for -- a clean solo sung voice -- and because formant preservation is exact
rather than approximate here: the spectral envelope is simply left untouched
while F0 is replaced. It also does pitch and time in one pass, so fitting a clip
to its slots costs nothing extra.

Two things keep this sounding like a person rather than a chipmunk:

  Octave folding. The test song's melody spans over two octaves while the bank
  sits near F3, so raw targets run to 29 semitones up. Beyond
  SHIFT_CAP_SEMITONES the shift is folded by whole octaves, which keeps the
  note NAME the melody asked for while landing it in a register the voice can
  actually reach.

  Ratio, not replacement. Each syllable's own F0 contour is multiplied by a
  constant, rather than being flattened onto the target pitch. The scoop into a
  note, the vibrato, the fall at the end -- the things that make the clip sound
  sung rather than typed -- all survive the move.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import config

FRAME_PERIOD_MS = 5.0


@dataclass
class Segment:
    """One syllable's journey from where it was to where it needs to be."""
    src_start_s: float
    src_end_s: float
    out_start_s: float
    out_dur_s: float
    semitones: float

    @property
    def src_dur_s(self) -> float:
        return max(1e-6, self.src_end_s - self.src_start_s)


def fold_shift(semitones: float, cap: float | None = None) -> float:
    """Fold a shift beyond the cap by whole octaves.

    A 29-semitone jump becomes 5: the same note name, two octaves closer to the
    clip's own register. Stretching a voice that far instead would destroy it,
    and landing on the wrong octave is far less noticeable than landing on a
    chipmunk.
    """
    cap = config.SHIFT_CAP_SEMITONES if cap is None else cap
    if abs(semitones) <= cap:
        return float(semitones)

    folded = semitones - 12.0 * round(semitones / 12.0)
    # With a cap under 6 semitones no fold can always satisfy it; return the
    # closest available rather than looping.
    return float(folded if abs(folded) < abs(semitones) else semitones)


def clamp_stretch(out_dur_s: float, src_dur_s: float) -> float:
    lo, hi = config.TIME_STRETCH_RANGE
    if src_dur_s <= 0:
        return 1.0
    return float(np.clip(out_dur_s / src_dur_s, lo, hi))


# ---------------------------------------------------------------------------
# WORLD
# ---------------------------------------------------------------------------

def _analyse(mono: np.ndarray, sr: int):
    import pyworld as pw

    x = np.ascontiguousarray(mono, dtype=np.float64)
    # harvest over dio: slower, but markedly steadier on sung material, and
    # these clips are short enough that the cost is irrelevant.
    f0, t = pw.harvest(x, sr, f0_floor=config.F0_MIN_HZ, f0_ceil=config.F0_MAX_HZ,
                       frame_period=FRAME_PERIOD_MS)
    f0 = pw.stonemask(x, f0, t, sr)
    sp = pw.cheaptrick(x, f0, t, sr)
    ap = pw.d4c(x, f0, t, sr)
    return f0, sp, ap


def render_segments(mono: np.ndarray, sr: int, segments: list[Segment],
                    total_out_s: float) -> np.ndarray:
    """Resynthesise a clip so each syllable lands on its slot, at its pitch."""
    import pyworld as pw

    if not segments:
        return np.zeros(0, dtype=np.float32)

    f0, sp, ap = _analyse(mono, sr)
    n_src = len(f0)
    if n_src == 0:
        return np.zeros(int(total_out_s * sr), dtype=np.float32)

    step_s = FRAME_PERIOD_MS / 1000.0
    n_out = max(1, int(round(total_out_s / step_s)))

    src_index = np.zeros(n_out, dtype=int)
    ratio = np.ones(n_out, dtype=float)
    gate = np.zeros(n_out, dtype=bool)

    for seg in segments:
        stretch = clamp_stretch(seg.out_dur_s, seg.src_dur_s)
        sounding = min(seg.out_dur_s, seg.src_dur_s * stretch)

        j0 = int(round(seg.out_start_s / step_s))
        j1 = min(n_out, j0 + max(1, int(round(sounding / step_s))))
        if j1 <= j0:
            continue

        # Map each output frame back to a source frame within this syllable.
        local = (np.arange(j0, j1) - j0) * step_s / stretch
        idx = np.round((seg.src_start_s + local) / step_s).astype(int)
        idx = np.clip(idx, 0, n_src - 1)

        src_index[j0:j1] = idx
        ratio[j0:j1] = 2.0 ** (seg.semitones / 12.0)
        gate[j0:j1] = True

    f0_out = f0[src_index] * ratio
    f0_out[~gate] = 0.0
    sp_out = np.ascontiguousarray(sp[src_index], dtype=np.float64)
    ap_out = np.ascontiguousarray(ap[src_index], dtype=np.float64)

    y = pw.synthesize(np.ascontiguousarray(f0_out, dtype=np.float64),
                      sp_out, ap_out, sr, FRAME_PERIOD_MS)

    # Silence the frames no syllable was mapped onto. Without this the
    # unvoiced-aperiodicity path fills the gaps with breath noise.
    mask = np.repeat(gate, int(round(step_s * sr)))
    if len(mask) < len(y):
        mask = np.concatenate([mask, np.zeros(len(y) - len(mask), dtype=bool)])
    y = y[:len(mask)] * mask[:len(y)]

    return np.asarray(y, dtype=np.float32)


# ---------------------------------------------------------------------------
# Rubber Band
# ---------------------------------------------------------------------------

def render_segments_rubberband(mono: np.ndarray, sr: int, segments: list[Segment],
                               total_out_s: float) -> np.ndarray:
    """Per-syllable constant shift, crossfaded together.

    Rubber Band transposes by a fixed amount per pass, so unlike WORLD it
    cannot follow a contour in one go; each syllable is processed separately
    and the joins are crossfaded.
    """
    import pylibrb

    # FORMANT_PRESERVED is what actually holds the vocal tract still. Without
    # it Rubber Band lets the spectral envelope ride up with the pitch, and
    # setting formant_scale alone does nothing, because that value only scales
    # an envelope the engine has been told to preserve.
    #
    # Measured across bank clips, formant centroid against the unshifted
    # source: this path used to give 1.17x at +5 semitones and 1.35x at +12,
    # which is the chipmunk the config says it avoids. With the flag and an
    # automatic scale it is 0.98x and 0.88x.
    options = (pylibrb.Option.ENGINE_FINER | pylibrb.Option.PROCESS_OFFLINE
               | pylibrb.Option.FORMANT_PRESERVED)

    # 1.0 means "leave them where they were", which is the engine's automatic
    # scale rather than a literal 1.0: Rubber Band reads 1.0 as "do not scale
    # the preserved envelope", and the envelope still has to be scaled against
    # the pitch change to stay put.
    scale = (pylibrb.AUTO_FORMANT_SCALE if config.FORMANT_SCALE == 1.0
             else config.FORMANT_SCALE)

    out = np.zeros(int(total_out_s * sr) + sr, dtype=np.float32)
    fade = max(1, int(0.005 * sr))

    for seg in segments:
        lo = max(0, int(seg.src_start_s * sr))
        hi = min(len(mono), int(seg.src_end_s * sr))
        if hi - lo < fade * 2:
            continue

        stretch = clamp_stretch(seg.out_dur_s, seg.src_dur_s)
        stretcher = pylibrb.RubberBandStretcher(
            sample_rate=sr, channels=1,
            options=options,
            initial_time_ratio=stretch,
            initial_pitch_scale=2.0 ** (seg.semitones / 12.0),
        )
        stretcher.formant_scale = scale

        block = np.ascontiguousarray(mono[lo:hi], dtype=np.float32)[None, :]
        # Whole clip in one call, so say so. Without this Rubber Band sizes its
        # buffers for a default block, discovers the real one is larger, and
        # reallocates both of them while warning about it on every clip.
        stretcher.set_max_process_size(block.shape[1])
        stretcher.study(block, final=True)
        stretcher.process(block, final=True)
        piece = stretcher.retrieve_available()[0]

        if piece.size < fade * 2:
            continue
        piece = piece.copy()
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        piece[:fade] *= ramp
        piece[-fade:] *= ramp[::-1]

        start = int(seg.out_start_s * sr)
        end = min(len(out), start + len(piece))
        out[start:end] += piece[:end - start]

    return out[:int(total_out_s * sr)]


def render_unit(mono: np.ndarray, sr: int, segments: list[Segment],
                total_out_s: float, engine: str | None = None) -> np.ndarray:
    engine = engine or config.SHIFT_ENGINE
    if engine == "world":
        return render_segments(mono, sr, segments, total_out_s)
    if engine == "rubberband":
        return render_segments_rubberband(mono, sr, segments, total_out_s)
    raise ValueError(
        f"unknown SHIFT_ENGINE {engine!r}.\n"
        "    Expected 'world' (default) or 'rubberband'.\n"
        "    Set it in the STAGE 4 block of src/song_generator/config.py, "
        "or pass --engine on the command line."
    )
