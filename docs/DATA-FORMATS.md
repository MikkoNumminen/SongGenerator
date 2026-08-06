# Data formats

Every intermediate stage lands on disk as JSON, so state can be inspected
without re-running anything. Separation takes minutes; reading a file does not.

---

## `work/<song>/analysis.json`

What the original singer did. Written by `analysis.py`.

```jsonc
{
  "sr": 44100,
  "duration_s": 148.584,
  "tempo_bpm": 92.3,
  "beats_s": [0.51, 1.16, ...],

  "notes": [
    {
      "i": 0,                  // index
      "onset_s": 12.44,
      "offset_s": 12.71,
      "dur_s": 0.27,
      "midi": 67.3,            // unrounded; stage 4 shifts to the real pitch
      "midi_q": 67,            // nearest semitone, for reporting
      "hz": 392.4,
      "conf": 0.91,            // mean periodicity across the note
      "rms_db": -18.2,         // used to find the song's peaks
      "phrase": 3,
      "source": "both"         // "pitch" | "onset" | "both" | "start"
    }
  ],

  "phrases": [
    { "i": 3, "start_s": 12.44, "end_s": 15.02, "n_notes": 9 }
  ],

  "f0": {                      // omitted with --slim
    "hop_s": 0.01,
    "hz": [0.0, 392.4, ...],   // 0.0 where unvoiced
    "voiced": [false, true, ...]
  }
}
```

`source` records which detector opened each note, and is worth reading when
timing looks wrong. A pitch change and an energy onset have different blind
spots. Neither alone sees both a slurred note change and two syllables sung on
one pitch. So a run consisting only of `"pitch"` means the onset detector has
stopped contributing.

These are **notes, not slots**. Slots are notes after cleanup, and cleanup
happens in stage 3 so this file stays a faithful record of what was heard.

---

## `words/words.json`

The bank. Written by `build_bank.py`.

```jsonc
{
  "aah-calculator_1.wav": {
    "words": ["aah", "calculator"],
    "variant": "1",
    "source_clip": "aaahcalculator.wav",
    "duration_s": 1.6437,
    "midi": 55.2,
    "note": "G3",
    "syllables": 5,
    "word_syllables": [1, 4],
    "word_start_syllable": [0, 1],   // which syllable each word begins on
    "syllable_bounds_s": [0.42, 0.71, 0.98, 1.29],
    "syllable_midi": [57.1, 53.7, 53.2, 53.4, 52.9]
  }
}
```

`syllable_bounds_s` has `syllables - 1` entries. The split points inside the
clip. They are what make a multi-syllable word land its syllables on the
melody's note onsets instead of drifting across them.

**Hand-editable.** Add `"hand_corrected": true` to a clip and a later rebuild
keeps your boundaries instead of re-detecting them.

`syllable_midi` is measured per syllable rather than per clip, so a clip with
internal melody does not carry that movement along and land later syllables off
their targets.

---

## `work/<song>/arrangements/<seed>-<level>.arr`

What gets sung where, for one run. Written by `arrange.py` on every render,
never overwritten, so an older arrangement stays reproducible.

```
# SongGenerator arrangement
#   song    rocketman_bluegrass
#   bank    words_hq3.std
#   level   wild
#   seed    543686
#
#   at      when it starts. The song decides the slots; this locates the line.
#   x<n>    how many melody slots it covers.
#   =<s>    how long it is given, in seconds. Optional.
#   words   what is sung there, in order. This is the part to edit.
#   [take]  which recording. Delete it and the best fit is chosen for you, or
#           the words are built out of slices if nothing recorded says them.

phrase 1
   0:02.57  x8  =2.37  pillu paska pornolehti   [pillu-paska-pornolehti_1.wav]
   0:04.94  x6  =1.96  perse pillu perse        [perse-pillu-perse_1.wav]
   0:07.26  x1  =0.35  eee                      [eee_then__muumit__50.76.wav]
```

`phrase N` counts the phrases the mapper sings to, which are the detector's
phrases after cleanup has merged blips, split held notes and capped anything
too long to be one phrase. They do not line up with the `phrase` field on a
note in `analysis.json`, and neither is wrong: that file records what was
heard, this one records what the tool sang to.

The span is written because it cannot always be derived: a word may be held
across a leftover slot, which widens what it is given without adding a note to
land on. Omit it in a hand-written file and the slots decide.

**Two-way on purpose.** The tool writes it and a person can edit it and feed
it back:

```powershell
.\.venv\Scripts\song-generator.exe input\song.mp3 --arrangement <path>
```

Replay rebuilds the placements from the file rather than replanning, so an
edited file produces what it says and nothing else. Change the words on a
line, delete a line, or delete a `[take]` to let the tool pick the recording.
A sequence nobody recorded is assembled from slices on demand, so any order of
the bank's words can be asked for, whether the generator would have chosen it
or not. That is what makes this the format a "supply your own lyrics" mode
would read, without that mode existing yet.

Refused rather than guessed: a word the vocabulary does not have, a line that
cannot be anchored to a slot, a sequence the bank cannot say, and a seed that
does not read as a number. The seed is load-bearing on replay, since the pool
of slices and invented orders is rebuilt from it; substituting a default would
play a different arrangement under this file's name. A silently misaligned or
dropped word would still play, which is why none of them are tolerated. A file
with no seed line reads as seed 0.

Each level of a run writes its own file, so a run produces two.

---

## `words_hq.std/standardized.json`

How each derivative was made, and what it was made from. Written by
`standardize.py`.

```jsonc
{
  "format": 1,
  "params_sha256": "9f2c...",     // every threshold and target, as one hash
  "shout_mode": "offset",
  "source_dir": "words_hq",
  "clips": {
    "aah-calculator_1.wav": {
      "source_sha256": "4a81...", // of the recorded clip's bytes
      "source_bytes": 302444,
      "trim_head_s": 0.012,       // what syllable_bounds_s was shifted by
      "trim_tail_s": 0.43,
      "lufs_before": -24.8,
      "lufs_after": -20.0,
      "gain_db": 4.8,
      "ceiling_limited": false,   // true = could not reach target without clipping
      "levelled": true,           // false = a shout under shout_mode "as_recorded"
      "group": "shout"
    }
  }
}
```

Staleness is decided by hashing, never by names or timestamps: a clip re-cut to
the same length under the same name is exactly the case a naming convention
cannot see. `params_sha256` covers the thresholds too, so editing one in
`config.py` makes every derivative read as stale even though no source moved.

```powershell
.\.venv\Scripts\python.exe -m song_generator.standardize --check
```

Reports **stale** (source changed), **new** (source has no derivative),
**missing** (manifest claims one that is not on disk), **orphan** (derivative
whose source is gone) and **drifted** (parameters moved, so all of them are).
Exits non-zero unless everything matches, so it can gate a build.

The tier alongside it is an ordinary bank: `words.json` in the same directory,
with `duration_s` and `syllable_bounds_s` rewritten to match the trimmed audio.
`--words-dir words_hq.std` reads it like any other.

---

## `work/<song>/detect.json`

The Mode A / Mode B verdict and the numbers behind it.

```jsonc
{
  "vocal_present": true,
  "vocal_lufs": -22.4,
  "mix_lufs": -19.0,
  "rel_lu": -3.4,          // vocal relative to mix; the robust measure
  "voiced_frac": 0.494,
  "f0_backend": "torchcrepe",
  "reasons": []            // populated only when refused
}
```

Both tests must pass. They fail on different things: loudness catches a
near-silent stem, voicing catches one that is loud but full of instrumental
bleed. `reasons` says which line was crossed, so a misclassification is
diagnosable rather than mysterious.

---

## `words/labels.tsv`

Optional alternative to renaming files. Tab-separated, parsed as **utf-8-sig**
because Notepad and PowerShell both write a BOM.

```
word	variant	start	end	syl	pitch	candidate
bravo		0.090	0.480	2	F3	c01.wav
?		4.060	4.900	5	F#3	c06.wav
```

`?` or `-` skips a row. Lines beginning `#` are comments.

`variant` becomes part of the output filename (`<word>_<variant>.wav`), so it
may only contain the letters `a-z`, digits, `_` and `-`. Empty is fine; a
counter is substituted. Anything else, a slash or `..` in particular, is
refused with the line number, because it would let a hand-edited row write
outside the bank directory. The letter range is meant literally and excludes
accents, so `hä` is refused: a bank filename has to survive every tool that
reads it.

It is lowercased on the way in, like the word column. Windows filenames are
case-insensitive, so `Low` and `low` name one file, and without folding them
together two rows would validate, neither would trigger the collision counter,
and the second clip would replace the first while `words.json` claimed both.

---

## Filename conventions

Filenames carry meaning in `words/candidates/`, and the parsing is real code
`parse_phrase` in `build_bank.py`, with the edge cases pinned by tests.

```
TODO_2syl__kirby2__c07__1.42-1.98.wav
└──┘ └──┘  └────┘  └─┘  └────────┘
 │    │      │      │        └─ seconds in the source
 │    │      │      └────────── candidate index
 │    │      └───────────────── source, minus its shared prefix
 │    └──────────────────────── best guess, or measured syllable count
 └───────────────────────────── review state
```

An unprefixed name is a claim about content: `bravo1`, `tangodelta`,
`aahcalculator`. See `docs/GLOSSARY.md` for the prefix table.

**No prefix parses as a bank word.** That is what makes it structurally
impossible for an unreviewed clip to reach the bank, however confident a machine
guess looked.

---

## `--json` output

Every run accepts `--json` for a machine-readable summary instead of the report:
mode, tempo, note and phrase counts, median note length, and the path to
`analysis.json`.
