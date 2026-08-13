"""Stage 4: move each clip onto the melody's notes, formants intact.

WORLD is the default engine because the material is exactly what it was built
for -- a clean solo sung voice -- and because formant preservation is exact
rather than approximate here: the spectral envelope is simply left untouched
while F0 is replaced. It also does pitch and time in one pass, so fitting a clip
to its slots costs nothing extra.

Two things keep this sounding like a person rather than a chipmunk:

  Octave folding, once per word. The test song's melody spans over two octaves
  while the bank sits near F3, so raw targets run to 29 semitones up. Beyond
  SHIFT_CAP_SEMITONES the shift is folded by whole octaves, which keeps the
  note NAME the melody asked for while landing it in a register the voice can
  actually reach. The octave is chosen for the whole word rather than for each
  syllable, because a word whose syllables fold differently does not bend in
  the middle, it comes apart. See fold_unit.

  Ratio, not replacement. Each syllable's own F0 contour is multiplied by a
  constant, rather than being flattened onto the target pitch. The scoop into a
  note, the vibrato, the fall at the end -- the things that make the clip sound
  sung rather than typed -- all survive the move.

  Gliding between syllables. Where a word steps from one pitch to the next it
  slides in over GLIDE_MS rather than jumping on a frame boundary, because a
  sung voice reaches a note through its approach. WORLD only; see GLIDE_MS for
  why Rubber Band cannot do this.
"""

from __future__ import annotations

from collections.abc import Sequence
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
    # A shout is kept at its own pitch and its own length on purpose, so it is
    # not slid into or out of either. Bending its tail is exactly the smoothing
    # SHOUT_KEEP_RAW exists to prevent.
    glide: bool = True
    # Hold the vowel until this moment on the output clock rather than falling
    # silent early. Set on a syllable that has another one of the same word
    # after it, to the moment that one starts.
    #
    # Deliberately separate from out_dur_s, which stays the length the melody
    # allotted. Widening out_dur_s instead would make the syllable itself
    # stretch to fill the rest, up to the TIME_STRETCH_RANGE ceiling, so a word
    # over a slow melody would come out smeared. A singer holds the vowel; they
    # do not slow the consonant down. WORLD only.
    sustain_to_s: float | None = None

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


def fold_unit(semitones: Sequence[float], cap: float | None = None) -> list[float]:
    """Fold a whole word by one octave decision instead of one per syllable.

    `fold_shift` judges a syllable on its own, so two syllables of the same
    word sitting either side of the cap are moved an octave apart from each
    other. The word does not bend in the middle, it comes apart.

    Measured on ellinoora against the curated bank: of 156 words with more than
    one pitched syllable, folding enlarged the interval inside 32 of them (21%)
    by a median of 5.5 semitones. The worst was a `perse` whose own melody
    moved 0.7 semitones and which was rendered with its halves 11.3 apart.

    Deciding the octave once for the word keeps every interval inside it
    exactly as the melody asked. The octave chosen is the one leaving the
    furthest syllable nearest its own register, ties going to the smaller move.
    A word that needed no folding at all is returned untouched, so this changes
    nothing for the majority that never crossed the cap.
    """
    cap = config.SHIFT_CAP_SEMITONES if cap is None else cap
    values = [float(s) for s in semitones]
    if not values or max(abs(v) for v in values) <= cap:
        return values

    def worst(k: int) -> float:
        return max(abs(v - 12.0 * k) for v in values)

    lo = int(min(values) // 12.0) - 1
    hi = int(max(values) // 12.0) + 2
    best = min(range(lo, hi + 1), key=lambda k: (worst(k), abs(k)))

    # With a cap under 6 semitones no octave can satisfy every syllable; return
    # what was asked rather than moving the word for no gain.
    if worst(best) >= worst(0):
        return values
    return [v - 12.0 * best for v in values]


def apply_glide(semis: np.ndarray, placed: Sequence[tuple[int, int, float, bool]],
                step_s: float, glide_ms: float | None = None) -> np.ndarray:
    """Slide between a word's syllables instead of stepping on a frame edge.

    `placed` is each rendered syllable as (first frame, last frame, semitones,
    may glide), in output order. Returns the per-frame semitone track.

    A sung voice reaches a note through its approach, and the step is a good
    part of what makes a word read as a run of separate syllables. The slide is
    linear in semitones, because a ramp in frequency ratio would sit sharp for
    most of its length.

    Three things are deliberately left stepping:

    - A join with silence in it. The gap between two words is where the pitch
      is allowed to change outright, and sliding across it would sound like one
      long word.
    - Either side asking not to be glided, which is how a shout keeps the pitch
      it was recorded at.
    - Anything at all when GLIDE_MS is 0, which restores the old behaviour
      exactly rather than approximately.
    """
    glide_ms = config.GLIDE_MS if glide_ms is None else glide_ms
    half = int(round((glide_ms / 1000.0) / step_s / 2.0))
    if half <= 0:
        return semis

    out = semis.copy()
    for (a0, _a1, a_st, a_ok), (b0, b1, b_st, b_ok) in zip(placed, placed[1:]):
        if b0 > _a1 or a_st == b_st or not (a_ok and b_ok):
            continue
        # Never take more than half of either syllable, so a short one between
        # two others still states its own pitch instead of being swallowed by
        # the slide into it and the slide out of it.
        left = max(a0 + (_a1 - a0) // 2, b0 - half)
        right = min(b0 + (b1 - b0) // 2, b0 + half)
        if right - left >= 2:
            out[left:right] = np.linspace(a_st, b_st, right - left)
    return out


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
    # Held in semitones rather than as a frequency ratio, because the glide
    # below has to be linear in pitch. Ramping the ratio instead would leave
    # the slide sitting sharp for most of its length.
    semis = np.zeros(n_out, dtype=float)
    gate = np.zeros(n_out, dtype=bool)
    placed: list[tuple[int, int, float, bool]] = []

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
        semis[j0:j1] = seg.semitones
        gate[j0:j1] = True

        # Hold the vowel out to the next syllable. TIME_STRETCH_RANGE caps how
        # far a syllable may be stretched, and a short one cannot always reach
        # the note after it, which left the word cut in half by silence. One
        # frame is repeated instead, which is a held note rather than the
        # smeared one that stretching further would give.
        if seg.sustain_to_s is not None:
            j_end = min(n_out, int(round(seg.sustain_to_s / step_s)))
            if j_end > j1:
                # The last VOICED frame, not simply the last one. A syllable
                # cut at an energy valley often ends inside a consonant, and
                # holding an unvoiced frame synthesises as silence, which is
                # the hole this exists to fill. Measured on the curated bank,
                # 1 syllable in 31 ends unvoiced.
                voiced = idx[f0[idx] > 0]
                src_index[j1:j_end] = voiced[-1] if voiced.size else idx[-1]
                semis[j1:j_end] = seg.semitones
                gate[j1:j_end] = True
                j1 = j_end

        placed.append((j0, j1, seg.semitones, seg.glide))

    semis = apply_glide(semis, placed, step_s)

    f0_out = f0[src_index] * 2.0 ** (semis / 12.0)
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

    # Put the original samples back wherever the source had no pitch.
    #
    # An unvoiced frame carries no f0, so shifting it changes nothing a
    # listener can hear and everything WORLD can get wrong: with no harmonic
    # structure to move it rebuilds the frame from aperiodicity alone, and a
    # long unvoiced stretch comes back as a tearing scratch. This voice sings
    # a great deal of its content breathy, up to a second at a time and only
    # a few dB below the voiced parts, so those stretches were most of what
    # was breaking, in both singers and worst in the lower one.
    #
    # Only where the mapping is one-to-one in time, which is every render
    # that does not stretch. Where a syllable is being re-timed the source
    # samples no longer line up and there is nothing to put back.
    aligned = np.abs(np.arange(n_out) - src_index) <= 1
    restore = (f0[src_index] <= 0.0) & aligned & gate
    if restore.any():
        hop = int(round(step_s * sr))
        keep = np.repeat(restore, hop)
        keep = (np.concatenate([keep, np.zeros(len(y) - len(keep), dtype=bool)])
                if len(keep) < len(y) else keep[:len(y)])
        original = np.zeros(len(y), dtype=np.float32)
        shared = min(len(mono), len(y))
        original[:shared] = mono[:shared]
        # Ramped over 5 ms so the joins cannot click.
        ramp = max(1, int(0.005 * sr))
        weight = np.convolve(keep.astype(np.float32),
                             np.ones(ramp, dtype=np.float32) / ramp, mode="same")
        weight = np.clip(weight, 0.0, 1.0)
        y = y * (1.0 - weight) + original * weight

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

    That also means GLIDE_MS does nothing here. The pitch steps between
    syllables, and the crossfade blurs the join without bending it. Words still
    hold together, because the octave is chosen once per word before the
    segments ever reach an engine.
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
