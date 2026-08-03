# Workflows

Recipes for the jobs that actually come up. Every command assumes the repo root
and the project's own venv.

---

## Make a track from a song

```powershell
.\.venv\Scripts\luokkaretki-generator.exe input\song.mp4
```

Writes seven mp3s to `output/`, one per mimicry setting from 0.00 (words ignore
the tune entirely — clashing, and funny for it) to 1.00 (sings the melody as
closely as the song allows). Pick by ear; there is no correct value, and the
right one varies by song.

First run on a song pays for separation (~0.45x realtime). Every later run on
the same song reuses the cached stems and takes seconds.

**Useful flags**

| Flag | Effect |
|---|---|
| `--mimicry 0.45` | One file at one setting instead of the sweep |
| `--bank chaos` | Sing with every candidate clip, identity ignored |
| `--seed 42` | Different word choices, same everything else |
| `--no-shift` | Words at their own recorded pitch |
| `--rows 30` | Print more of the extracted note table |
| `--json` | Machine-readable summary |

---

## Add words to the bank

Only a person can say what a clip contains, so this loop is built around
listening. It is the one part that cannot be automated.

```powershell
# 1. Cut candidates out of one or many sources
.\.venv\Scripts\python.exe -m luokkaretki_generator.mine_words "D:\clips\*.mp4"

# 2. Collapse into one flat folder, tagging what has not been reviewed
.\.venv\Scripts\python.exe -m luokkaretki_generator.flatten

# 3. LISTEN. Delete junk. Rename keepers after what you hear.
#       TODO_2syl__kirby__c07__1.42-1.98.wav   ->   paska7.wav

# 4. Build
.\.venv\Scripts\python.exe -m luokkaretki_generator.build_bank
```

**Naming.** All of these parse: `paska`, `paska1`, `paska_2`, `paska_low`,
`PASKA3`. Multi-word clips keep the singer's own transitions and are worth more
than their parts — name them as sequences: `persepillu`, `eeepaviaani`. A shout
can be spelled however it sounded: `eee`, `eeei`, `eiii`, `eeiii`.

**Removing the prefix is what confirms a clip.** Anything still tagged is
ignored by the bank, so leaving a clip alone is always safe.

**Pitch spread matters more than quantity.** Takes at *new* pitches raise the
mimicry ceiling directly, by reducing how much has to be octave-folded. Ten more
takes at the same pitch as everything else change nothing.

---

## The words are too dense / too sparse

All in the `DENSITY` block of `config.py`:

| Constant | Raise it to… | Lower it to… |
|---|---|---|
| `PHRASE_FILL` | fill more phrases | leave more instrumental space |
| `SHOUT_MAX_SHARE` | more `eee` | less |
| `PREFER_LONGER_UNITS` | fewer, longer placements | busier, more varied |

`PHRASE_FILL` is the blunt instrument; reach for it first. Keep
`PREFER_LONGER_UNITS` mild — at 1.4 the longest clip in the bank won nearly
every slot and the track became one phrase on repeat.

---

## `paviaani` never appears / appears too often

The `CLIMAXES` block. `paviaani` is refused outside the song's peaks, so it
stays a payoff.

- Never appears? Check that a climax phrase is **long enough to hold it**. The
  smallest `eee+paviaani` unit is 5 syllables, and phrases shorter than that are
  excluded from being peaks. This failed silently once.
- Too often? Lower `CLIMAX_PHRASE_SHARE` or `CLIMAX_USE_CHANCE`.
- Want the occasional one off-peak as a joke? `CLIMAX_WILDCARD_CHANCE`.

---

## A song comes back "Mode B — no vocals"

It failed one of two independent tests, and the run prints which. Both must
pass, because they catch different things: loudness catches a near-silent stem,
voicing catches a stem that is loud but full of instrumental bleed.

If it genuinely has vocals, the thresholds are in the `STAGE 1b` block. Try
`--separator roformer` first — it separates vocals noticeably better, and a
weak stem is the usual cause.

---

## Verify a change

```powershell
$env:PYTHONPATH='D:\koodaamista\LuokkaretkiGenerator\src'
.\.venv\Scripts\python.exe -m pytest tests\ -q
.\.venv\Scripts\luokkaretki-generator.exe input\musicHyva.mp4 --rows 0
```

The second matters more. Watch these numbers — they move when behaviour changes:

- **units placed** and **slots filled** — density
- **mimicry** and **ceiling** — how closely the tune survives
- **octave-folded %** — how far the bank sits from this song's register
- **units used** — whether the vocabulary is what you expect

---

## Set syllables aside, or bring them back

```powershell
.\.venv\Scripts\python.exe -m luokkaretki_generator.set_aside            # out of the bank
.\.venv\Scripts\python.exe -m luokkaretki_generator.set_aside --restore  # back in
```

Renames between `pas.wav` and `SYL_pas.wav`. Nothing is deleted; the ear-work
that identified them stays recorded in the name either way.
