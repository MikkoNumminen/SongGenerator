# luokkaretki

Takes a song, throws away the singer, and puts a small bank of sung Finnish
words back in their place — on the same notes, at the same moments.

Runs entirely locally. No paid services, no cloud, no vocal synthesis: the
words are real recorded sung clips, and the tool only separates, analyses,
re-pitches, re-times and mixes them.

## How it works (Mode A)

The trick is to steal every musical decision from the original singer rather
than invent any of them:

1. **Separate** the song into vocal and instrumental (Demucs).
2. **Analyse the original vocal before discarding it** — the melody (pitch over
   time) and the timing (where each sung syllable starts and how long it runs).
3. **Map the word clips onto those same slots**, and pitch-shift each to the
   melody note it landed on, formant-corrected so it still sounds like a person.
4. **Mix** the word track over the instrumental, level-matched, out as mp3.

A song with no vocals is **Mode B**, which is detected and refused rather than
botched — see [docs/TODO.md](docs/TODO.md) for why.

## Status

Commit 1 of 4. Separation, caching and mode detection work; the tool currently
outputs the **instrumental bed**. Word placement lands in commit 3 and pitch
shifting in commit 4. Build order and progress: [docs/TODO.md](docs/TODO.md).

## Install

Windows, Python 3.11, an NVIDIA GPU, and `ffmpeg` on PATH.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
.\.venv\Scripts\python.exe -m pip install -e .
```

The venv is deliberately its own island — this drags in torch and a pile of
heavy audio dependencies, and none of it should be anywhere near another
project's environment.

Optional, for the better separator:

```powershell
.\.venv\Scripts\python.exe -m pip install "audio-separator[gpu]"
```

## Usage

```powershell
.\.venv\Scripts\luokkaretki.exe input\song.mp3
.\.venv\Scripts\luokkaretki.exe input\song.mp3 -o output\meme.mp3 --separator roformer
.\.venv\Scripts\luokkaretki.exe input\song.mp3 --json
```

Stems are cached under `work/<song>/`, so re-running only pays for separation
once. `--force` separates again.

Exit codes: `0` success, `2` error, `3` Mode B (no vocals, unsupported).

## Tuning

Every knob lives in one place: [`src/luokkaretki/config.py`](src/luokkaretki/config.py),
grouped by pipeline stage. Shift cap, level balance, the syllable-mapping rule,
beat subdivision, detection thresholds — all there, none of it buried in logic.

## The word bank

Individually recorded sung clips in `words/`, lifted from a Finnish film's
singing scene: *paska*, *perse*, *pillu*, *pornolehti*, *paviaani*. Where the
scene sings a word at more than one pitch, several versions are kept so the
tool can pick the closest and shift it less.

Usefully, every word has an **even** syllable count (2 or 4), so any phrase with
an even number of slots is filled exactly and an odd one leaves precisely one
slot over — which is why `ODD_SLOT_POLICY` only has one case to handle.

## Separator choice

`demucs` (htdemucs_ft) is the default. `roformer` (Mel-Band Roformer) scores
noticeably higher on vocals and is worth A/B-ing: separation quality sets the
ceiling for everything downstream, since the vocal stem drives melody and
timing extraction, and any vocal residue left in the instrumental sits audibly
under the replacement words.
