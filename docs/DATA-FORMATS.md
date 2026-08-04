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
    "source_clip": "eeeicalculator.wav",
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
`eeecalculator`. See `docs/GLOSSARY.md` for the prefix table.

**No prefix parses as a bank word.** That is what makes it structurally
impossible for an unreviewed clip to reach the bank, however confident a machine
guess looked.

---

## `--json` output

Every run accepts `--json` for a machine-readable summary instead of the report:
mode, tempo, note and phrase counts, median note length, and the path to
`analysis.json`.
