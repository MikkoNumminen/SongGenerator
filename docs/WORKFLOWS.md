# Workflows

Recipes for the jobs that actually come up. Every command assumes the repo root
and the project's own venv.

---

## Make a track from a song

```powershell
.\.venv\Scripts\song-generator.exe input\song.mp4
```

Writes **two** mp3s to `output/`, one per playfulness level, both at full
mimicry: the words sing the melody as closely as the song allows.

```
output/song/<bank>/song.conservative.mp3
output/song/<bank>/song.wild.mp3
```

No rung in the name, because there is only one. The plain name belongs to the
take a plain run writes, and anything asked for specially says so in the
filename instead of landing on top of it: `--mimicry 0.6` writes `.mim0p60`,
`--no-shift` writes `.noshift`, `--mix 0.5` writes `.mix0p50`,
`--arrangement` writes `.replay`, and `--ladder` names every rung it renders.
Renders made before this was the default are still named `.mim1p00`.

`--ladder` cannot be combined with `--mimicry`, `--mix` or `--no-shift`. One
asks for every rung and the others name a single shift, so the command is
refused rather than one of them quietly winning.

Each song gets its own folder, one per bank inside it. The song name stays in
the filename too, so a file dragged out of its folder still says what it is.

`--ladder` renders the other six mimicry rungs as well, from 0.00 (words ignore
the tune entirely, clashing, and funny for it) upward. That is fourteen files
per song per bank, of which two get listened to, so it is opt-in.

Both levels every time, because which is funnier is a listening decision and a
run that produced one of them has not finished the job. Pick by ear; there is
no correct value for either dial, and the right one varies by song.

Every run draws a new arrangement, so running the same song three times gives
three different takes to choose between. Each is written to
`work/<song>/arrangements/` and the path is printed, which is how a take that
turned out well is brought back.

First run on a song pays for separation (~0.45x realtime). Every later run on
the same song reuses the cached stems.

Rendering both levels costs about 50 seconds of resynthesis on a 2.5 minute
song, since each arrangement is resynthesised separately. `--play conservative`
halves the time when only one level is wanted. `--ladder` costs almost nothing
on top, because the rungs are a selection over the same shifted set; what it
costs is the files.

**Useful flags**

| Flag | Effect |
|---|---|
| `--mimicry 0.45` | Both levels at that one setting, named `.mim0p45` |
| `--ladder` | Every mimicry rung, fourteen files instead of two |
| `--play wild` | One level instead of both |
| `--arrangement <path>` | Replay a saved arrangement exactly, or an edited one, named `.replay` |
| `--bank chaos` | Sing with every candidate clip, identity ignored |
| `--seed 42` | Fix the arrangement seed; otherwise a new one each run |
| `--raw-clips` | Ignore the standardised tier, sing the recordings as they are |
| `--no-shift` | Words at their own recorded pitch |
| `--swallow 2-4` | Fold 2-4 of the original's words into one bank syllable, for rap; see below |
| `--keep-original "0:24-0:30"` | Leave the original vocal in those stretches, for whistling and anything else that is not words; see below |
| `--rows 30` | Print more of the extracted note table |
| `--json` | Machine-readable summary |

---

## Sing a song with several voices taking turns

```powershell
.\.venv\Scripts\song-generator.exe input\song.mp4 --voices ppbank isoaiti
```

For a posse cut where several people sing: each turn is sung by the next bank
in the list, cycling, switching wherever the original singer changes. Not one
voice per singer. With more singers than voices, mapping singers to voices can
put two different singers next to each other in the same voice, and the
listener never hears the change; alternating at every turn is what makes the
switch audible regardless of how many people are actually on the track.

Needs the optional extra: `pip install -e .[voices]`. It installs
`speechbrain`, which measures who is singing when.

Output lands in `output/<song>/<bankA+bankB>/`, named by every voice joined
with `+`, so a turn-taking render never lands in one of its own banks' folders
and overwrites that bank's plain take. Still two files, conservative and wild,
both at full mimicry.

The first `--voices` render of a rap posse cut ("SMC Hoodrats") came back with
too many words far too fast: a bank syllable on every rapped syllable is a
machine gun of words at rap tempo. `--swallow`, below the render section for
rap material, is what turned that into something melodic.

Refused rather than attempted: fewer than two distinct banks (use `--bank` for
one), a bank named twice (turns go round the list, so a repeat puts one voice
on two turns in a row where the list wraps), `--bank` beside `--voices`,
`--words-dir` (`--voices` names banks from the bank table), and
`--arrangement` (a `--voices` run writes one log per voice and there is no
replay of a multi-voice run yet). Banks whose `bank.json` declare different
`word_bus_lufs` are refused too, since the voices share one word bus.

Required words are judged on what the take will actually sing. Each voice is
arranged over the whole song and then loses every placement outside its turns,
so coverage judged over the whole song was met at the first draw while the
words that met it went to the other voice. `arrange.build` takes `sings`, the
placements its voice is heard in, and its own redraws and its relaxing of
preferences work on those. The voices are planned longest-singing first: the
first is asked for every required word, and each after it (`wanted`,
`pairing`) only for what the voices before it have not said. Asking every
voice for every word in its own turns made a voice with one short turn spend
every draw and relax every preference. A first version redrew the whole set
from outside instead, which cost up to 288 planner runs a level and never let
the relaxation see the coverage that mattered. The run prints its own seed,
and `--seed` with it brings the whole take back.

At a handover the voices were planned apart, so the incoming voice's first
words could start while the outgoing voice's last word was still sounding, for
a second or more when the two swallow at different paces. Those incoming words
are dropped whole until the outgoing word has finished; nothing is cut.

When fewer turns are found than there are voices (one singer, or one cluster
for several), the voices past the last turn own nothing. They are not planned
at all, and the run says which of them sings nothing, instead of spending
every coverage redraw on a voice nobody hears.

**Known limits, left as they are.** Each was found in review and judged not
worth its cost yet:

- `--voices` and `--swallow` take several values, so they swallow the song's
  path when written before it. Put the song first:
  `song-generator.exe input\song.mp4 --voices a b`.
- Coverage is judged on the placements whose onset is in a voice's turn, so a
  required word placed in the first moment of a turn and then dropped at the
  handover still counts as said; the report's line of words never said is
  the check.
- Arrangement logs are named by seed and level only, so a swallowed and an
  unswallowed run at the same `--seed` write the same `.arr`.
- The run report adds both banks' units together, so two banks holding a clip
  of the same label print it as one.
- A reciting bank (`sequence` or `shuffled`) is recited over the whole song
  and then cut to its turns, so in its second turn it picks up the text where
  it would have been had it read through the other voice's turn. Reciting
  only on the voice's own turn slots would fix it.

**How turns are found.** The vocal stem is cut into overlapping windows and
each becomes a speaker embedding; windows cluster by voice, and a run of
windows shorter than `TURN_MIN_S` is folded into its neighbours rather than
treated as its own singer. The result is cached as `work/<song>/turns.json`
together with the settings that produced it, and reused while a run's settings
still match. See `docs/DATA-FORMATS.md` for the file.

**Tuning `TURN_DISTANCE`.** This is the knob to reach for first, in
`config.py`'s `STAGE 4b` block. It is the cosine distance at which two voices
stop being merged into one cluster. Measured on a 5:43 rap posse cut (521
voiced windows):

| `TURN_DISTANCE` | Result |
|---|---|
| 0.6 | five turns, matching the track by ear: 40-91, 91-132, 132-234, 234-285, 285-306 s |
| 0.55 | the same five turns, with more short blips absorbed |
| 0.5 | 27 clusters: single verses split into pieces |
| 0.4 | 74 clusters, about one per line |

Raise it when two different singers come out as one turn; lower it when one
singer's turn keeps splitting. `TURN_MIN_S` (4.0 s as shipped) is the second
knob: it decides how short a stretch has to be before it is folded into its
neighbours rather than counted as a singer of its own.

**Correcting a boundary by hand.** Turns are cached, so a boundary that is a
few hundred milliseconds off can be fixed once rather than re-detected every
run: open `work/<song>/turns.json`, move a `start_s` or `end_s`, and rerun with
the same `--voices` and the same config. The file is read back as long as its
`settings` block still matches what the current config would measure with;
editing a turn's own times does not touch `settings`, so the edit sticks.
Delete the file, or change one of the `STAGE 4b` constants, to force a fresh
measurement.

### Make a voice-converted copy of a bank

For turning an existing bank into a second voice that says the same words with
the same takes and the same sung delivery, only in a different timbre. Voice
conversion keeps the delivery; text-to-speech would not, which is why it is
the first thing to try. It worked by ear for a male voice, Keskisarja, on this
material. It did not for a female one, Isoäiti, even though nothing about the
recipe below measured as wrong; see "When it does not sound like the voice"
below before assuming a converted bank is fine because the numbers are.

1. Start from the bank's **source** clips, the hand-named recordings a bank
   was built from (for `ppbank`, that is `words_hq`), not the built bank
   itself: `build_bank` parses word identity out of the source filenames, so
   converting the source and re-running `build_bank` on the result keeps every
   name.
2. Convert each source clip toward a reference recording of the target voice
   with `ChatterboxVC` (from the `chatterbox` project, run in a venv that has
   it installed):

   ```python
   from chatterbox.vc import ChatterboxVC

   model = ChatterboxVC.from_pretrained(device="cuda")
   wav = model.generate(audio=source_clip_path, target_voice_path=reference_wav)
   # resample wav from the model's 24 kHz to the source clip's own rate
   # before writing it under the source clip's own filename
   ```

   Write the converted audio into a sibling `words_<voice>_src/candidates/`
   directory, one file per source clip, same filenames. The model's output
   pitch does not need to match the source: `build_bank` measures pitch from
   the audio it is given, and the renderer re-pitches every clip to its slot
   regardless.
3. Build the bank from the converted candidates:

   ```powershell
   python -m song_generator.build_bank --candidates words_<voice>_src/candidates --out words_<voice>
   ```

Durations should come back within tens of milliseconds of the source clips;
much more than that means the conversion changed the pacing and the syllable
boundaries `build_bank` measures will be off. Register the new bank in
`vocabulary_local.py` (bank names are local, kept out of this repository) or
point `--words-dir` at it directly.

**When it does not sound like the voice.** The Isoäiti bank, converted by the
recipe above, measured fine and did not sound like her at all. Checked and
ruled out, in order:

- **The reference file.** `assets/voices/grandmom_reference.wav` and
  AudiobookMaker's own Finnish path (`samples/reference_finnish.wav`, cloned
  from the `Finnish-NLP/Chatterbox-Finnish` HF cache) measure 0.81 cosine
  similarity apart, so they are the same voice; the reference was not the
  cause. Redoing the conversion against `reference_finnish.wav` still only
  reached 0.40 similarity to her own reference, against 0.45 for Keskisarja's
  voice-converted clips.
- **Pitch.** Her reference speaks at MIDI 52.8 (E3); the converted clips
  measured 53.3, close to it and nowhere near the song's own median of 49.7
  (D3).

Text-to-speech through AudiobookMaker's own Finnish path came closer than
voice conversion of the sung source, and it took two tries to get clean
words out of it. It still did not give her voice: the owner heard the third
Isoäiti bank, the one made as described below, as wrong too. See the open
item in [TODO.md](TODO.md).

**The dead end.** Speaking several phrases as sentences in one 60-200
character chunk, then cutting each word back out at the longest measured
silence, failed on all 8 chunks after 6 rolls each. Her sentence pauses are
not longer than her comma pauses, so the cuts landed in the wrong places, and
faster-whisper hallucinated a trailing "Kiitos." onto the silence after the
last piece. Abandoned rather than tuned further.

**Clean words, not yet her voice.** AudiobookMaker already has the tool for this,
`scripts/build_word_bank.py`, but only in its git history: commit `3658909`
("say the word in a sentence, then cut it back out") on branch
`feat/word-bank-generator`, not on its current checkout. It says each word
inside a carrier sentence written for the expression asked for (`"Paska!
Kuuletko sinä minua?"`, `"Paska? Oliko se todella niin?"`), locates the word
by faster-whisper's own word timestamps, snaps each end to the quietest point
nearby, trims it out, and verifies the cut by its own transcript; a word with
no surviving carrier take falls back to rendering it alone and verifies that
instead. Deliberately skips AudiobookMaker's audiobook post-processing (7 kHz
low-pass, -20 dBFS), because a sample that is going to be transposed should
not be muffled going in.

1. Take the script out of history into a scratch directory:
   `git show 3658909:scripts/build_word_bank.py`.
2. Point its own repo-root path at the AudiobookMaker checkout (it imports
   `_load_engine` from there), and run it with AudiobookMaker's
   `.venv-chatterbox` python:

   ```
   python build_word_bank.py --words paska,perse,pillu,pornolehti,paviaani \
       --language fi \
       --presets scream,shout,urgent,excited,command,bright,narrate,asking \
       --whisper-device cuda --out words_isoaiti_src --no-contact-sheet
   ```

   It calls `ensure_alignment_empty_guard`, which patches a source file in
   the `chatterbox` checkout it runs against
   (`models/t3/inference/alignment_stream_analyzer.py`); check whether the
   patch is already applied there before running, since this writes into
   another repo.
3. Result: 40 of 40 kept (5 words times 8 presets), three of them via the
   word-alone fallback (`pornolehti_excited`, `pornolehti_asking`,
   `paviaani_command`). Clips land at
   `words_isoaiti_src/fi/roots/<word>_<preset>.wav`.
4. `build_bank --candidates words_isoaiti_src/fi/roots --out words_isoaiti`.

Isoäiti says only real words this way: no "eee" shout and no "au", which the
Finnish model cannot say. Those stay with whichever voice already has them; a
word one voice of `--voices` lacks is not reported as missing from the song
as long as another voice can say it.

Speaker-embedding similarity to her reference does not rank these routes
the way the ear did: 0.40 for the voice conversion, 0.53 for the
phrase-by-phrase text-to-speech clips that failed by ear, 0.48 for the
carrier-sentence clips that replaced them. An embedding score is not a
pass/fail test for a converted or synthesised voice; listen before building
the bank.

**Never ask the Finnish model for a fragment under 60 characters.**
AudiobookMaker's own minimum-fragment guard, 60 characters
(`scripts/generate_chatterbox_audiobook.py`), exists because the model
rambles or repeats on a shorter fragment, and it is only enforced upstream of
the audiobook path. Asking it directly for a bare phrase like `"Paska!"` (3
to 25 characters) skips that guard: one earlier attempt at this bank did
exactly that, and Whisper large-v3, run as a hint on the clips afterwards,
shows what came back: `paska_2.wav` said "Aukumaala", `perse-eee_2` said
"Perse. Ei, ei, ei." (the shout written "Eeeeee!" comes back as "ei, ei,
ei"), `au_1` said "Vähä", and `perse-pillu_1` said "Ainet. Pillu" against
`pillu_2`'s "Joo, pillu". The carrier-sentence route above never hits this,
because every utterance sent to the model is a full sentence.

**A bank of generated or converted speech needs `never_split` before its
first render, not after.** Without it, `arrange.build` cuts the speech into
syllables and each is re-pitched and time-stretched to its own slot like a
sung recording, and generated or converted speech survives that far worse
than a real singer's take: a first Isoäiti render (built with no
`bank.json`, so no `never_split` declared) came back sounding like a computer
voice, fit at 0.59x natural speed, about 1.7x slower than she actually spoke.
See "Tune a bank of generated voices" below, which already says this; the
bank was built without reading it. `words_isoaiti/bank.json` now declares
`{"never_split": true}`, which is what makes `arrange.build` set
`target_s = play_s`: the clip sounds at its own length or faster and is never
slowed, a long swallowed slot leaves a pause after the word instead of
stretching it, and her own intonation carries through, shifted by one
constant.

---

## Keep whistling, or anything else that is not words: `--keep-original`

The separator sends whatever sounds like a voice into the vocal stem, and
whistling sounds like one. On "Kielinuppu - Suomalainen metsä" the whistling
came out in the vocal stem, the analysis found notes in it, and the render sang
swear words over it. The owner's verdict: the whistling is part of the song and
has to stay.

```powershell
.\.venv\Scripts\song-generator.exe input\song.mp4 --keep-original "0:24-0:30,1:03-1:09"
```

Inside every range no slot gets a word (a slot that touches the range at all is
dropped, since a word begun before it would ring on into it), and the original
vocal stem goes back onto the bed with a `KEEP_ORIGINAL_FADE_S` fade inside
each edge. It is added before the bed is levelled, so it sits against the band
as it did in the original. The files are tagged `.keep`; a second attempt at
the ranges replaces the first, which is kept in `previous/`.

**The ranges are given by hand, on purpose.** A detector was tried: whistling
is close to a pure tone, so frames with at least 60% of their 150 Hz to 8 kHz
energy within two bins of one peak above 500 Hz, and nothing 4 dB near it an
octave below, were marked. On this song it found steady tones near 785 Hz, but
a child's voice held on one note is nearly as pure, and across 40 other cached
songs it fired on long sung notes: 88 seconds of Avantasia's "Ghostlights", 40
of "Kalasatamaan", 34 of "Through the Fire and Flames". Run by default it would
put real singing back into renders across the library. Listen to the song, or
to its `work/<song>/vocal.wav`, and write down where the whistling is.

---

## Slow rap down before singing it: `--swallow`

```powershell
.\.venv\Scripts\song-generator.exe input\song.mp4 --swallow 2.6
.\.venv\Scripts\song-generator.exe input\song.mp4 --voices keskisarja isoaiti --swallow 2.6 keskisarja=2.05
```

For rap and anything else where the melody gives close to one note per sung
syllable. A bank syllable placed on every one of them is a machine gun of
words at rap tempo, far more than the genre can carry as singing. `--swallow`
folds several of the original's words into one bank syllable before the words
are planned, so that syllable sounds for as long as the words it swallowed and
is pronounced along with them, which is what reads as melodic rather than
rushed. Off by default: this is for material dense enough to need it.

`--swallow` is asked in *words* of the original song, because that is how a
pace is naturally described. `2.6` swallows that many words per bank
syllable; `2-4` is accepted too, but only its mean is used as the pace, so
`2-4` and `3` render the same. Several values may be given at once: one
unnamed value for every voice singing, plus a named value, `keskisarja=2.05`,
for any voice of `--voices` that should move at its own pace; the voice's own
value wins over the general one. Refused rather than resolved: two unnamed
values, the same voice named twice, and a voice not singing in this run.
The filename lists the values in a fixed order (everybody's first, then each
voice's own by name), so the same request always writes the same file.

A swallowed take's `.arr` log records the grid in a `swallow` header line, and
`--arrangement` rebuilds that grid from it, so the take comes back without
`--swallow` being typed again. An explicit `--swallow` that disagrees with the
log is refused: replayed on the unswallowed notes, every line would land at
more than twice the pace it was planned for.

A swallowed run needs its bank plans laid over fewer, wider slots, so it also
places fewer, longer units. Filenames carry the setting,
`smc_hoodrats.conservative.swallow2p6.mp3`, a named voice's own pace appended
after it (`swallow2p6-keskisarja2p05`), combined with any other tag by
`join_tags` (`mim0p60.swallow2p6`), so a swallowed take never lands on top of
a plain one.

**Words to notes.** The analysis measures notes, roughly one per sung
syllable, but `--swallow` is asked in words. The word count is converted to
notes per bank syllable as `words * RAP_WORD_SYLLABLES / (bank's mean
syllables per word)`, floored at one note, since a bank syllable cannot sound
on part of one. `RAP_WORD_SYLLABLES` (2.5 in `config.py`) is an estimate for
Finnish rap, not a measurement. The run report prints the notes-per-syllable
figure each voice actually used, so it can be checked against the ear rather
than the word count typed on the command line.

**What is actually folded.** `swallow_slots` in `mapping.py` keeps the mean
exactly, because the mean is the pace: a phrase of N notes becomes
`round(N / per_syllable)` slots, split as evenly as the notes allow. Each
boundary can then move up to `SWALLOW_SNAP_NOTES` (1) note toward the widest
gap within reach, the nearest thing to a word boundary a run of sung
syllables offers. A group never crosses a phrase. The group's slot takes its
onset from the first note, its offset from the last, and its pitch from the
longest note in it, the one the rapper actually leant on. Each voice of
`--voices` gets its own slots, folded at its own pace.

Keeping the mean exactly is what makes a percentage change possible to ask
for at all. An earlier version of `swallow_slots` chose each group's size by
widest gap within a whole-number range and did not hold the mean: asked for
`2-4` (meant as 3.54 notes per bank syllable, against Keskisarja's bank),
it actually delivered 3.09 (998 notes folded to 323 slots), so there was no
number to move by a known percentage.

**Measured on "SMC Hoodrats", Keskisarja's bank (2.12 syllables per word),
988 notes after cleanup:**

| `--swallow` | slots |
|---|---|
| 2.0 | 422 |
| 2.1 | 396 |
| 2.2 | 383 |
| 2.6 | 323 |
| 3.0 | 282 |

323 slots is the pace that had already been heard and judged too slow; the
owner asked for 25% faster, i.e. not swallowing that many words. `2.05`
gives about 409 slots, roughly +26% against 323. Note melody extraction
re-runs on every render and gave 1004, 998 and 988 notes across three runs of
the same song, so a slot count moves by about 1% between otherwise identical
runs; treat a count near a table value as a match rather than expecting it
exactly.

**Replaying an arrangement.** A saved arrangement is laid over the slots it
was drawn against, so replaying it with `--arrangement` needs the same
`--swallow` value the render was made with. A different value folds the
slots differently and the arrangement no longer lines up with them.

---

## Fetch a song from the web

```powershell
.\.venv\Scripts\python.exe -m song_generator.fetch "https://example.com/watch?v=abc123"
```

Lands in `input\<slug>.mp4`, best video plus audio merged, named by the same
slug the renderer would derive, so the filename on disk is already the key the
whole tool uses. Then render it as usual; the renderer never takes a URL
itself, because the network stays out of the render path on purpose. A render
must not be able to fail because a site changed.

The video is kept at the best resolution the site holds, not just the audio,
because the plan for a rendered song is to cut the original music video to fit
it. Several early songs were downloaded as convenience files at 426x238 and
cannot be cut into anything.

The origin is recorded twice: embedded in the file itself as the `comment`
tag, where `ffprobe` recovers it as long as you know which tag to read, and
as a row in `input\SOURCES.md`, the
gitignored index of where every song came from. See `docs/DATA-FORMATS.md`
for its shape. Songs that arrived before this command exist have no recorded
address; fetching does not fix history, it stops the gap growing.

A file that is already there is reported and left alone: no overwrite, no
`(1)` duplicate. Delete it first to fetch it again. The exception is when
`input\SOURCES.md` already records a different address for that name, which
means two titles slugified to the same slug; the fetch then warns on stderr,
records nothing and exits nonzero, because deleting the file would lose the
song the index describes. `--json` prints the same
fields the `fetch()` function returns, and `--out` redirects everything,
index included, somewhere other than `input\`.

---

## Make many tracks at once

```powershell
.\.venv\Scripts\python.exe -m song_generator.batch "input\*.mp4"
.\.venv\Scripts\python.exe -m song_generator.batch "input\*.mp4" --mimicry 0.45
```

One song failing does not end the batch. A song with no vocal is refused as
Mode B, recorded, and the rest continue. The exit code still tells the truth:
non-zero when any song failed, so a script or CI step sees a partial batch
rather than a clean one. Mode B refusals alone do not fail a batch, since a
song with no vocal was handled exactly as designed. The one exception is a
batch where nothing rendered at all, which exits non-zero whatever the reason:
a run that produced no audio is not a success worth reporting. A hung ffmpeg
cannot stall the run either; every call is bounded by `FFMPEG_TIMEOUT_S` in
`config.py`.

Each song writes both playfulness levels, so twenty songs is 280 files.
`--play conservative` narrows it to one level when that is more listening than
you want.

### Running it in parallel, without taking the machine down

`batch` renders one song at a time. Running several at once is tempting and is
how a workstation gets wedged, so the numbers are written down here rather than
rediscovered.

A render is **single-threaded and holds about 3.5 GB**. Measured: 99% of one
core, which on a 24-core machine reads as 4% in Task Manager and looks like
nothing is happening. It is.

The ceiling is memory, not cores. Eight at once against 19 GB free exhausted
RAM, and the swapping pinned the disk at 100% until the machine had to be
restarted. Divide the free memory by 4 GB and use that, and remember anything
else on the box counts: a local model server can hold 15 GB of RAM and 8 GB of
VRAM on its own, which leaves room for exactly one render.

Five things that each cost an hour to learn:

- **Killing the launcher does not kill the pool.** `xargs -P` keeps refilling
  after its parent shell dies, so a second run silently doubles the
  concurrency. Write the `xargs` pid to a lock file, refuse to start when it is
  live, and kill *that* pid to stop.
- **`--device cpu` does not spare the GPU, it wrecks the run.** Melody
  extraction is torchcrepe, and on this material one song went from 167 seconds
  to over nine minutes without the card. Every render needs the GPU, not just
  the first: `analysis.json` is written each run and never read back.
- **`CUDA_VISIBLE_DEVICES=""` does not hide the card.** Torch still reports
  cuda available and builds a context, so ten workers filled 11.7 GB doing no
  GPU work at all. `-1` genuinely hides it. To leave room for other GPU work
  instead, use `GPU_MEMORY_FRACTION`, and do not set it below what separation
  measurably needs: at 0.15 roformer died with "1.80 GiB allowed" while 6.25 GiB
  of the card was free.
- **`--separator` on a song that already has stems does nothing, and says it
  did.** The cache is `work/<song>/vocal.wav` plus its instrumental, and the
  check is only that both files exist; nothing records which backend wrote
  them. So asking for a different separator reuses whatever is there while the
  header still prints the backend you asked for. `--force` is what actually
  re-separates.
- **Redirect stdout and Python buffers it.** A run that has printed only its
  header looks hung and is not. Use `python -u`, or you will kill working jobs.
  For the same reason, grep batch logs with `-a`: one `ä` in a song title makes
  GNU grep call the file binary and print nothing.

---

## Bring back a take that worked

Every arrangement is logged, so nothing good is lost to a re-roll.

```powershell
.\.venv\Scripts\song-generator.exe input\song.mp4 `
    --arrangement work\song\arrangements\543686-wild.arr
```

The file is readable and editable. Change the words on a line, delete a line,
or delete the `[take]` to let the tool choose the recording. A word the bank
cannot say is refused by name rather than quietly dropped. See
`docs/DATA-FORMATS.md`.

### Undo the last render

Replaying an arrangement re-renders it, which takes a GPU and several minutes.
When the previous take is still on disk, there is a faster way back: a render
moves the file it is about to overwrite into a `previous` folder beside it, and
`--rollback` puts it back.

```powershell
.\.venv\Scripts\song-generator.exe input\song.mp4 --bank ppbank --rollback
```

It restores every level for that song and bank at once, because a run writes
conservative and wild together and a pair from two different runs is
indistinguishable by looking at it. It reads no stems and loads no bank, so it
returns immediately.

The two takes are swapped rather than moved, so running it again returns to
where it started. That is deliberate: comparing two takes by ear means going
back and forth, and neither one is ever the one that gets thrown away.

Only one generation is kept, per song, per bank, per level. A second re-render
replaces the backup, so this undoes the last render and not the one before it.

---

## One word is too common, or too rare

Each kind of word has a share of the song it should have, weighted per level in
the `PLAYFULNESS` block of `config.py`. See `docs/GLOSSARY.md` for what the
roles mean.

| Symptom | Knob |
|---|---|
| The song is mostly shouting | `shout_cost` up, or `shout_share` down |
| The words that carry it are drowned out | `core_bonus` up |
| A long word turns up too often | `crown_cost` up |
| Words the song is not about keep appearing | `extra_cost` up |
| The payoff is everywhere / never | `climax_share`, `climax_wildcard` |
| It says the same thing too often | `repeat_penalty` up, `chant_chance` down |
| It never repeats anything, which is half the joke | `chant_chance` up |
| Words sound stitched together | `spelled_cost` and `joined_cost` up |

Measure rather than guess. The run's report prints what was used, and the
share of each role is worth counting across several seeds before deciding a
knob is wrong, since one arrangement is one draw.

Coverage outranks all of them: a required word missing is a broken rule, so
these weights are relaxed and then dropped rather than let that happen. Turning
a knob to 0 will not remove a required word from a song.

---

## Make a bank behave differently

How a bank should be placed is a property of its recordings, so it is
declared beside them: a `bank.json` in the bank directory, read from
whichever directory is actually being sung from. `docs/DATA-FORMATS.md`
documents the format.

```jsonc
{
  "levels": {
    "conservative": {"strategy": "sequence"},
    "wild": {"strategy": "arranged",
             "overrides": {"chant_chance": 0.55, "chant_max": 6}}
  }
}
```

Per level, pick a strategy. `arranged` is the planner every bank gets by
default. `sequence` replays the clips in the order they were recorded,
looping, with no randomness at all, built for a bank whose words were spoken
in an order that carries the meaning. `overrides` lean the level's
parameters from the `PLAYFULNESS` block of `config.py` without redefining
them; any knob a level sets may appear.

Name the bank in the `BANKS` table of `vocabulary_local.py`, or point
`--words-dir` at the directory; the settings are read either way. Renders
land in `output/<song>/<bank>/`, so the same song sung from two banks never
overwrites itself.

A bank with no `bank.json` behaves exactly as every bank always has, and
`tests/test_determinism.py` holds the existing bank to its exact placements
for a fixed seed. If that suite goes red, the change moved a bank that
declared nothing, which is the one thing this mechanism must never do.

---

## Check the bank is the one being sung from

```powershell
.\.venv\Scripts\python.exe -m song_generator.doctor
```

The environment section names, per bank, the directory a run would actually
sing from and whether its standardised tier still matches the recordings. A
stale tier is the quiet failure: the song is sung from clips that no longer
reflect what is on disk, and an ordinary run says nothing about it.

---

## Tune a bank of generated voices

Everything below was settled by tuning `asuntoautoBank` over one long session,
mostly by getting it wrong first. Walk it in order. Each step's decision
depends on a measurement, and the measurement is cheap.

`doctor --bank <name>` prints the first three.

**1. Measure the voice before deciding anything.**

| measurement | what it decides |
|---|---|
| **voiced fraction** | how much of the clip WORLD can rebuild at all |
| **register**, median MIDI | whether the melody is reachable, and by how much |
| **edge safety**, source level either side of every cut | whether the clips are usable at all |

A generated voice is mostly breath, and that is the single fact governing
everything else: an unvoiced frame carries no f0, so the vocoder cannot
transpose it, and the lower the voice the worse it gets. `render_segments`
restores those frames from the source, which is what makes such a bank usable
at all.

Two figures, and they are not the same measurement. **Per clip**, the phrases
in these banks run 57 to 86 per cent unvoiced, and the spread between the
voices is what matters: the lowest one is the highest number and it tears
first. `doctor` reports a **bank-wide mean over sampled clips**, one number,
which for `asuntoautoBank` is 42 per cent voiced. Read the doctor line for
whether a bank is breathy at all, and measure per clip when deciding which
voice is the problem.

**2. Cut only where the recording is already silent.**

Find every silence of 80 ms or more and cut at the **middle** of each one. Both
sides of every cut are then quiet by construction rather than by a threshold
somebody chose, and a threshold somebody chose is how three rounds of checking
confirmed the same broken cuts. See the ending runbook below for that story.

Do not try to separate words that run together. If a chorus says two words with
no gap, there is no clean cut between them and no setting recovers one: the
short clip can only be cut mid-word. Take the whole phrase and let the planner
use it whole. Four of five attempts to split one word out of this recording had
to be abandoned for exactly this.

**3. Choose the strategy from what the material can survive.**

| you want | declare | cost |
|---|---|---|
| words whole, in the recorded order | `sequence` | deterministic, so both levels render the same file |
| words whole, varied | `shuffled` + `never_split` | order only; nothing follows the tune's rhythm |
| the tune's rhythm followed | `arranged` | clips are stretched to their notes, and past about 0.6 a word stops sounding like the word |

`never_split` is not optional for spoken or generated material. Half a spoken
word is a different sound, not a shorter one.

**4. Set the level against the band, and measure rather than copy.**

A speaking voice needs more than a sung one to be heard, but a hot word bus
trips the ceiling in `mapping.mix` and drags the whole mix down: at -11.0 LUFS
this bank's renders came back quieter overall than at -14.0. `asuntoautoBank`
settled at **-13.0**. Copying another bank's number without measuring is a
documented way to make every render sound wrong.

**5. Decide the register by folding, not by pre-shifting.**

Compare the bank's median MIDI with the song's. Folding already moves a clip by
whole octaves for free, at render time, in one pass. Baking an octave into the
clips costs a second generation of processing, and if you bake it with WORLD on
a breathy voice you get a bank that is already torn before any song touches it.
That was tried here and thrown away.

**6. Leave the engine alone.**

WORLD, not Rubber Band. Rubber Band needs no f0 so it never tears, which makes
it look like the fix for a breathy voice, and it is not: measured as
mel-spectral distance from the source at a five semitone shift, it does about
twice the damage, worst on the lowest voice.

| clip | unvoiced | WORLD | Rubber Band | WORLD + restore |
|---|---|---|---|---|
| female phrase | 57% | 3.1 | 3.6 | **2.3** |
| male phrase | 72% | 1.8 | 3.3 | **1.0** |

**7. Where `asuntoautoBank` landed**, as a worked example:

```jsonc
{
  "levels": {
    "conservative": {"strategy": "sequence", "overrides": {"reading_speed": 1.0}},
    "wild":         {"strategy": "shuffled", "overrides": {"reading_speed": 1.0}}
  },
  "never_split": true,                 // spoken words are never cut
  "mix": {"word_bus_lufs": -13.0},     // measured, not copied
  "shift_cap_semitones": 12.0          // lower it only if the voice tears
}
```

Three voices, cut at measured silences, every clip whole, nothing stretched.

**What listening is still for.** None of this can be judged from the numbers.
Every fault found here was found by ear first and explained afterwards: which
words broke, that a second voice broke identically, that the lower voice broke
sooner. The measurements tell you which explanation is true, not that something
is wrong. Hand over the candidate folder and listen before building.

---

## A word breaks, scratches or loses its ending

The most expensive fault this tool has had, and it was misdiagnosed four times
because every explanation sounded right. Walk these in order. Each step rules
out a whole class, and the render report names most of the numbers.

**1. Is it placement?** Read `truncated` and `time fit` in the report.

- `truncated` above zero with an `arranged` bank: the planner is cutting clips
  to fit their slots. That counter also fires on any reading speed above 1.0,
  where nothing is cut, so check `time fit` before believing it.
- `time fit` far from 1.00: the clip is being stretched or squeezed. Below
  about 0.6 a word stops sounding like the word. `sequence` never stretches;
  `arranged` fits every clip to its note.

**2. Is it the cut?** Test **against the source, on both sides of every cut**,
never inside the clip:

```powershell
# For each cut, measure the source in the 50ms before the start and after the
# end. Both must sit near the noise floor. A loud reading means the cut landed
# mid-word, whatever the clip looks like on its own.
```

Do not judge a start by comparing a clip's first frames to its own body: a
correct clip *begins* on a word, so that test flags every good clip and clears
none. That mistake threw away five good clips here.

Do not pick the silence threshold to suit the answer. A gate at floor+12 dB
called a decaying vowel silence, the check then agreed with the cuts three
times running, and the endings were chopped the whole time. Cut at the
**middle of a measured silence** and both sides are quiet by construction.

**3. Is it the shift?** Check `after folding` and `octave-folded`. Lowering
`shift_cap_semitones` for the bank will make a shift-caused fault quieter. Be
careful: that also makes an *unrelated* fault quieter, because a smaller shift
mangles any discontinuity less. Improvement here is a hint, not a diagnosis.

**4. Is it the voice?** Measure the **voiced fraction**. Anything much under
half means most of the clip carries no f0, and WORLD rebuilds those frames
from aperiodicity alone. The generated voices used here run 57 to 86 per cent
unvoiced, which is why their endings tore while the middles were fine, and why
the lower voice failed first: it has the most breath and the furthest to move.

That last one is handled in `pitchshift.render_segments`, which puts the
original samples back wherever the source had no pitch. Shifting unvoiced
sound changes nothing anybody can hear, so there is nothing to lose by it.
It applies only where the render is not stretching, since a re-timed clip has
no aligned original to restore.

**What not to do.** Switching engines is the wrong first move. Rubber Band
needs no f0 and so never tears, which makes it look like the fix, but it does
roughly twice the spectral damage to a low breathy voice. Measured on these
banks, mel-spectral distance from the source at a five semitone shift:

| clip | unvoiced | WORLD | Rubber Band | WORLD + restore |
|---|---|---|---|---|
| female phrase | 57% | 3.1 | 3.6 | **2.3** |
| male phrase | 72% | 1.8 | 3.3 | **1.0** |

## Work out why something sounds wrong

```powershell
.\.venv\Scripts\python.exe -m song_generator.doctor
.\.venv\Scripts\python.exe -m song_generator.doctor --song input\musicHyva.mp4
```

Prints, in one go: whether the environment is sound, what the bank contains,
what pitches it covers, how a song's notes became slots, how many phrases are
long enough to hold a climax, and how far this bank would have to shift to
follow this melody.

Reach for it before changing any constant. Most "it sounds wrong" questions are
answered by the pitch-coverage histogram or the phrase-size line.

---

## Add words to the bank

Only a person can say what a clip contains, so this loop is built around
listening. It is the one part that cannot be automated.

```powershell
# 1. Cut candidates out of one or many sources
.\.venv\Scripts\python.exe -m song_generator.mine_words "sources\*.mp4"

# 2. Collapse into one flat folder, tagging what has not been reviewed
.\.venv\Scripts\python.exe -m song_generator.flatten

# 3. LISTEN. Delete junk. Rename keepers after what you hear.
#       TODO_2syl__kirby__c07__1.42-1.98.wav   ->   bravo7.wav

# 4. Build
.\.venv\Scripts\python.exe -m song_generator.build_bank
```

`mine_words` and `precheck` report like `batch` does. One bad source does not
stop the rest, and the exit code is non-zero when a source failed to mine, so a
partial run cannot pass for a complete one.

Two limits worth knowing rather than discovering. A failed `--asr` pass does
**not** make `mine_words` exit non-zero: recognition is a labelling hint that
gets checked by ear regardless, so a source whose clips were cut correctly has
not failed because the recogniser fell over. It is counted and reported, and
the clips are there to name by hand. In `precheck`, a failed transcription
batch is survived and reported, but a wav that cannot be rendered at all still
ends the run, because that happens before the part with the handler around it.

**Naming.** A variant label may begin with something the bank knows: `_low`
starts with the syllable `lo`, and the name is still read as one word plus a
label. All of these parse: `bravo`, `bravo1`, `bravo_2`, `bravo_low`,
`BRAVO3`. Multi-word clips keep the singer's own transitions and are worth more
than their parts, name them as sequences: `tangodelta`, `aahcalculator`. A shout
can be spelled however it sounded: `aah`, `aaah`, `ahh`, `aaahh`.

**Removing the prefix is what confirms a clip.** Anything still tagged is
ignored by the bank, so leaving a clip alone is always safe.

### Judging a source before cutting it

One measurement predicts whether a source can make a bank at all, and taking
it first would have saved an evening. Separate the source, then compare the
vocal against the instrumental **over the moments the vocal is actually
sounding**:

| source | voice against the band under it |
|---|---|
| `pilluvittu*`, which built `words_hq4` | **+1.5 dB** |
| a buried vocal that produced nothing usable | **−3.1 dB** |

```powershell
.\.venv\Scripts\python.exe -c @"
import pathlib, numpy as np, soundfile as sf
d = pathlib.Path('work/<slug>')
v = sf.read(d/'vocal.wav', dtype='float32', always_2d=True)[0].mean(axis=1)
i = sf.read(d/'instrumental.wav', dtype='float32', always_2d=True)[0].mean(axis=1)
n = min(len(v), len(i)); v, i = v[:n], i[:n]
# Only where the voice is sounding, or the silences flatter it.
on = np.abs(v) > 0.2 * np.percentile(np.abs(v), 99.5)
db = lambda x: 20 * np.log10(max(float(x), 1e-9))
print(db(np.sqrt((v[on]**2).mean())) - db(np.sqrt((i[on]**2).mean())))
"@
```

Above the band, the separator has something clean to take and the clips need
no rescuing. Below it, everything downstream degrades together: the stem is
quiet and full of artefacts, standardising lifts it about 8 dB with the
artefacts included, and pitch tracking stops being reliable. No cutting,
gating or level change repairs that, and four rounds of trying produced
nothing worth keeping. Measure first and say early that a source is a poor
candidate.

Roformer is the separator to use, and it was measured rather than assumed:
against the same buried source it left 0.103 correlation with the
instrumental where Demucs left 0.146. It is better and still not enough on a
bad source.

### When the words have no silence between them

`mine_words` cuts on silence, so a list recited without gaps defeats it.
Three threshold settings each returned two clips of about twenty-nine seconds;
a fourth, pushed harder, split them into four clips with half starting
mid-word. Word timestamps from the recogniser are the only boundary such audio
contains.

Two traps in doing that:

- **Never pass `initial_prompt`.** Telling Whisper the vocabulary to expect
  raised recall from 25 words to 349 and destroyed precision: the merged set
  had a median duration of 0.00 s and only 18% sat on audible vocal. It
  invents words to match the prompt.
- **One pass is not evidence.** The same seventy-three seconds gave 25 words
  on one run and 8 on the next. Merge several passes, longest detection per
  word winning.

Then keep only what survives two gates, both against the stems rather than
the clip alone: the vocal has to be **loud** where the word was heard, and
**uncorrelated** with the instrumental there. Loudness alone passes pure
backing, because the band is loud too.

### Check every clip's pitch against a second detector

The most expensive lesson. Everything downstream trusts the pitch stored for
a clip, and on a processed voice that number can simply be wrong: **9 of 15
clips disagreed with an independent `pyin` estimate by 7 to 19 semitones**. A
clip believed to be at 73 that is really at 54 gets shifted confidently in
the wrong direction, and the result screams. A wrong pitch is worse than a
missing clip.

Cross-check, discard disagreements, then look at the spread of what is left.
Six survivors still spanned **30 semitones** against melodies sitting around
62, so most were octave-folded and landed an octave from the tune. Transpose
them into one register **by whole octaves only**: an octave keeps the voice,
anything else makes it a different singer.

### The bank's own level

`words_hq4` declares no `bank.json`, so it uses `config.WORD_BUS_LUFS`,
**−14.0**. Copying `−11.0` from a spoken bank without measuring made every
render sound wrong in a way that was not simply loudness: the hotter word bus
tripped the −1 dB ceiling in `mapping.mix`, which scales the whole mix down,
so the band was dragged about 2 dB below reference while the words rode
+2.99 above it against +1.58 on a good render. Match the reference bank
unless there is a measured reason not to.

**Pitch spread matters more than quantity.** Takes at *new* pitches raise the
mimicry ceiling directly, by reducing how much has to be octave-folded. Ten more
takes at the same pitch as everything else change nothing.

---

## Re-cut the bank from cleaner stems

The clips were cut from Demucs stems, so whatever instrumental residue Demucs
left behind is baked into them. Re-separating with the Roformer and cutting
again over the same time ranges replaces the audio under every clip without
losing a name, label or syllable boundary.

```powershell
.\.venv\Scripts\python.exe -m song_generator.separate_hq --for-bank "sources\*.mp4"
.\.venv\Scripts\python.exe -m song_generator.recut_bank --out words_hq2
```

`--for-bank` narrows the files you pass to the ones the current bank was cut
from. It cannot find them on its own: the bank records which work directories
its clips separated into, not where the source media lives, so the files or
globs are always given.

`recut_bank` writes an index that describes exactly what it wrote. A clip it
could not write, because its span collapsed against the new stem, or would not
write, because it appeared in the output mid-run and may be hand work, is
dropped from `words.json` and reported, together with the `build_bank` command
that puts the words back once the clips are restored. A word only those clips
carried would otherwise vanish silently at render time, since a render reads
the index alone.

---

## The words are too dense / too sparse

All in the `DENSITY` block of `config.py`:

| Constant | Raise it to... | Lower it to... |
|---|---|---|
| `PHRASE_FILL` | fill more phrases | leave more instrumental space |
| `SHOUT_MAX_SHARE` | more `aah` | less |
| `PREFER_LONGER_UNITS` | fewer, longer placements | busier, more varied |

`PHRASE_FILL` is the blunt instrument; reach for it first. Keep
`PREFER_LONGER_UNITS` mild, at 1.4 the longest clip in the bank won nearly
every slot and the track became one phrase on repeat.

---

## `calculator` never appears / appears too often

The `CLIMAXES` block. `calculator` is refused outside the song's peaks, so it
stays a payoff.

- Never appears? Check that a climax phrase is **long enough to hold it**. The
  smallest `aah+calculator` unit is 5 syllables, and phrases shorter than that are
  excluded from being peaks. This failed silently once.
- Too often? Lower `CLIMAX_PHRASE_SHARE` or `CLIMAX_USE_CHANCE`.
- Want the occasional one off-peak as a joke? `CLIMAX_WILDCARD_CHANCE`.

---

## A song comes back "Mode B, no vocals"

It failed one of two independent tests, and the run prints which. Both must
pass, because they catch different things: loudness catches a near-silent stem,
voicing catches a stem that is loud but full of instrumental bleed.

If it genuinely has vocals, the thresholds are in the `STAGE 1b` block. Try
`--separator roformer` first. It separates vocals noticeably better, and a
weak stem is the usual cause.

---

## Put the site online

The front end is hosted on Azure Static Web Apps, Free plan, and published by
`.github/workflows/deploy.yml`. What runs in Azure and what deliberately does
not is in [AZURE.md](AZURE.md).

**1. Create the site.** Once, from a machine signed in with `az login`:

```powershell
az deployment sub what-if --location westeurope --template-file infra\main.bicep
az deployment sub create  --location westeurope --template-file infra\main.bicep
```

`what-if` changes nothing and prints what the second command would do. Both
create a resource group `rg-songgen-web` and a Free-plan site in it.

**2. Nothing to point anywhere.** `.github/workflows/deploy.yml` is already in
the repository, so a push to `main` that touches `web/` builds and publishes.
GitHub Actions is unmetered on standard runners for a public repository: no
grant request, no second console, no organisation to belong to.

This used to be Azure DevOps and `azure-pipelines.yml`, which is still here
with its trigger off so the two can be read side by side.
[AZURE.md](AZURE.md) has why it moved. The short version is that it stopped
producing runs and nothing in the repository could tell.

**3. Give the repository two secrets.** GitHub, Settings, Secrets and
variables, Actions:

| Secret | Value |
|---|---|
| `AZURE_STATIC_WEB_APPS_API_TOKEN` | see below |
| `GOOGLE_CLIENT_ID` | the OAuth client id, once there is one |

The token is the one credential here, and it is enough on its own to publish to
the site, so it is never committed:

```powershell
az staticwebapp secrets list --name songgen-web --query "properties.apiKey" -o tsv
gh secret set AZURE_STATIC_WEB_APPS_API_TOKEN
gh secret set GOOGLE_CLIENT_ID
```

`gh secret set` with no value prompts for one and does not echo it, which is
why it is written that way rather than piped from the command above it.

The client id is not secret and cannot be. The browser has to know which client
signs people in, so it is in the shipped files however it gets there. The
allowlist on the edge is what actually protects the service.

Both are secrets here even though only one is. GitHub's plain variables are
readable by any workflow in any fork's pull request, and the client id being
public in the shipped files is not a reason to hand it to arbitrary workflow
code as well.

The backend address is not among these. It is `API_BASE_URL` in
`.github/workflows/deploy.yml`, because the edge is reached through a proxy on
a domain this repository names everywhere, and hiding a public hostname bought
nothing. Committing it also removes a trap worth knowing about even now:
**editing a value in a web UI does not start a build**, and `config.json` is
written during one, so the value changed and the site did not. Editing the
workflow triggers the deploy that applies it.

Missing the client id is not a failure. Sign-in is unavailable and the site
says so, which it renders honestly. Missing the address is not a failure
either: away from localhost the site assumes no backend rather than probing the
visitor's own machine, and reports that nothing is answering.

**4. Check that a deploy actually happened.** Not optional, and not the same
question as whether the build was green:

```powershell
curl.exe -s https://<the site hostname>/ | Select-String -Pattern 'main-\w+\.js'
```

The build hashes every bundle name, so that filename changes whenever the
sources do. Run `npx ng build` in `web` and compare it against what came back:
the same hash means the deploy landed, an older one means the site is still
serving a previous build.

This step exists because a front end was rewritten, reviewed, merged with
everything green, and never published: the site went on serving a build six
commits old while nothing anywhere said so.

The suspect at the time was the Azure pipeline's path filter, `web/*`, which
is genuinely ambiguous: Azure Pipelines supports wildcards and `**` is the form
that crosses directories, which would leave a single `*` matching only the
files sitting directly in `web`, while for older servers the documentation says
a trailing `*` does nothing different from naming the directory. It was changed
to `web`, and nothing ran. The workflow that publishes today writes `web/**`,
where GitHub's own documentation is unambiguous.

**What is established, and what is not.** All five deploys this site has had
came from commits that also touched `azure-pipelines.yml`, the filter's other
entry, and none from a change to the site alone. That is a strong correlation
and it is not a proof: the merge that should have published the design added
`web/DESIGN.md`, which sits directly inside `web` and matches the old filter
under every reading, and no build ran. So something else may be involved, and
the repository cannot see it.

The repository's Actions tab is where to look now, in this order:

1. **Is there a run at all** for the commit? If not, the paths filter did not
   match, and `web/**` is the thing to read.
2. **Did the publish step succeed while the check step failed?** Then the
   upload went somewhere other than this site, and the deployment token is the
   thing to check.
3. **Did a run fail earlier than that?** Then the step that failed says why,
   and the site keeps serving the previous build, which is the intended
   behaviour rather than a second fault.

The workflow ends by asking the site what it is serving and fails if it is not
this build, so a green run means a live change rather than a successful
upload.

**5. Reach the backend from the internet.** It runs on a desktop behind a home
connection, so it needs a tunnel. Tailscale Funnel is the free one:

```powershell
tailscale funnel 8000
```

The address it prints is where the edge answers. The site does not call it
directly: `mikkonumminen.dev` proxies `/api/songgen/*` to it, and
`API_BASE_URL` in `.github/workflows/deploy.yml` points at that proxy
instead.

The proxy is not decoration. On any machine signed in to the tailnet, MagicDNS
resolves a `*.ts.net` name to the node's own `100.x` address, so a browser sees
a public page reaching into a private network and blocks it. The site then
reports the backend as unreachable for the one person most likely to be testing
it, while working for everyone else. Vercel's edge is not on the tailnet, so
routing through it makes the address behave the same for everybody.

**6. Let the browser call it.** A page on `azurestaticapps.net` calling the edge
is cross-origin, so the edge has to allow it. On the machine running the edge:

```powershell
$env:SONGGEN_ALLOWED_ORIGINS = "https://<the site hostname>"
```

**The site's hostname, not the API's.** An origin is a property of the page
making the request, so routing through the proxy does not change it: the
browser still says it came from the Static Web App. Adding the proxy's domain
here allows nothing and protects nothing.

Without it every request fails the preflight and the site reports the machine
as unreachable, which is technically true and thoroughly unhelpful.

Measured through the proxy rather than assumed. A preflight for an
authenticated `GET`, carrying the site's origin, comes back with
`Access-Control-Allow-Origin` echoing that origin, `Allow-Headers` including
`Authorization`, and `Vary: Origin`. So the proxy forwards the preflight and
the edge answers it as if the browser had called directly.

Two things about a single page app on a static host, both of which fail as a
blank screen rather than as an error:

- A Static Web App serves from the root of its own hostname, so the build takes
  no `--base-href`. Passing one, as a GitHub project page would need, 404s
  every script after the page loads.
- There is no file at `/runs/abc`, so `web/public/staticwebapp.config.json`
  rewrites unknown paths to `index.html` and hands them to the router.

### Publishing without the workflow

`.github/workflows/deploy.yml` is the normal way and this is the way out when
it cannot run, which has happened to the publisher before: `dev.azure.com`
redirects a personal Microsoft account into the Azure Portal, and the portal's
tenant picker then refuses that account outright (`AADSTS16000`). With no
access to the thing that publishes there is no way to change a value and no way
to press Run, and a broken site stays broken.

`az` on a machine that is signed in can hand over the deploy token, and the
Static Web Apps CLI takes it directly:

```bash
token=$(az staticwebapp secrets list --name songgen-web \
        --query "properties.apiKey" -o tsv)
cd web && npx ng build
cat > dist/songgen-web/browser/config.json <<'JSON'
{ "apiBaseUrl": "...", "googleClientId": "..." }
JSON
npx --yes @azure/static-web-apps-cli deploy dist/songgen-web/browser \
    --deployment-token "$token" --env production
```

The config file is written by hand here because nothing else is going to write
it; the workflow step that normally does is exactly what is being skipped.

**What this costs is the guarantee that the site matches `main`.** A workflow
run is reproducible from a commit and this is not, so after using it, land the
same change in git before the next push does. Any push touching `web` or the
workflow itself rebuilds from `main` and silently reverts whatever was
deployed by hand.

---

## Let people sign in

Every route but the health check is behind Google sign-in and an allowlist of
named accounts, because the pipeline takes an arbitrary link and spends a GPU
on it. The browser only carries a token; the edge decides who may use anything.

**1. Make an OAuth client.** In the Google Cloud console this lives under
**Google Auth platform**, then **Clients**, then **Create client**. It used to
be under APIs and Services, Credentials, and older instructions still say so.

Application type **Web application**.

Under **Authorised JavaScript origins**, add the site, and the dev server if
you develop against it. Google wants the port-less form as well as the one with
a port:

```
https://<the site hostname>
http://localhost
http://localhost:4200
```

Authorised **redirect URIs** stay empty. Identity Services hands the token back
to the page through a callback rather than redirecting anywhere, so a redirect
URI here is one more thing to get wrong for no benefit.

If this is the first client in the project, the console asks for the consent
screen first. **External**, with yourself added as a **test user**, is enough
and is the honest shape: the service is meant for a named few rather than for
whoever finds it. Leaving it in Testing rather than publishing it costs nothing
here, because only ID tokens are used and a fresh one is issued at each
sign-in; the seven-day limit that catches people in Testing applies to refresh
tokens, which this never asks for.

**2. Give the client id to both halves.** The pipeline variable
`GOOGLE_CLIENT_ID` puts it in the site. The edge needs the same id, plus the
list of who may actually use it:

```powershell
$env:SONGGEN_GOOGLE_CLIENT_ID = "<client id>.apps.googleusercontent.com"
$env:SONGGEN_ALLOWED_EMAILS   = "you@example.com,someone.else@example.com"
```

Both are required for anyone to get in. With either missing the edge reports
sign-in as unconfigured, and the site says so rather than showing a button that
cannot work.

The two lists do different jobs and both matter. The client id decides which
site Google will issue a token to; the allowlist decides whose token this
service accepts. A real Google account that is not on the list gets no further
than no account at all.

**3. Check it.** Sign in on the site, then confirm the edge agrees:

```powershell
curl.exe -H "Authorization: Bearer <token>" https://<edge>/banks
```

A 200 means the whole chain works. A 401 naming the allowlist means Google
issued a token for somebody this service does not accept, which is the check
doing its job.

---

## Verify a change

```powershell
$env:PYTHONPATH='.\src'
.\.venv\Scripts\python.exe -m pytest tests\ -q
.\.venv\Scripts\song-generator.exe input\musicHyva.mp4 --rows 0
```

The second matters more. Watch these numbers. They move when behaviour changes:

- **units placed** and **slots filled**: density
- **mimicry** and **ceiling**: how closely the tune survives
- **octave-folded %**: how far the bank sits from this song's register
- **units used**: whether the vocabulary is what you expect

---

## Set syllables aside, or bring them back

Rarely wanted now. Syllable clips used to crowd out the words, because a clip
of `bra` filled a slot as neatly as one of `bravo` and said nothing. The pool
a song is chosen from is filtered to whole words, so a bare syllable is never
placed, and those clips instead spell words no recording contains. Setting
them aside costs that and buys nothing, so the command reports which words
would stop being spellable before you decide.

```powershell
.\.venv\Scripts\python.exe -m song_generator.set_aside            # out of the bank
.\.venv\Scripts\python.exe -m song_generator.set_aside --restore  # back in
```

Renames between `bra.wav` and `SYL_bra.wav`. Nothing is deleted; the ear-work
that identified them stays recorded in the name either way.
