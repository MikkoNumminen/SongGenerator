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

- **`sykeBank` has never been listened to, and declares nothing.**

  Its 137 units were mined from a fetched song and built straight into a bank:
  the 142 candidates in `words_syke_src/` went in unheard and unnamed, junk
  included, so the bank is whatever the silence split produced. Deleting the
  bad ones and rebuilding is what turns it into a bank rather than a pile.

  It also has no `bank.json`, so it takes the defaults: `arranged` at both
  levels, clips splittable. On generated speech that means the word endings are
  cut and stretched exactly as `asuntoautoBank` was before it was tuned.
  Nothing has been rendered with it yet, so nobody has hit that. Give it a
  declaration before anything is.

  `words_asuntoauto_src/candidates/` has had no systematic listening pass
  either, though its cuts are at least verified against the source.

- **The run report states two things that are not true.**

  `mapping.py` prints `engine {config.SHIFT_ENGINE}` rather than the engine the
  run actually used, so `--engine rubberband` reports "world". It misled an
  entire A/B comparison before somebody checked the audio differed.

  It also prints `truncated N units cut short by the next entry`, counting any
  placement whose play time is under the clip's natural length. A reading speed
  above 1.0 makes that every placement, cut or not: a recitation at 1.3 reported
  123 units cut short with nothing cut. The number that matters is how many were
  clamped past the stretch range, which is not what this counts.

  Both are one-line fixes and both are in the report the diagnostic ladder in
  `docs/WORKFLOWS.md` tells people to read.

- **Four settings change the audio without changing the filename.**

  `--engine`, `--separator`, `--raw-clips` and `--bare-syllables` all produce
  materially different renders under exactly the same name, so each overwrites
  the take before it and `previous/` keeps only one generation. `variant_tag`
  already names what was asked for specially, for `--mimicry`, `--no-shift`,
  `--mix` and `--arrangement`; these four were left out of it.

  `--no-words` is worse: it writes an untagged instrumental straight into the
  bank folder, bypassing `versioned_name` and `keep_the_one_it_replaces`
  entirely, so it appears in the library as a take with neither level nor
  variant in its name and `--rollback` can never bring back what it replaced.

- **Noted, not a problem here: `pylibrb` is GPLv2 while `LICENSE` is MIT.**

  Recorded because it is the kind of thing that looks like an oversight later.
  `pylibrb` is a required dependency in `pyproject.toml` and bundles the Rubber
  Band Library, which is GPL-or-commercial. It is free of charge, which is the
  bar this repository sets.

  Copyleft only bites on distribution, and nothing here is distributed: this is
  one person's tool that happens to be readable on GitHub. Left alone
  deliberately. If it ever were packaged for anyone else, the one-line move to
  `[project.optional-dependencies]` beside `roformer` is what that would need,
  and nothing about a render would change, since WORLD is the default and
  measures better on this material anyway.

- **Renders from before the naming rule are still on disk.**

  `output/bussilaulu_.../ttsfi/` holds four files: the two current names and
  two `.mim1p00` leftovers from when a run wrote a rung tag. They are the same
  two takes under two naming schemes, so the library lists each twice. Worth a
  sweep for `*.mim1p00.mp3` beside an untagged twin, rather than deleting by
  hand one folder at a time.

- **The planner predicts folding by a different rule than the renderer uses.**

  `pitch_cost` in `mapping.py` measures a candidate against the MEAN shift
  across the notes it would cover. `build_segments` hands the word to
  `fold_unit`, which folds on the LARGEST shift any of its syllables needs. A
  three-syllable word wanting +2, +5 and +8 against a cap of 6 is predicted
  unfolded, charged no penalty, chosen, and then folded whole.

  The fix is one line, `max` by absolute value instead of `np.mean`, and it was
  written and then reverted deliberately. It re-ranks every candidate, so every
  arrangement this repository has a golden value for moves, and
  `tests/test_determinism.py` pins two of them. That is a listening decision
  about every bank rather than a correctness fix to slip into an unrelated
  branch: the renders would all change, and only an ear can say whether they
  changed for the better.

  Do it on its own, with the goldens updated in the same commit and a listening
  pass on the default bank before and after.

- **Tune the wild level for a multi-voice bank.**

  `shuffled` exists because the only placement that neither cuts, stretches
  nor syllabifies a word is the reciting one, and that one is deterministic:
  a bank declaring `sequence` for both levels wrote two identical files.
  Shuffling the running order varies the take while leaving every clip exactly
  as recorded. That much works.

  What it does not do is know whose voice it is holding. `asuntoautoBank` now
  carries three singers, and conservative keeps them in blocks only because
  reciting in bank order happens to group them: the female phrases were built
  first, then the male, then the reader. Shuffling throws that away, so wild
  moves between three people at random, which is the gibberish the bank was
  explicitly asked not to produce.

  Fixing it properly needs the bank to record which voice each clip is, and
  the shuffle to draw in runs rather than per clip: a few clips of one singer,
  then a few of the next. `build_bank --raw` has nowhere to put that today,
  since every unit it writes is called `raw`. The natural home is a field in
  `words.json` and a matching key in `bank.json`, so a bank can say how long a
  run should be, the way it already says how far its voice may be shifted.

  A third thing belongs with it: **seasoning**. The reader voice is meant to
  appear seldom and unpredictably, the way `SHOUT_WORDS` and `CLIMAX_WORDS`
  season an arranged bank. Reciting has no such notion: every clip gets its
  turn once per cycle, so rarity can only be bought by keeping fewer copies,
  and even a single clip returns on a fixed beat as the sequence loops. A
  per-clip appearance weight, read by the reciting cursor rather than only by
  the planner, is what that wants.

  Two smaller things belong with it. `arranged` remains unusable for a bank
  like this, because fitting a clip to a note means stretching it, and a clip
  squeezed past about 0.6 stops sounding like the word. And a `shuffled` take
  is only as repeatable as its seed, so a run worth keeping has to be brought
  back with `--seed` or replayed from its `.arr` log.

- **A real waveform on the track being played.**

  The idea that started this was a whole look built around waveforms: every
  row in the library drawn as the shape of its own audio, colour taken from
  the sound rather than from a palette. It was dropped rather than attempted,
  and the reason is worth keeping.

  The edge reports a rendering's size, not its shape. Drawing a real waveform
  needs peak data that nothing currently produces, so a list of it would mean
  either decoding megabytes per row in the browser, which makes the list slower
  exactly where speed was just bought, or inventing squiggles, which is
  decoration pretending to be measurement.

  The version that would earn its keep is narrow: one waveform, for the take
  currently playing, drawn from peaks written beside the mp3 at render time.
  That is a small addition to the render step, a few hundred bytes per
  rendering, and a backfill pass over what already exists. It also gives a
  playhead something to move along, which is the part a person would actually
  use.

  Not scheduled. Written down because the reasoning is the useful part: the
  cost is generating data that does not exist yet, not drawing it.

- **Make vocals with AudiobookMaker.**

  A bank needs clean, isolated, pitch-trackable words, and every source cut so
  far has been a recording of somebody singing over a band. The worst of them
  failed outright: see the traps under "Add words to the bank" in
  [WORKFLOWS.md](WORKFLOWS.md), all of which come from separating a voice out
  of a mix rather than starting with one.

  AudiobookMaker already makes speech, on this machine, with no band under it.
  A voice generated rather than extracted has no bleed to gate away, no
  ambiguous pitch to cross-check, and no octave spread to normalise, so most
  of that procedure stops applying. What it costs is the thing the recorded
  banks are actually liked for: a real person's delivery.

  Worth a small experiment rather than a plan. One generated word set, cut
  into a bank, rendered next to `words_hq4` on the same song.

- **Done: the site has a name, and the edge is reachable from the tailnet.**
  Kept because the wrong answer was expensive and is easy to reach for again.

  Both were solved by four lines in the personal site's `vercel.json`, which
  already serves that domain from Vercel. `/songgenerator` redirects to the
  Static Web App, the same one-liner every other project there uses, and
  `/api/songgen/*` rewrites to the funnel, one entry per endpoint.

  The wrong answer was Cloudflare. The domain's DNS sits there, so a worker
  looked like the tool, but the record is DNS-only and traffic goes straight to
  Vercel: a worker never sees it. Making a subpath work would mean proxying the
  apex, putting Cloudflare in front of the whole personal site to serve one
  path. A worker was written, deployed, found inert, and deleted. The host that
  already answers for a domain is the place to route it.

  The rewrite is what makes the site usable by its own author. On a machine
  signed in to the tailnet, MagicDNS resolves the funnel name to the node's own
  `100.x` address, so a browser sees a public page reaching into a private
  network and refuses, while `curl` to the same address returns in 20 ms.
  Vercel's edge is not on the tailnet, so it resolves the public ingress like
  any other visitor and the browser never sees a `*.ts.net` name. The RAG chat
  on the same machine had been arranged that way for months.

  Measured, not assumed: a preflight through the proxy carrying the site's
  origin returns `Access-Control-Allow-Origin` for that origin and
  `Allow-Headers` including `Authorization`, so an authenticated call survives
  the hop. The origin stays the site's own, so `SONGGEN_ALLOWED_ORIGINS` did
  not change.

  Still open, and cosmetic: a subdomain would be tidier than a redirect, since
  the address bar shows the Azure hostname the moment the redirect fires. One
  CNAME from `songgenerator.mikkonumminen.dev` to the Static Web App, left
  unproxied so Azure issues its own certificate; two custom domains are free.
  It needs a token with DNS edit on that zone, and the one wrangler logs in
  with carries `zone:read` only.

- **Words hold together now. The break inside a shout pairing is the next
  gain, and it is a bank problem more than a code one.**

  The tearing is fixed. Shifts were folded one syllable at a time, so two
  syllables of a word either side of the 12-semitone cap were moved an octave
  apart however little the melody moved between them. `fold_unit` now makes one
  octave decision per word, and on ellinoora the words whose internal interval
  was enlarged by folding went from 32 of 156 to 5. A glide between syllables
  covers the rest. See `fold_unit` and `GLIDE_MS`.

  Four things remain, in the order they are worth doing:

  1. **Anchor the octave to a held shout.** A shout is dropped in as recorded,
     so it sounds at its own pitch while the word beside it can be shifted most
     of an octave away, and the unit breaks in the middle. Shifting the shout
     too is not the answer, that is what `SHOUT_KEEP_RAW` exists to prevent.
     Choosing the *word's* octave to sit beside the shout is. Measured over 304
     units mixing a raw shout with sung words, median internal spread 7.5 to
     6.9 semitones and units breaking more than half an octave 230 to 200.
     Where it applies the win is large, `perse+eee` goes from 10.6 to 3.0.

     A shout also leaves a gap in time, not only in pitch. It keeps the length
     it was recorded at, so it does not hold its vowel across a rest the way a
     sung syllable now does, and the word after it starts late. On rocketman
     those are the only two words left with silence inside them, 80 ms and
     30 ms, both after `eee`. Whatever is decided about the octave should
     decide this at the same time: both come from the same exemption.

  2. **Record a bare `paviaani`.** There is not one. All six takes in the
     curated bank are `eee-paviaani`, so every placement of the climax word
     carries the shout and its break. This removes the problem rather than
     reducing it, and no code change reaches as far.

  3. **The `paviaani` takes disagree.** `eee-paviaani_8` descends across its
     syllables where the other five ascend, so which take the arrangement picks
     changes the shape of the word. Worth deciding whether that is range or a
     take to set aside.

  4. **`GLIDE_MS` is a taste default.** 60 ms was chosen as roughly a fast
     singer's portamento and confirmed by ear, not by measurement. The
     surrounding constants in that block all carry numbers.

  Worth knowing before re-measuring any of this: most remaining `eee+paviaani`
  breaks are not octave artefacts. The word's own recorded melody spans about
  9.6 semitones around the held shout, which is real and no octave choice
  should flatten it.

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

- **Not every song that has been made records where it came from, and the
  video is the reason that matters.** Twenty-three songs are indexed. Two have
  their source written down. For the other twenty-one the only surviving trace
  of the original is a filename, and `music46.mp4` says nothing about what it
  is, who made it, or which link it came from.

  **The point is not provenance, it is the picture.** A rendered song is new
  audio over the original instrumental, and the obvious next thing to do with
  one is cut the original music video to fit it. That needs the video, at the
  best quality available, which means it needs the link. An index of sources is
  really an index of raw material for an edit that has not been made yet.

  Which changes what is missing, because some of it is already in hand:

  | Songs | Video | What is needed |
  |---|---|---|
  | 10 `.mp4` in `input/` | present, h264 | nothing, unless the resolution is too low |
  | 13 `.mp3` | none, cover art only | the link, or there is no picture at all |

  The ten that still carry video carry it at what was downloaded: three at
  854x480, two at 640x360, then 492x360, 360x360, two vertical at 406x720,
  and one at **426x238**. Usable for a joke, not for anything anyone would watch twice.
  Re-fetching at a decent resolution needs the link as much as the thirteen
  with no picture at all do.

  `paskaperse.wav` is not in that table and not in the index. It is not a song
  that was fetched from anywhere: it is the source the first word clips were
  cut out of, so there is no address to find for it. That is a different answer
  from one nobody has written down, and worth keeping distinct, because a gap
  invites somebody to go looking for something that was never there.

  The index is `input/SOURCES.md`, one row per song, keyed on the slug the tool
  derives from the input filename. That slug names the `work/` directory
  reliably. It does **not** always name the `output/` folder, because `-o`
  defaults to the raw input stem and several renders were given short names by
  hand, so `work/avantasia_-_carry_me_over_official_video` is `output/carry_me_over`.
  The slug is still the stable key; the output folder is not.

  It lives in `input/` rather than `docs/` because `docs/` is tracked, and a
  source list there would publish every link and every local path to anyone who
  clones the repo.

  **The files were asked and they do not know.** A downloader can stamp the
  source URL into what it writes. Checked with `ffprobe`: not one of these
  carries a URL. They do not all fail equally though. Every mp3 carries title,
  uploading channel, album and year, so one tagged `title=Mokoma - Takatalvi
  (Re-recorded 2018)` and `artist=MokomaOfficial` can be found again by
  searching for exactly that. The mp4s carry only container tags, `major_brand`
  and the encoder version, which identify nothing. For those the only source of
  truth is whoever downloaded them.

  **Eleven songs are not in the repo at all.** Ten were rendered straight out
  of a downloads folder and one, `seija_simola_-_juna_turkuun`, was analysed
  and never rendered. None was copied into `input/`, so that audio exists in
  one place and clearing the folder loses it. Copying them in costs nothing and is
  the thing to do first, because a link is no help once the file it names is
  gone.

  Every directory involved is gitignored, so a fresh clone has no songs and no
  way to find them. That is right, the repo is the tool and not the media, and
  it is exactly why the index has to carry the addresses.

  **The gap has stopped growing.** `python -m song_generator.fetch <url>`
  downloads a song into `input/`, keeps the video, writes the page address into
  the file itself as the `comment` tag, and appends the row, so anything
  fetched from now on records its own origin without anyone remembering to.
  What it does not fix is the backlog: those rows are a sitting-down-and-writing
  job for whoever has the links, and nothing can automate it.

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

- **A web front end, and the two pieces deliberately left out of its first
  cut.** The first cut takes one link for the song, lets you pick which bank
  sings it, runs the pipeline and plays the seven mimicry versions back. Two
  things it does not do, both cut on purpose rather than forgotten.

  **Building a bank from a second link.** The obvious next feature, and the one
  that cannot be automated the way it sounds. `AGENTS.md` is blunt about it:
  identification is done by ear, and speech recognition was tried three ways
  and was wrong nearly every time on shouted singing. The mine, listen, rename,
  build loop needs a person in the middle.

  The one automatable route is `build_bank --raw`, which discards identity and
  keeps only syllable count and pitch. That is a real feature and it is exactly
  how the spoken bank was built, but what it produces is a bank to be replayed
  in recorded order, not a vocabulary to be chosen from. A UI offering "paste a
  link, get a bank" has to say which of those it means, or it promises the one
  people expect and delivers the other.

  So the seam is there from the start: the front end asks the API which banks
  exist rather than naming them, because the names live in a gitignored local
  override anyway. Adding a bank later is a new row in that list, not a change
  to the form.

  **Snapshot mode.** A deployed link that works when the machine behind it is
  off, serving a few pre-rendered songs so the whole interface is browsable
  with generation calmly disabled. Cut for a simpler reason: there is nothing
  yet that is worth showing publicly.

  The seam for this one is a single interface over "where runs come from", with
  one implementation today and a second reading static assets later. Chosen
  before it is needed because retrofitting it means touching every component
  that ever called the API directly, and because it is also what makes
  "the backend is down" testable without a backend.

  Note when it does happen: seven versions of one song is a real number of
  megabytes shipped into a static build, so the question is how few songs and
  how few rungs can carry the demo, not how many will fit.

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
