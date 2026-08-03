# TODO

## MODE B — hardest problem, deferred

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

1. **Harmonic context** — chord progression over time, so an invented note is
   consonant rather than merely in key. Chord recognition is the tractable part
   (`madmom`, or a chroma-template approach over librosa CQT).
2. **A note grid** — beat and downbeat tracking becomes load-bearing here, in a
   way it is not in Mode A. This is where a proper tracker (`beat_this`) earns
   its dependency over `librosa.beat`.
3. **Melody invention** — the actual hard part. Choosing a pitch per slot from
   the chord tones, with enough contour and repetition to read as a tune rather
   than a random walk over the scale. No off-the-shelf component does this
   well for a fixed, arbitrary lyric.
4. **Phrasing** — deciding where phrases start and stop against the
   arrangement, so words do not machine-gun continuously through the whole
   track.

A first naive pass would be: downbeat grid → one word per bar → pitch from the
bass note of the current chord, an octave up. Expect it to sound like a drum
machine reading a shopping list. That is the point at which the real work
starts, and the reason it is not being started now.

---

## Build order (Mode A)

- [x] **1. CLI skeleton** — isolated venv, mp3 in / mp3 out, Demucs separation
      wired with a Roformer alternative, instrumental saved, Mode B detection
      routing to the not-supported message.
- [x] **2. Analysis** — beat/tempo via librosa; melody F0 and syllable timing
      from the original vocal, written to `analysis.json`.
      **Gate not yet cleared:** validated against synthesised singing with known
      ground truth, but not yet reported on a real song. See below.
- [x] **3. Word mapping, no pitch shift** — bank units placed on the extracted
      slots at their original pitch, mixed, output. First listenable version;
      awaiting a verdict on funniness before shifting is added.
- [ ] **4. Pitch shift** — each clip moved to its slot's melody note,
      formant-corrected, with `SHIFT_CAP_SEMITONES` folding large jumps by
      whole octaves instead of chipmunking. Re-mixed.

## Stage 2 findings so far

Measured against synthesised singing whose notes and onsets are known exactly.
Synthetic material only — a real song has not been run yet.

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

- **`paviaani` is not in the bank yet.** It does not appear anywhere in the
  `paskaperse.mp4` scene's labelling. Mikko is supplying it from another source
  later. Until then the bank has four of the five words, and
  `config.WORD_SYLLABLES` still lists `paviaani` (4 syllables) so it slots in
  with no code change the moment a clip named `paviaani*.wav` appears.

- **Syllable boundaries inside the word clips.** Auto-detection from energy
  valleys is planned for commit 3, written to `words/words.json`. Hand
  correcting those few numbers is expected to beat the detector noticeably, and
  the file is designed to be edited.
- **Which shift engine wins.** `SHIFT_ENGINE` defaults to `world`; `rubberband`
  is implemented as an A/B. Decide by listening once commit 4 lands.
