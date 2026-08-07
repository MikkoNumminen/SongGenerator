# Workflows

Recipes for the jobs that actually come up. Every command assumes the repo root
and the project's own venv.

---

## Make a track from a song

```powershell
.\.venv\Scripts\song-generator.exe input\song.mp4
```

Writes **fourteen** mp3s to `output/`: both playfulness levels, and for each,
seven mimicry settings from 0.00 (words ignore the tune entirely, clashing,
and funny for it) to 1.00 (sings the melody as closely as the song allows).

```
output/song/song.conservative.mim0p00.mp3 ... mim1p00.mp3
output/song/song.wild.mim0p00.mp3         ... mim1p00.mp3
```

Each song gets its own folder. Fourteen files a run across a dozen songs is
nearly two hundred in one directory, sorted by name, with every song's levels
and rungs interleaved. The song name stays in the filename too, so a file
dragged out of its folder still says what it is.

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
song, since each arrangement is resynthesised separately. The seven mimicry
settings within a level are nearly free, because they are a selection over the
same shifted set. `--play conservative` halves the time when only one level is
wanted.

**Useful flags**

| Flag | Effect |
|---|---|
| `--mimicry 0.45` | One file at one setting instead of the sweep |
| `--play wild` | One level instead of both |
| `--arrangement <path>` | Replay a saved arrangement exactly, or an edited one |
| `--bank chaos` | Sing with every candidate clip, identity ignored |
| `--seed 42` | Fix the arrangement seed; otherwise a new one each run |
| `--raw-clips` | Ignore the standardised tier, sing the recordings as they are |
| `--no-shift` | Words at their own recorded pitch |
| `--rows 30` | Print more of the extracted note table |
| `--json` | Machine-readable summary |

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
