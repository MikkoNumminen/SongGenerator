# Working on LuokkaretkiGenerator

Replaces a song's vocals with sung Finnish word clips, timed and pitched to the
original melody. Everything runs locally on one GPU. No cloud, no paid services,
no vocal synthesis — the words are real recordings and the tool only separates,
analyses, re-pitches, re-times and mixes them.

## Run things this way

The venv is deliberately isolated (torch, demucs and heavy audio deps live
there and must not leak into other projects). Always use it explicitly:

```powershell
.\.venv\Scripts\luokkaretki-generator.exe input\song.mp4          # full run, 7 variants
.\.venv\Scripts\python.exe -m pytest tests\ -q          # 191 tests, ~10s
.\.venv\Scripts\python.exe -m luokkaretki_generator.build_bank    # rebuild the word bank
```

Tests need `PYTHONPATH` pointed at `src` unless the package is installed:
`$env:PYTHONPATH='...\src'`.

## Never do these

- **Never rename or delete anything in `words/candidates/` that has no prefix.**
  Unprefixed clips are hand-reviewed by ear and cannot be regenerated. Prefixed
  ones (`TODO_`, `AI_`, `SYL_`, `EEE_then__`, `THEN_`) are machine-written and
  safe. This rule is enforced structurally: no prefix parses as a bank word, so
  an unreviewed clip cannot reach the bank.
- **Never hardcode a tunable.** Everything adjustable lives in `config.py`,
  grouped by stage, with the reasoning recorded next to the value. If you find
  yourself typing a number into logic, it belongs there instead.
- **Never trust speech recognition on this material.** It was tried three ways
  (whole-source, clip-by-clip, shape-ranked shortlist) and was wrong nearly
  every time on shouted, sung Finnish. It is kept only as a labelling *hint*.
  Identification is done by ear.
- **Never re-separate needlessly.** Stems are cached under `work/<song>/`.
  Separation is by far the slowest stage; everything else is seconds.

## Where the traps are

- **Filenames end up on Windows.** A clip's measured note goes into its name,
  and an unpitched clip once wrote a literal `?`, which is illegal — the write
  threw and an entire source was silently abandoned. Sanitise anything derived
  from measurements before it becomes a path.
- **A clip name is a contract.** `parse_phrase` in `build_bank.py` reads word
  sequences out of filenames. It deliberately refuses names ending mid-word, and
  deliberately accepts a shout spelled any of several ways. Change it carefully;
  the tests spell out the intended edge cases.
- **Whisper is non-deterministic by default.** Its temperature ladder made two
  runs over the same audio return 25 matches and then 3. It is pinned to
  `temperature=0.0` with beam search. Do not remove that.
- **The venv has no Triton.** Whisper falls back to a slower DTW path and warns
  about it. Harmless.

## Reading order

1. `docs/GLOSSARY.md` — what slot, unit, phrase, mimicry and fold mean here.
   These are load-bearing terms; guessing at them will mislead you.
2. `docs/ARCHITECTURE.md` — the pipeline, module by module.
3. `src/luokkaretki_generator/config.py` — every decision that can be tuned, and why.
4. `docs/WORKFLOWS.md` — the recipes for common jobs.
5. `docs/TODO.md` — what is deliberately unfinished, including Mode B.

## Verifying a change

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ -q
.\.venv\Scripts\luokkaretki-generator.exe input\musicHyva.mp4 --rows 0
```

The second is the real check: it prints how many units were placed, how much of
the melody survives, and how far clips had to be shifted. Those numbers move
when behaviour changes, and they are the fastest way to see whether a change did
what you intended.

## The one thing to understand

The tool works because it **steals every musical decision from the original
singer** — when each syllable starts, how long it lasts, what note it lands on —
rather than inventing any of them. That is what makes Mode A tractable and Mode B
(a song with no vocals) hard enough to be deliberately refused. Any change that
starts inventing musical decisions is going the wrong way.
