# TODO

## MODE B, hardest problem, deferred

> With no original vocal there is no melody or timing to borrow, so the tool
> must invent where and on what pitch each word is sung against the
> instrumental. That is composition, not signal processing: choosing note,
> onset and duration per word so it fits the chord progression and grooves. A
> naive version (place words on detected beats, pick pitch from the song's
> key/bass) is achievable but sounds mechanical; a genuinely good version is
> research-grade and has no ready off-the-shelf part. Build only after Mode A
> is solid, so the only new problem here is melody invention rather than
> everything at once.

### Current behaviour

Mode B is **detected, not attempted**. After separation the tool measures the
vocal stem's loudness relative to the mix and its fraction of confidently
voiced frames; a song failing either test exits with code 3 and the
"not supported yet" message in `cli.py`, printing the numbers that produced the
verdict so a misclassification is diagnosable rather than mysterious.

### What Mode B would need, when it happens

Everything Mode A borrows from the original singer would have to be invented:

1. **Harmonic context**, chord progression over time, so an invented note is
   consonant rather than merely in key. Chord recognition is the tractable part
   (`madmom`, or a chroma-template approach over librosa CQT).
2. **A note grid**, beat and downbeat tracking becomes load-bearing here, in a
   way it is not in Mode A. This is where a proper tracker (`beat_this`) earns
   its dependency over `librosa.beat`.
3. **Melody invention**. The actual hard part. Choosing a pitch per slot from
   the chord tones, with enough contour and repetition to read as a tune rather
   than a random walk over the scale. No off-the-shelf component does this
   well for a fixed, arbitrary lyric.
4. **Phrasing**, deciding where phrases start and stop against the
   arrangement, so words do not machine-gun continuously through the whole
   track.

A first naive pass would be: downbeat grid → one word per bar → pitch from the
bass note of the current chord, an octave up. Expect it to sound like a drum
machine reading a shopping list. That is the point at which the real work
starts, and the reason it is not being started now.

---

## Build order (Mode A)

- [x] **1. CLI skeleton**, isolated venv, mp3 in / mp3 out, Demucs separation
      wired with a Roformer alternative, instrumental saved, Mode B detection
      routing to the not-supported message.
- [x] **2. Analysis**, beat/tempo via librosa; melody F0 and syllable timing
      from the original vocal, written to `analysis.json`. Reported on a real
      song, which exposed two bugs that synthetic material had hidden: voicing
      dropouts ending notes, and a splitter that quantised to a semitone grid.
      Both fixed and pinned by tests.
- [x] **3. Word mapping, no pitch shift**, bank units placed on the extracted
      slots at their original pitch, mixed, output. Judged funny enough to
      continue.
- [x] **4. Pitch shift**. Each clip moved to its slot's melody note,
      formant-corrected, with `SHIFT_CAP_SEMITONES` folding large jumps by
      whole octaves instead of chipmunking. Re-mixed.

Everything since is refinement rather than plan: `MIMICRY` as a dial that means
the same thing across songs, density and climax control, raw shouts, and the
switchable banks.

## Stage 2 findings so far

Measured against synthesised singing whose notes and onsets are known exactly.
Synthetic material only. A real song has not been run yet.

**Accuracy is not the problem.** Across two melodies (32 and 24 syllables):

| | melody A | melody B (9 repeated notes) |
|---|---|---|
| syllables matched | 32/32 | 24/24 |
| onset error | median 0 ms, p90 10 ms | median 0 ms, p90 20 ms |
| pitch error | max 0.072 semitones | max 0.043 semitones |

The two-signal boundary design is earning its place: 6 of melody B's matched
slots were opened by onset detection alone. Those are the repeated notes, which
produce no pitch movement whatsoever. With pitch alone they would have merged
silently and every subsequent word would have landed wrong. `test_analysis.py`
pins this case specifically.

Beat tracking reads 99.4 BPM against a 100 BPM ground truth.

**Over-segmentation is the problem.** 43 slots detected for 32 true syllables
(~25% too many); spurious onsets fire mid-syllable, splitting one syllable into
e.g. 170 ms + 250 ms at the same pitch. They are too long for
`MIN_SYLLABLE_S` to merge away in stage 3, so words would land denser than the
original singing.

`ONSET_DELTA` has deliberately NOT been tuned to suppress this. The synthetic
voice ramps vibrato in at a fixed 250 ms into every syllable, which is the most
likely thing those false onsets are tracking, and real singing does not do that.
Tuning the constant against that artifact would fit it to a signal the tool will
never see. Resolve it on a real vocal.

## Open items

- **Record word takes at higher pitches. Still the way to reach the last of
  it, but much less urgent than it was.**

  The cap was the larger part of this. It sat at 7 semitones on the assumption
  that a bigger stretch sounds worse than landing an octave out, and on this
  material it does not: at 12 both test songs sound better by ear, and the mean
  ceiling across fourteen songs went from 0.78 to 0.90. See
  SHIFT_CAP_SEMITONES for the measurement and the listening result.

  What remains is the songs that still fold heavily, which are the ones sitting
  furthest above the bank: musickorea at 0.60 with 75% still folded, music8 at
  0.81, music46 and music45 at 0.82. Those are a range problem and no cap
  setting reaches them.

  A folded syllable lands on the right note *name* in the wrong register, so it
  carries the tune only in part, and that is what caps a song's ceiling.

  The bank looks like it has range and does not. Of 37 units, the spread that
  matters is narrower than the total:

  | category | units | spread | shiftable? |
  |---|---|---|---|
  | bare shouts | 2 | one pitch | never shifted at all |
  | climax-only | 7 | A#3-E4, 6.0 st | peaks only |
  | **ordinary. What actually places** | **28** | **E3-B4, 19.3 st** | yes |

  The ordinary spread reads wide and is not: 25 of those 28 sit below MIDI 55,
  so the top of the range is a handful of outliers. Against melodies whose
  median sits 5 to 14 semitones above the bank, selection cannot invent a pitch
  the bank does not hold, and wiring up `PREFER_NEAREST_SOURCE_PITCH` moved
  folding only a couple of points for exactly that reason. An earlier estimate
  of 1% was made by measuring the whole bank, shouts included, and was wrong.

  What would move it: **more takes of the ordinary words sung noticeably
  higher.** A handful would do it.

  What would *not* move it: more shouts (never shifted, so their spread is
  decorative), more takes at the pitch the bank already has, or any further
  tuning of selection weights.

  `python -m song_generator.doctor` reports this breakdown per bank.

  **Measured on the current bank, 37 clips, 14 songs.** The ceiling tracks one
  number almost exactly: how far the melody sits above the bank. The middle
  column is what this looked like before the cap was raised, kept because it is
  what the range problem costs when nothing else absorbs it.

  | song | melody | above bank | ceiling at cap 7 | at cap 12 |
  |---|---|---|---|---|
  | musickorea | 67.9 | +14.4 | 0.51 | 0.60 |
  | music8 | 63.7 | +10.1 | 0.62 | 0.81 |
  | musichyva | 62.2 | +8.6 | 0.75 | 0.86 |
  | cardib_up | 63.4 | +9.9 | 0.68 | 0.96 |
  | rocketman_bluegrass | 58.7 | +5.1 | 0.87 | 0.99 |
  | paskaperse | 53.5 | 0.0 | 0.95 | 1.00 |

  Mean 0.78 then, 0.90 now. The bank sits at MIDI 53.6 with a 10-90 percentile
  span of 53.3 to 61.0, so it has almost no register of its own, and the songs
  that still fold are simply the ones furthest from it.

  **If higher takes cannot be recorded, the same range can be generated once,
  offline, per clip.** Simulated over all 14 songs, assuming a variant that
  sounds as good as a recording:

  | variants held per clip | mean ceiling | worst song | songs at 1.00 |
  |---|---|---|---|
  | none, today | 0.90 | 0.60 | 1 of 14 |
  | +12 | 0.97 | 0.82 | 6 of 14 |
  | +12, +24 | 0.98 | 0.82 | 9 of 14 |
  | -12, +12, +24 | **1.00** | **1.00** | **14 of 14** |

  A single octave up captures most of it. That the grid is this coarse is not
  luck: `fold_shift` already reduces any shift to a residual within +/-6
  semitones and discards only the octave, so octave-spaced variants restore
  exactly what folding throws away and the engine handles the rest at a
  distance it is already good at.

  Sizing: 37 clips x 3 octaves is about 111 files and 70 MB against a 23 MB
  standardised tier.

  **Measured where the engine actually starts to suffer.** Twelve clips, each
  shifted upward and compared against its own unshifted self. The 0 st row is
  the control: resynthesis costs something even when nothing moves, so that is
  the floor, not zero.

  | shift | formants | harmonicity | envelope error |
  |---|---|---|---|
  | 0 st | 1.001 | +0.1 | 0.051 |
  | 6 st | 1.023 | +0.9 | 0.053 |
  | **7 st, the cap** | 1.022 | +0.8 | 0.058 |
  | **9 st** | 1.001 | +0.7 | 0.062 |
  | 10 st | 1.015 | +2.1 | 0.061 |
  | **12 st** | 0.986 | +3.3 | 0.126 |
  | 14 st | 1.034 | +3.6 | 0.080 |

  Formants never drift: WORLD holds the vocal tract within 4% of its own size
  at every shift out to 16 semitones, so the chipmunk the cap exists to
  prevent does not happen at any distance the tool would ask for.

  What does change is harmonicity, which rises as a vocoder smooths a rough
  voice toward a clean tone, and that is the thing worth protecting here. It is
  flat out to 9 semitones and then climbs.

  So the cap is not where the damage begins. **9 is nearly free**: same
  harmonicity as 7, envelope error a hair above it, and on the ceiling table
  above it takes rocketman from 0.87 to 0.96 and musicwtf from 0.86 to 0.96.
  **12 is not free**: harmonicity up 2.5 dB over the cap and envelope error
  more than doubled, which is the smoothing that would cost the voice its
  roughness.

  Raising the cap to 9 looks defensible on measurement alone. Going past that
  is an ear question, and scratch/cap holds two songs rendered at 7 and at 12
  for exactly that.

  **The arithmetic above proves what is reachable, not that it is reachable.**
  It assumes a +12 variant sounds like a recording. Generating those variants
  with WORLD would buy nothing, because that is what a live +12 shift already
  does and the reason folding exists is that it sounds wrong. The gain exists
  only if something generates a better one, which is what a voice model would
  be for. So the first step is not a pipeline:

  1. Take one word. Produce it an octave up three ways: the existing WORLD
     shift, a voice model, and if possible a real recording of that word sung
     an octave higher. Listen. If the model is not clearly better than WORLD,
     the whole idea is dead and no pipeline is worth building.
  2. Only then: generate variants once per bank into a derivative tier beside
     the recordings, under the same rules `standardize.py` already follows,
     since a generated clip is a derivative of a hand-recorded one and must
     never be able to overwrite it.
  3. Selection needs no new logic. A variant is another `Unit` with a different
     `midi`, and `PREFER_NEAREST_SOURCE_PITCH` already prefers the nearest
     take. `unit_fit` becomes honest about the ceiling for free.

  Keeping the runtime deterministic is the reason for generating up front
  rather than shifting live: the tool chooses among files that exist rather
  than running a model mid-render, and a clone without the extra behaves
  exactly as it does today.

## Resolved

Kept rather than deleted, because each says what was tried and why the answer
turned out the way it did.

- **Syllables turned out to be worth keeping.** They crowded out the words
  when they could be sung on their own: a clip of `bra` filled a slot as
  neatly as one of `bravo` and said nothing. The pool a song is chosen from is
  now filtered to whole words, so a bare syllable is never placed, and those
  clips do the job they were always meant for. `arrange.py` cuts them apart
  and spells words no recording contains, which on the current bank is every
  take of two words. `set_aside` still exists for a bank whose syllables
  really are junk, and reports which words would stop being spellable first.

  Shouts were always exempt: the shout is a real utterance and the only
  odd-length unit, so it is the only thing that fits the leftover slot of an
  odd phrase.

- **Every word in the vocabulary now has a clip.** The climax word was missing
  for a long time, since it appeared nowhere in the source material the bank
  was first cut from, and the bank ran on four of the five words. It arrived
  from another source. `python -m song_generator.doctor` reports any word
  still missing, and currently reports none.

- **Syllable boundaries are detected and hand-correctable.** Detection from
  energy valleys is implemented in `build_bank.syllable_boundaries` and runs
  on every build: 34 of 37 clips on the current bank carry boundaries, and the
  three without are single syllables that correctly have none.

  Hand correction is still expected to beat the detector on any clip with a
  soft internal consonant, and `words.json` is designed for it. Edit
  `syllable_bounds_s` and add `"hand_corrected": true`, and a later rebuild
  keeps your values instead of stamping over them. Nothing has been corrected
  yet, so that gain is available and unclaimed.

- **WORLD wins as the shift engine.** Both are implemented and `SHIFT_ENGINE`
  chooses; `--engine` overrides per run. Measured across ten bank clips at the
  shifts the tool actually asks for, formants relative to the unshifted source
  where 1.00 is a vocal tract the same size:

  | shift | engine | formants | harmonicity | seconds |
  |---|---|---|---|---|
  | 4 st | world | 1.026 | -0.1 | 13.5 |
  | 4 st | rubberband | 0.993 | +1.8 | 4.2 |
  | 8 st | world | 1.017 | +1.0 | 9.0 |
  | 8 st | rubberband | 0.933 | +4.8 | 4.5 |
  | 12 st | world | 0.984 | +2.3 | 9.6 |
  | 12 st | rubberband | 0.850 | +7.6 | 4.5 |

  WORLD holds the vocal tract within 3% of its own size at every shift. Rubber
  Band darkens steadily, 15% down by an octave, and smooths harder: +7.6 dB of
  harmonicity against WORLD's +2.3, which on shouted material is the roughness
  going away.

  Rubber Band is about twice as fast, and that is the only thing it wins.
  Resynthesis is around 25 seconds a song, so halving it buys little against
  sounding further from the singer.

  Worth knowing before re-running this: Rubber Band spent a long time with
  formant preservation switched off entirely, reading 1.35x at an octave, so
  any comparison made before that was fixed judged a version nobody meant to
  ship. It is kept as an alternative because darker and smoother is a real
  colour, not because it is a contender for the default.
