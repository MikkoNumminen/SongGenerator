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
  | **7 st, the cap then** | 1.022 | +0.8 | 0.058 |
  | **9 st** | 1.001 | +0.7 | 0.062 |
  | 10 st | 1.015 | +2.1 | 0.061 |
  | **12 st, the cap now** | 0.986 | +3.3 | 0.126 |
  | 14 st | 1.034 | +3.6 | 0.080 |

  Formants never drift: WORLD holds the vocal tract within 4% of its own size
  at every shift out to 16 semitones, so the chipmunk the cap exists to
  prevent does not happen at any distance the tool would ask for.

  What does change is harmonicity, which rises as a vocoder smooths a rough
  voice toward a clean tone, and that is the thing worth protecting here. It is
  flat out to 9 semitones and then climbs.

  So the cap is not where the damage begins. **9 is nearly free**: same
  harmonicity as 7 and envelope error a hair above it. **12 is not free**:
  harmonicity up 2.5 dB and envelope error more than doubled, which is the
  smoothing that would cost the voice its roughness.

  **This is what the measurement said, and the ear overruled it.** On
  measurement alone 9 was the defensible number and 12 looked expensive. The
  two songs in scratch/cap were rendered at 7 and at 12 to settle it, and 12
  sounded better on both, so that is where SHIFT_CAP_SEMITONES is. What the
  numbers above priced was resynthesis damage to one clip; what they could not
  price is a whole song landing an octave out, which is what the cap was
  buying at 7. The table is kept because it is still the honest cost of a big
  shift, not because the question is open.

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

- **Nothing records where a song came from.** Eighteen songs have been analysed
  and seventeen rendered, and for most of them the only surviving trace of the
  original is a filename. `music46.mp4` says nothing about what it is, who
  recorded it or where it was fetched from, and no amount of reading the repo
  recovers that.

  This matters more than it looks, because every directory the sources live in
  is gitignored: `input/`, `work/` and `output/` are all excluded, so a fresh
  clone has no songs and no way to find them again. Four of the current songs
  were rendered straight out of a downloads folder and are not even in
  `input/`. Losing that folder loses the source.

  What to record, one row per song: the name the tool knows it by (which is the
  `work/` directory and the `output/` folder), the original address, and what
  that address is. An address is a web link for anything fetched, or a path for
  anything ripped, recorded or received as a file. The tool derives its own
  name by slugifying the input filename, so the name is a stable key.

  What is already knowable, and what is not:

  | Songs | Local source | Original address |
  |---|---|---|
  | 13 in `input/` | present | unknown, only the owner has these |
  | 4 rendered from downloads | present, outside the repo | unknown |
  | `seija_simola_-_juna_turkuun` | analysed, no input file left | unknown |

  So the local half can be filled in by listing directories, and the half worth
  having cannot. That part is a sitting-down-and-writing job for whoever has the
  links.

  One decision to make first: whether the file is tracked. `docs/` is tracked,
  so a file there publishes every link to anyone who clones the repo. If this is
  a private index of where the audio came from, it belongs beside the audio in a
  gitignored location instead, and the tracked docs need only say that it exists
  and what shape it has.

- **A live site: drop a song in, get a paskaperse back.** Nothing about the
  pipeline needs a person once the bank exists, so the interesting question is
  not whether it can be a web service but what it costs and what it hands a
  stranger.

  What a request actually costs, measured on this machine today, an RTX 3080 Ti:

  | | 5 minute song |
  |---|---|
  | Roformer separation | about 30s |
  | Whole run, analysis through 14 renders | about 4 minutes |
  | Bytes written | 14 files at 320k CBR, roughly 177 MB |

  So a naive site is a GPU queue, not a web app. Every upload occupies a real
  graphics card for minutes, and the obvious first cut is to render one level
  at one mimicry setting rather than the full 14, which is a `--play` and a
  rung away and drops the output to about 13 MB.

  Three things would have to be decided before any of it is worth building, and
  none of them are engineering:

  1. **The bank is somebody's voice.** A public site distributes those
     recordings to everyone who uses it, saying what they say. That is the
     owner's call to make explicitly, not a detail to discover after launch.
  2. **The uploads are commercial recordings**, and the output is a derivative
     of both the upload and the bank. A local tool and a public service that
     stores and serves the result are not in the same position.
  3. **Most strangers would get the worst version of it.** Ceilings measured
     across seven songs today ran from 0.99 to 0.69, and the number tracks one
     thing: how far the song sits above the bank's register. A site cannot pick
     its songs. Whatever arrives is likelier to be a wide-range pop or metal
     track, which is the material that folds hardest, so the median visitor
     hears the version that carries the tune only in part.

  Also worth knowing: Mode B is not implemented, so any upload without a vocal
  stem exits with code 3. On a site that is a user-facing error and needs a
  message written for it rather than an exit code.

- **A downloadable app, so people can do this themselves.** The other end of
  the same question, and the one that sidesteps the two legal problems above by
  never holding anyone's audio. It replaces them with a packaging problem.

  What ships is the hard part. The tool is a thin thing on top of a very thick
  stack: torch with CUDA, a separator, WORLD, torchcrepe and ffmpeg. Measured
  on this machine:

  | | size |
  |---|---|
  | `.venv` | **5.3 GB** |
  | torch hub cache | 32 MB |
  | a 25-clip bank plus its standardised tier | 26 MB |

  So the recordings, which are the entire point, are half a percent of the
  download. Everything else is the machinery, and the separator additionally
  fetches its own model weights at first run rather than carrying them, so a
  first launch needs a network connection whatever the installer contains.
  Trimming that 5.3 GB means a CPU-only torch build, which is the same
  question as the first bullet below.

  Open questions, roughly in the order they would bite:

  - **GPU or not.** Device is autodetected and a CPU path exists, but nothing
    has ever timed a CPU run. If it turns out to be an hour a song, the app is
    a different product than if it is ten minutes, and that number should be
    measured before any of this is designed.
  - **Whose bank.** Shipping the app means shipping clips, which is the same
    consent question the site raises. Alternatively the app ships empty and
    points at `build_bank`, which makes it a tool for people willing to record
    and label their own words. That is a much smaller audience and a much
    smaller problem.
  - **There is no interface.** `cli.py` is argparse, and the docs are
    PowerShell. Anyone who would download an app is not going to pass
    `--mimicry`.
  - **Windows first is currently implicit**, not decided. Nothing in the code
    is Windows-only, but every documented path is.

  The honest sequencing is that this item and the site item share one
  prerequisite, a decision about distributing the recordings, and neither is
  worth starting until that is settled.

- **`--bare-syllables` does not reach the render path, and making it would be
  a feature rather than a fix.** The flag exists, is documented, and changes
  nothing about what gets sung.

  Two things swallow it. `cli` loads the bank with `singable_only=False`, which
  skips the filter the flag controls, and `arrange.enrich` then filters to
  word-like units unconditionally. An audit found the flag being written into
  module state that outlived the run, and that leak is fixed, but fixing the
  leak did not make the flag work and was not meant to.

  Deciding what it should do is the actual question, and it is a listening
  question rather than an engineering one. Bare syllables were deliberately
  taken out of the pool once already, recorded under Resolved below: a clip of
  `bra` filled a slot as neatly as one of `bravo` and said nothing. Whether a
  flag should be able to put them back, and whether the result is funny or just
  mush, is answered by rendering it and listening, not by reading `enrich`.

  So it stays as it is until somebody wants that sound. The alternative worth
  considering is removing the flag, since a documented option that does nothing
  is worse than no option.

- **`doctor.py`'s `_bar` helper stays, and this records why so nobody audits
  it again.** One line, one call site, and a `width` parameter nothing passes.
  A smell audit flagged it as the only survivor of sixteen single-use-helper
  candidates and called it marginal itself.

  It is kept because it names what the line does. `_bar(hist[midi])` reads as a
  histogram bar; `"#" * min(hist[midi], 28)` reads as string arithmetic that
  the next person has to decode. The unused `width` is a real wart and one
  character of the file.

  Deleting a helper because it has one caller is a rule that would also delete
  every well-named private function in the codebase. Closed, not fixed.

## Resolved

Kept rather than deleted, because each says what was tried and why the answer
turned out the way it did.

- **`doctor --song` predicted almost no folding on songs that folded half
  their syllables.** It measured each note against the NEAREST take in the
  bank, which let every slot reach whichever single clip sat closest to it.
  Selection cannot do that: a unit also has to fit the slot's length and say
  the word being sung, so what a slot really draws from is the bulk of the
  bank.

  It now measures against the median pitch of the units that ordinarily place,
  the same pool the ORDINARY row of the bank report counts. Checked against
  eight rendered songs:

  | song | folded, measured | predicted now | predicted before |
  |---|---|---|---|
  | musickorea | 71% | 78% | 0% |
  | ghostlights | 67% | 71% | 1% |
  | dawn | 51% | 58% | 1% |
  | misplaced | 46% | 48% | 0% |
  | musichyva | 27% | 38% | 0% |
  | takatalvi | 10% | 11% | 1% |
  | cardib_up | 9% | 5% | 0% |
  | rocketman_bluegrass | 2% | 3% | 0% |

  The old number sat at 0 or 1 for every song whatever happened, including the
  one that folded 71%. The new one never inverts the order. On `misplaced` the
  median it reports, 10.9 semitones, is the same figure the render asked for.

  It is still an estimate and now says so in its own output. What it cannot
  know is which unit selection will actually pick for a given slot.


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
