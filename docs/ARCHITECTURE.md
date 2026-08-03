# Architecture

Read `docs/GLOSSARY.md` first — slot, unit, phrase, mimicry and fold all carry
specific meanings here.

## The idea in one paragraph

A song's singer already decided everything musical: when each syllable starts,
how long it lasts, what note it lands on. The tool recovers those decisions from
the original vocal and then puts different words on them. It never invents a
musical decision, which is why a song *without* a vocal (Mode B) is refused
rather than attempted — there would be nothing to borrow.

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
   │                    (pitch change AND energy onset — neither alone
   │                     sees both a slur and a repeated note)
   │
   ├─ mapping.py ────── plan + render ── the whole arrangement decision
   │      clean_slots      blips merged, held notes split
   │      group_phrases    slots → sung lines
   │      find_climaxes    where paviaani is allowed
   │      plan_words       which unit goes where
   │      decide_shifts    which units sing along (MIMICRY)
   │      render           audio, via pitchshift
   │      mix              level-matched against the instrumental
   │
   └─ 7 mp3s, one per mimicry setting
```

## Modules

### The pipeline

| Module | Does | Key exports |
|---|---|---|
| `cli.py` | Wires everything; one run writes the whole mimicry sweep | `main` |
| `audio_io.py` | The only place sample rate and array shape are established | `decode`, `encode_mp3`, `read_wav` |
| `separate.py` | Demucs or Mel-Band Roformer behind one interface, cached | `separate`, `Stems` |
| `detect.py` | Mode A vs Mode B, with the numbers behind the verdict | `detect_vocal`, `VocalReport` |
| `analysis.py` | Melody and syllable timing out of the original vocal | `analyse`, `Analysis` |
| `mapping.py` | Every arrangement decision, plus render and mix | `load_bank`, `plan_words`, `render`, `mix` |
| `pitchshift.py` | WORLD or Rubber Band; octave folding | `render_unit`, `fold_shift` |
| `config.py` | Every tunable, grouped by stage, with the reasoning | — |
| `util.py` | Device resolution, work-dir naming, formatting | `resolve_device`, `work_dir_for` |

### Building the bank

These do not run during a song. They turn source videos into reviewed clips.

| Module | Does |
|---|---|
| `mine_words.py` | Many sources at once: separate, cut candidates, one folder each |
| `extract_words.py` | Cut one source into candidate clips |
| `flatten.py` | Collapse per-source folders into one flat reviewable folder |
| `label_words.py` | Speech-recognition *hints* (unreliable here — see CLAUDE.md) |
| `precheck.py` | Per-clip guessing, constrained by measured syllable count |
| `hunt.py` | Find a shout-then-word shape on the envelope, no model needed |
| `successors.py` | Re-cut what follows a shout, since cutting severs `eee paviaani` |
| `set_aside.py` | Take syllable clips out of the bank without deleting them |
| `build_bank.py` | Reviewed clips → `words/words.json`; filename parsing lives here |

## Data on disk

| Path | Written by | Contains | Regenerable? |
|---|---|---|---|
| `work/<song>/vocal.wav` | `separate` | Separated vocal | Yes, slowly |
| `work/<song>/analysis.json` | `analysis` | Notes, phrases, beats, F0 | Yes |
| `work/<song>/detect.json` | `cli` | The Mode A/B verdict and its numbers | Yes |
| `words/words.json` | `build_bank` | Every unit: pitch, duration, syllable bounds | Yes |
| `words/*.wav` | `build_bank` | The bank's audio | Yes |
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
non-obvious values arrived at by measurement — `PREFER_LONGER_UNITS` was 1.4 and
made the longest clip win every slot. The comment records that so it is not
raised again casually.

**Separation sits behind an interface.** Its quality sets the ceiling for
everything downstream: the vocal stem drives melody and timing, and any vocal
residue left in the instrumental sits audibly under the replacement words.

**Resynthesis is precomputed once per run.** Which units a mimicry variant
shifts is only a selection over the same shifted set, so seven variants cost
barely more than one.
