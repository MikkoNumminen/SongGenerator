# Architecture

Read `docs/GLOSSARY.md` first, slot, unit, phrase, mimicry and fold all carry
specific meanings here.

## The idea in one paragraph

A song's singer already decided everything musical: when each syllable starts,
how long it lasts, what note it lands on. The tool recovers those decisions from
the original vocal and then puts different words on them. It never invents a
musical decision, which is why a song *without* a vocal (Mode B) is refused
rather than attempted. There would be nothing to borrow.

## Pipeline

```
song.mp4
   │
   ├─ audio_io.decode ───────────────── float32 (2, n) at 44100
   │
   ├─ separate.py ──── Demucs ───────── vocal.wav + instrumental.wav
   │                                     cached in work/<song>/
   │
   ├─ detect.py ─────── two tests ───── Mode A or Mode B
   │                    (loudness relative to mix, voiced-frame fraction;
   │                     both must pass. They fail on different things.)
   │                                     └─ Mode B ⇒ exit 3, refused
   │
   ├─ analysis.py ───── melody + timing ── analysis.json
   │                    F0 contour, note boundaries from TWO signals
   │                    (pitch change AND energy onset, neither alone
   │                     sees both a slur and a repeated note)
   │
   ├─ arrange.py ────── playfulness ──── one arrangement per level, logged
   │      slice_words      words cut out of recorded phrases
   │      build            drawn from a seed, redrawn until coverage holds
   │
   ├─ mapping.py ────── plan + render ── the whole arrangement decision
   │      clean_slots      blips merged, held notes split
   │      group_phrases    slots → sung lines, capped in length
   │      find_climaxes    where the payoff is allowed
   │      plan_words       which unit goes where, by role and fit
   │      decide_shifts    which units sing along (MIMICRY)
   │      render           audio, via pitchshift
   │      mix              level-matched against the instrumental
   │
   └─ 14 mp3s: both playfulness levels x 7 mimicry settings
```

## Modules

### The pipeline

| Module | Does | Key exports |
|---|---|---|
| `cli.py` | Wires everything; one run writes both levels across the mimicry sweep | `main` |
| `audio_io.py` | The only place sample rate and array shape are established | `decode`, `encode_mp3`, `read_wav` |
| `separate.py` | Demucs or Mel-Band Roformer behind one interface, cached | `separate`, `Stems` |
| `detect.py` | Mode A vs Mode B, with the numbers behind the verdict | `detect_vocal`, `VocalReport` |
| `analysis.py` | Melody and syllable timing out of the original vocal | `analyse`, `Analysis` |
| `mapping.py` | Every arrangement decision, plus render and mix | `load_bank`, `plan_words`, `render`, `mix` |
| `banks.py` | Per-bank behaviour from `bank.json`: which strategy each level uses, and its overrides | `strategy_for`, `overrides_for` |
| `pitchshift.py` | WORLD or Rubber Band; octave folding | `render_unit`, `fold_shift` |
| `config.py` | Every tunable, grouped by stage, with the reasoning |, |
| `util.py` | Device resolution, work-dir naming, glob expansion, word scoring | `resolve_device`, `work_dir_for`, `expand`, `word_similarity` |

### Building the bank

These do not run during a song. They turn source videos into reviewed clips.

| Module | Does |
|---|---|
| `mine_words.py` | Many sources at once: separate, cut candidates, one folder each |
| `extract_words.py` | Cut one source into candidate clips |
| `flatten.py` | Collapse per-source folders into one flat reviewable folder |
| `label_words.py` | Speech-recognition *hints* (unreliable here, see AGENTS.md) |
| `precheck.py` | Per-clip guessing, constrained by measured syllable count |
| `hunt.py` | Find a shout-then-word shape on the envelope, no model needed |
| `successors.py` | Re-cut what follows a shout, since cutting severs `aah calculator` |
| `set_aside.py` | Take syllable clips out of the bank without deleting them |
| `build_bank.py` | Reviewed clips → `words/words.json`; filename parsing lives here |

### Operating it

| Module | Does |
|---|---|
| `batch.py` | Render many songs in one command; one failure does not end the run |
| `doctor.py` | Read-only: bank contents, pitch coverage, a song's slots and predicted shift |
| `separate_hq.py` | Re-separate sources with Mel-Band Roformer into `vocal_hq.wav` |
| `recut_bank.py` | Re-cut the bank from those stems, keeping every label |
| `standardize.py` | Trim, fade and level a bank into a derivative tier beside it |
| `arrange.py` | Cut words out of recorded phrases; build and replay arrangements |

These are deliberately scripts rather than anything cleverer. Their inputs are
enumerable and their work is deterministic, so there is no judgement to
delegate. The one decision that does need judgement, whether a result sounds
good, cannot be made by anything without ears.

`recut_bank.py` takes the source from a clip's filename but always derives the
offset by cross-correlation. Filenames are not reliable evidence of where audio
starts: clips written by `successors.py` are padded 50 ms earlier than the
timestamp they record, and trusting the name cut the attack off 34 shouts.

`arrange.py` exists because the bank is recorded *phrases*, not words. Most
clips hold two or three words at once, which is why the result sounds like a
person rather than a sampler, and also why the automation could only repeat
sequences somebody had already sung. `build_bank` already measured where each
word starts inside each clip, so the same numbers cut a phrase back into its
words. A single word is a slice; a new order is slices crossfaded together.

Recorded clips always win where one exists, because a real recording carries
the singer's own transition between two words and a crossfade does not. The
slices are what let the tool say something that was never recorded.

A run renders BOTH playfulness levels, each producing one arrangement of its
own, and each arrangement is then rendered across the whole mimicry ladder:
fourteen files. Playfulness and mimicry are different questions and
deliberately do not multiply into each other, but which level is funnier is a
listening decision, so shipping one of them and offering the other would leave
the decision needing another command.

Which words get sung is not left to duration fit alone. The bank's words have
roles with shares of the song attached, weighted per level: a handful of core
words carry it, a long word is rarer and finishes a combination, the shout and
the payoff are seasoning, and words the bank accumulated but the song is not
about are a garnish. Without that the shout wins constantly, being a third of
the recordings and short enough for any slot. Units are also ranked by origin,
so a clip the singer sang whole beats a word cut out of one, which beats an
order nobody sang, which beats a word assembled from syllable fragments.

Coverage outranks every one of those weights. A share is a preference and a
missing required word is a broken rule, so when the weights are what holds a
word out they are relaxed and then dropped. `docs/GLOSSARY.md` defines the
roles and origins.

All of that describes the `arranged` strategy, which is what every bank gets
unless it says otherwise. A bank may say otherwise in a `bank.json` beside its
clips, read by `banks.py` and always resolved to the bank as declared, so
`--words-dir` pointed at a bank or at its standardised tier gets the declared
behaviour either way. The other strategy is
`sequence`: the recordings replayed in the order they were spoken, sorted by
the variant index `build_bank --raw` writes, looping when they run out, with
no seed, no draws and no coverage redraw, because the order is the content. A
bank may also declare overrides that sit on top of a level's parameters from
`PLAY_LEVELS`, merged onto a copy so nothing leaks into the next song of a
batch. A bank with no `bank.json` behaves exactly as every bank did before
the file existed, and `tests/test_determinism.py` pins the existing bank's
placements so that cannot drift. `docs/DATA-FORMATS.md` documents the file.

Every arrangement is written to `work/<song>/arrangements/` as a file a person
can read and edit, and `--arrangement` plays one back. Replay rebuilds the
placements from the file rather than replanning, so an edited file produces
what it says. That format is also the one a "supply your own lyrics" mode would
consume, which is why `unit_for` will assemble any word order out of slices
rather than only recognising the ones the tool generated.

`standardize.py` works in tiers. The recorded clips are the source of truth and
are never written to; the pass reads them and produces new files in a sibling
directory, `words_hq.std`, each traceable to the clip it came from by a hash of
that clip's bytes. Every write goes through one function that refuses any
destination which is, contains, or sits inside a source directory, so
overwriting a recording is structurally impossible rather than merely avoided.

It changes edges and levels only: dead air trimmed off each end, a short fade
over the cut, and a loudness target so no word blares while the next disappears.
Nothing touches timbre. The rough sound of each word is the point of the bank.

The runtime prefers the tier when it exists and falls back to the recorded clips
when it does not, so a clone that has never run the pass behaves exactly as it
did before the tier existed. Standardised clips skip `level_clip` on load: they
arrive levelled to a loudness target, and re-levelling them to an RMS one would
undo that silently.

## Data on disk

| Path | Written by | Contains | Regenerable? |
|---|---|---|---|
| `work/<song>/vocal.wav` | `separate` | Separated vocal | Yes, slowly |
| `work/<song>/analysis.json` | `analysis` | Notes, phrases, beats, F0 | Yes |
| `work/<song>/detect.json` | `cli` | The Mode A/B verdict and its numbers | Yes |
| `words/words.json` | `build_bank` | Every unit: pitch, duration, syllable bounds | Yes |
| `words/bank.json` | a human | The bank's declared strategy and overrides, per level | Yes |
| `words/*.wav` | `build_bank` | The bank's audio | Yes |
| `words_hq.std/*.wav` | `standardize` | Trimmed, levelled derivatives | Yes |
| `words_hq.std/standardized.json` | `standardize` | Each derivative's source and hash | Yes |
| `words/candidates/*.wav` **unprefixed** | **a human** | **Reviewed clips** | **No** |
| `output/*.mp3` | `cli` | The results | Yes |

Only one row cannot be regenerated. That is why no automatic pass touches an
unprefixed clip.

## Why decisions live where they do

**Slot cleanup happens in stage 3, not stage 2.** `analysis.json` stays a
faithful record of what was actually heard. Merging blips and splitting held
notes is a mapping decision, and baking it into the analysis would make the
record lie.

**`config.py` holds reasoning, not just values.** Several constants have
non-obvious values arrived at by measurement, `PREFER_LONGER_UNITS` was 1.4 and
made the longest clip win every slot. The comment records that so it is not
raised again casually.

**Separation sits behind an interface.** Its quality sets the ceiling for
everything downstream: the vocal stem drives melody and timing, and any vocal
residue left in the instrumental sits audibly under the replacement words.

**Resynthesis is precomputed once per run.** Which units a mimicry variant
shifts is only a selection over the same shifted set, so seven variants cost
barely more than one.
