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

**Syllable**. A fragment of a word (`bra`, `vo`, `me`, `ter`). Kept for
*spelling* words that were never recorded intact, not for singing on its own
a clip of `bra` fills a slot as neatly as one of `bravo` and says nothing.
Currently set aside with a `SYL_` prefix.

**Shout** `aah`. Treated unlike everything else: never pitch-shifted,
never time-stretched, never resynthesised, because a vocoder smooths away
exactly the crack and attack that make it a shout.

**Climax**. A phrase the song peaks on, ranked by pitch and loudness together.
The only place `calculator` is allowed, so it stays a payoff rather than becoming
the texture.

## Playing with the words

**Arrangement**. What gets sung where, for one run: an ordered list of
placements, each naming its words and optionally the exact clip. Written to
`work/<song>/arrangements/` as a file a person can read against the song and
edit. `--arrangement` plays one back. See `docs/DATA-FORMATS.md` for the
format.

**Playfulness level**. How freely the words are rearranged. `conservative`
stays near what was recorded; `wild` invents more orders, spreads wider and
leans harder on the shout and the payoff; `off` is the behaviour from before
any of this existed. One level produces ONE arrangement, which is then
rendered across the whole mimicry ladder. Playfulness and mimicry are separate
questions and deliberately do not multiply: a run writes both levels times
seven rungs, not two arrangements per rung.

**Word role**. The bank's words are not interchangeable, and each has a share
of the song it should have. Weighted per level in `PLAY_LEVELS`.

| Role | Which words | Share of what gets sung |
|---|---|---|
| **core** | named by `PLAY_CORE_WORDS`, else every short word that is neither shout nor payoff | 70-74% conservative, 53-60% wild |
| **crown** | the long words. Rarer, and finish a combination rather than carry one | 4-6% |
| **shout** | `SHOUT_WORDS` | 14-18% conservative, 23-28% wild |
| **payoff** | `CLIMAX_WORDS`, already rationed by the climax machinery | 5-6% conservative, 9-11% wild |
| **extra** | everything else the bank has accumulated | 1-4% |

Left to compete on duration fit alone the shout wins constantly, being a third
of the recordings and short enough for any slot, and the result is a song of
shouting with words in the gaps. Extras are worse: they read as novel, so the
bonus for saying something new reaches for them, and novelty is exactly the
wrong reason to sing a word the song is not about.

**Origin**. How a unit came to exist, from most to least like a real
recording. Ranked, because they are not equal: a whole take carries the
singer's own movement between syllables and an assembled one carries a join
where that movement should be.

| Origin | What it is |
|---|---|
| `recorded` | a clip the singer sang whole |
| `slice` | one word cut out of such a clip, at the boundaries `build_bank` measured. Genuine audio of that word |
| `joined` | real words crossfaded into an order nobody sang |
| `spelled` | a word assembled out of syllable fragments |

Slicing and spelling exist to reach sequences nobody recorded, not to replace
what was recorded. In practice `spelled` should be near zero and appears only
when nothing recorded will do.

**Chant**. The same thing said several times running, on purpose. Distinct
from the monotony `repeat_penalty` exists to stop, which is one clip quietly
winning every slot because it happens to fit best. A chant is chosen, bounded
by `chant_max`, and ends.

**Coverage**. The rule that every word in `PLAY_REQUIRED_WORDS` appears
somewhere, and that the shout-into-payoff pairing appears at least once when
the bank holds one. Checked after an arrangement is drawn; a failure is
redrawn from a derived seed. Coverage outranks every weight above: when the
weights are what is holding a required word out, the weights are relaxed and
then dropped, because a share is a preference and a missing word is a broken
rule.

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
