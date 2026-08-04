# Glossary

Terms with a specific meaning in this codebase. Several are ordinary words used
narrowly; guessing at them will mislead you.

## The pipeline's units of work

**Slot**. One place in the original melody where a syllable was sung. Produced
by stage 2 from the original vocal: an onset, an offset and a pitch. A slot
holds exactly one syllable. `Slot` in `mapping.py`.

**Note**. The raw output of melody extraction, before cleanup. Notes become
slots once blips are merged and held notes are split. `analysis.json` records
notes; slots exist only in memory. Keeping them separate is deliberate:
`analysis.json` stays a faithful record of what was heard, rather than something
already massaged toward a mapping decision.

**Phrase**. A run of consecutive slots with no gap longer than
`PHRASE_GAP_S` between them. A sung line. Words never straddle a phrase
boundary.

**Unit**. One clip from the bank, and the thing actually placed on the melody.
A unit may be one word (`bravo`), several words the singer ran together
(`tango+delta+tango`), a shout (`aah`), or a word spelled from syllable clips.
Its length is measured in syllables, which is the same thing as how many slots
it fills.

**Bank**. The collection of units available to sing with. Built by
`build_bank.py` from reviewed clips into `words/words.json`. Two are prebuilt:
`curated` (reviewed clips, the default) and `chaos` (every candidate clip taken
raw, names ignored).

**Candidate**. A clip cut out of a source video but not yet identified. Lives
in `words/candidates/` with a prefix until a human renames it.

## Pitch

**Shift**, how far a clip must move to land on its slot's note, in semitones.

**Fold**, when a shift exceeds `SHIFT_CAP_SEMITONES`, moving it by whole
octaves instead until it is small. The word then sings the note *name* the
melody asked for, in a register the recorded voice can actually reach. Landing
an octave out is far less noticeable than a chipmunk.

**Mimicry**, how much of the original melody survives in the result, 0 to 1.
Not the same as how many units were shifted: a folded syllable carries the tune
in part (right note name, wrong octave), so it counts for `FOLDED_FIT` rather
than 1. This is the dial worth using, because it means the same thing across
songs.

**Ceiling**. The highest mimicry a given song can reach against a given bank,
set by how much of it has to be folded. A song ranging far above the bank's
register cannot sound fully sung however hard it is pushed. Reported on every
run.

## Content

**Word**. One of the five: `bravo`, `tango`, `delta`, `kilometer`,
`calculator`. Plus `aah`, the shout.

**Syllable**. A fragment of a word (`pas`, `ka`, `leh`, `ti`). Kept for
*spelling* words that were never recorded intact, not for singing on its own
a clip of `pas` fills a slot as neatly as one of `bravo` and says nothing.
Currently set aside with a `SYL_` prefix.

**Shout**, `aah`. Treated unlike everything else: never pitch-shifted,
never time-stretched, never resynthesised, because a vocoder smooths away
exactly the crack and attack that make it a shout.

**Climax**. A phrase the song peaks on, ranked by pitch and loudness together.
The only place `calculator` is allowed, so it stays a payoff rather than becoming
the texture.

## Filename prefixes in `words/candidates/`

| Prefix | Meaning | Safe for a tool to rename? |
|---|---|---|
| *(none)* | Reviewed by ear. **In the bank.** | **No. Never.** |
| `TODO_` | Cut, no guess as to content | Yes |
| `AI_` | A machine guess, unverified | Yes |
| `SYL_` | A recognised syllable, set aside | Yes |
| `EEE_then__` | A shout plus whatever followed it | Yes |
| `THEN_` | Only what followed a shout | Yes |

None of the prefixes parses as a bank word, so an unreviewed clip is
structurally incapable of reaching the bank however confident a guess looked.

## Modes

**Mode A**. The song has a vocal. Every musical decision is borrowed from it.
The whole tool.

**Mode B**. The song has no vocal. Detected and refused, because with nothing
to borrow the tool would have to invent note, onset and duration against the
backing track, which is composition rather than signal processing. See
`docs/TODO.md`.
