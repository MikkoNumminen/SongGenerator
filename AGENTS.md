# Working on SongGenerator

Replaces a song's vocals with short sung word clips, timed and pitched to the
original melody. Everything runs locally on one GPU. No cloud, no paid services,
no vocal synthesis. The words are real recordings and the tool only separates,
analyses, re-pitches, re-times and mixes them.

## Run things this way

The venv is deliberately isolated (torch, demucs and heavy audio deps live
there and must not leak into other projects). Always use it explicitly:

```powershell
.\.venv\Scripts\song-generator.exe input\song.mp4              # full run, both levels x 7 rungs
.\.venv\Scripts\python.exe -m pytest tests\ -q                        # the whole suite, ~50s
.\.venv\Scripts\python.exe -m song_generator.build_bank        # rebuild the word bank
.\.venv\Scripts\python.exe -m song_generator.doctor            # diagnose anything
```

Tests need `PYTHONPATH` pointed at `src` unless the package is installed:
`$env:PYTHONPATH='...\src'`.

## Never do these

- **Never merge anything without being told to, for that specific merge.**
  Branching, committing, pushing and opening a pull request are ordinary work.
  Merging is not, and permission for one merge is not permission for the next.
  A green suite is not permission either. See [CLAUDE.md](CLAUDE.md) for the
  full rule; it outranks anything an assistant arrives with.
- **Never write more than two renderings for a song.** One conservative and
  one wild, both at full mimicry, and nothing else. The pipeline's own default
  is the seven-rung mimicry sweep, which is fourteen full passes over the audio
  and three hours for a batch; the lower rungs are not listened to, and one song
  arrives as fourteen near-identical rows in a library holding hundreds. At a
  terminal, comparing rungs by ear is the point, so `--mimicry` still takes any
  value. Everywhere else the rung is 1.0. A run submitted through the site
  cannot produce the ladder: `SubmitBody.mimicry` defaults to it, and
  `tests/test_jobs.py` fails if that default ever moves. Anything new that
  starts a render inherits this rule; it is not a preference, and it has been
  stated twice.
- **Never commit audio.** Not source material, not rendered output, not the
  word samples. All of it is excluded by `.gitignore` on extension, so it is
  refused wherever it lands. The repo is the tool, not the media.
- **Never rename or delete anything in `words/candidates/` that has no prefix.**
  Unprefixed clips are hand-reviewed by ear and cannot be regenerated. Prefixed
  ones (`TODO_`, `AI_`, `SYL_`, `EEE_then__`, `THEN_`) are machine-written and
  safe. This is enforced structurally: no prefix parses as a bank word, so an
  unreviewed clip cannot reach the bank.
- **Never hardcode a tunable.** Everything adjustable lives in `config.py`,
  grouped by stage, with the reasoning recorded next to the value. If you find
  yourself typing a number into logic, it belongs there instead.
- **Never trust speech recognition on this material.** It was tried three ways
  (whole-source, clip-by-clip, shape-ranked shortlist) and was wrong nearly
  every time on shouted singing. It is kept only as a labelling *hint*.
  Identification is done by ear.
- **Never point a tool's output at a bank somebody curated by hand.** The
  clips in a bank get renamed by ear and added to over time, and none of that
  is regenerable. `recut_bank --out` defaulted to `words_hq` from when it
  created that directory, and would have written over eighteen hand-named
  recordings; it now refuses unless told otherwise, and checks again at write
  time, since a clip renamed into the folder mid-run is the same hand work.
  Any new tool that writes clips needs the same refusal.
- **Never re-separate needlessly.** Stems are cached under `work/<song>/`.
  Separation is by far the slowest stage; everything else is seconds.

## Where the traps are

- **Filenames end up on Windows.** A clip's measured note goes into its name,
  and an unpitched clip once wrote a literal `?`, which is illegal, the write
  threw and an entire source was silently abandoned. Sanitise anything derived
  from measurements before it becomes a path.
- **A clip name is a contract.** `parse_phrase` in `build_bank.py` reads word
  sequences out of filenames. It deliberately refuses names ending mid-word, and
  deliberately accepts a shout spelled any of several ways. Change it carefully;
  the tests spell out the intended edge cases.
- **Speech recognition is non-deterministic by default.** Its temperature ladder
  made two runs over the same audio return 25 matches and then 3. It is pinned
  to `temperature=0.0` with beam search. Do not remove that.
- **The venv has no Triton.** The recogniser falls back to a slower DTW path and
  warns about it. Harmless.
- **A wav that exists is trusted.** The stale-cache checks only test
  `is_file()`, and `recut_bank` overwrites curated clips in place, so an
  interrupted write must never leave a truncated file at the final name.
  `write_wav` writes to a temp file beside the destination and renames it into
  place. Any new code that writes a wav goes through it, never through
  `sf.write` straight onto the final path. The temp is named `.<clip>-XXXX.tmp`
  and is removed on any failure, but a process killed outright leaves one
  behind. It is hidden from every `*.wav` glob by that suffix, which also means
  nothing will ever report it: a stray `.tmp` in a bank directory is safe to
  delete.
- **An index entry is a claim that the file exists.** `load_bank` reads
  `words.json` alone and nothing re-checks the directory, so an entry for a
  clip that was never written fails at render time, and a dropped entry
  silently removes the word from every later render. A tool that decides not
  to write a clip must drop its entry in the same run and say which clips
  that excluded; `recut_bank` shows the shape, including the `build_bank`
  command it prints as the fix.
- **A `finally` that writes a file also writes it while unwinding from a
  failure**, straight over whatever a person put there. `mine_words` used to
  replace a hand-edited `labels.tsv` that way when a re-run died mid-cut; its
  failure path now writes `labels.partial.tsv` beside the file instead, and
  numbers later partials rather than clobbering earlier ones. Any new unwind
  path that writes where hand work can live needs the same sidestep.
- **Every render needs the GPU, not just the first.** `analysis.json` is
  written on every run and never read back, so melody extraction re-runs each
  time. It is torchcrepe: one song took 167 seconds with the card and over nine
  minutes without it. Sparing the GPU by passing `--device cpu` therefore makes
  a batch slower by an order of magnitude rather than politer. To leave room
  for other GPU work, cap the share with `GPU_MEMORY_FRACTION` instead.
- **Running renders in parallel is a memory decision, not a core count.** One
  render is single-threaded and holds about 3.5 GB; eight at once against 19 GB
  free exhausted RAM and the swapping pinned the disk until the machine had to
  be restarted. The full list of what bites, including the `xargs` pool that
  outlives the shell that started it, is in `docs/WORKFLOWS.md` under "Make
  many tracks at once".
- **What a segment is asked to do is not what it sounds.** `out_dur_s` is what
  the planner allotted; what actually sounds is
  `min(out_dur_s, src_dur_s * clamp_stretch(...))`, because
  `TIME_STRETCH_RANGE` caps how far a clip may be stretched, and now also
  whatever `sustain_to_s` holds past that. Measuring timing from
  `out_start_s + out_dur_s` therefore measures the request, not the result. It
  reported silence inside words at 37% of a song's words when the true figure
  was 67%, and the wrong number was quoted before anyone caught it. Any
  measurement of what a render sounds like has to compute the sounding length.
- **Check that a deploy happened. Do not infer it from a green build.** A front
  end was rewritten, reviewed and merged with everything green, and the site
  went on serving a build six commits old. It was published by Azure DevOps at
  the time, and its trigger's path filter read `web/*`, which is not something
  this repository can settle:
  Microsoft documents `*` as not crossing a directory separator, which would
  exclude everything under `web/src`, and older servers as treating a trailing
  `*` as the directory itself, which would include it. No filter reads that way
  any more: the Azure trigger is off and the workflow that publishes filters on
  `web/**`, which GitHub documents unambiguously. What is established is the
  correlation: all five deploys this site has ever had came from commits that
  also touched `azure-pipelines.yml`, the filter's other entry, and none from a
  change to the site alone. What is **not** established is that the filter was
  the whole cause, because the merge in question did add `web/DESIGN.md`,
  directly inside `web`, which every reading of the old filter matches. The
  pipeline had stopped producing runs at all, for a reason only its own run
  list could have shown, so publishing moved to
  `.github/workflows/deploy.yml`, which is unmetered here and next to the
  code. That workflow now ends by asking the site what it is serving and fails
  if the answer is not the build it just made. Ask the same thing by hand
  whenever you are wondering:
  `curl.exe -s <site>/ | Select-String -Pattern 'main-\w+\.js'` names the
  hashed bundle, and `outputHashing` is `all`, so it changes with every build.
- **A green front-end suite says nothing about what a visitor sees.** The web
  tests assert component state, and nothing in them renders at a phone's width,
  presses Tab, or looks at a first paint. Three defects passed the suite for
  exactly that reason: a top bar that scrolled the page sideways on a phone, a
  skip link that never moved focus because its target could not hold it, and a
  stored light theme that flashed dark on every load. Check a front-end change
  in a browser, at a narrow width, with the keyboard, in both themes. See
  `docs/AI-FIRST.md`, dimension 12.
- **A float WAV is not a pure function of its samples.** libsndfile writes a
  PEAK chunk holding the wall-clock time of the write, at byte 60. Two runs
  producing bit-identical audio therefore produce files that differ by that one
  byte whenever they straddle a second boundary. Never assert that audio is
  reproducible by comparing file bytes; decode and compare the samples. This
  cost a debugging session as a test that failed about twice in a hundred runs
  and looked like non-determinism in the code.

## Keep the docs current

The aesthetic decisions in this tool are not recoverable from the code. A
number in `config.py` says what the tool does; it does not say that the shout
was taking a third of the song and had to be charged for it, or that a word
assembled from syllables carries a join where the singer's own movement should
be. Those were decided by listening, and the next person to touch a knob will
undo them by accident if the reasoning is not written down.

So when behaviour changes, update the docs in the same commit:

| Changed | Update |
|---|---|
| A new module | `docs/ARCHITECTURE.md` (a test enforces this one) |
| A term worth knowing | `docs/GLOSSARY.md` |
| A file written to disk | `docs/DATA-FORMATS.md` |
| How to do something, or a knob worth turning | `docs/WORKFLOWS.md` |
| A trap that cost time once | this file |

Measured claims belong in the docs with their numbers, since "the shout was
too loud" ages badly and "the shout was 34% of what got sung against the core
words' 29%" does not.

## Reading order

1. `docs/GLOSSARY.md`. What slot, unit, phrase, mimicry and fold mean here.
   These are load-bearing terms; guessing at them will mislead you.
2. `docs/ARCHITECTURE.md`. The pipeline, module by module.
3. `src/song_generator/config.py`. Every decision that can be tuned, and why.
4. `docs/WORKFLOWS.md`. The recipes for common jobs.
5. `docs/TODO.md`. What is deliberately unfinished, including Mode B.

## Verifying a change

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ -q
.\.venv\Scripts\song-generator.exe input\musicHyva.mp4 --rows 0
```

The second is the real check: it prints how many units were placed, how much of
the melody survives, and how far clips had to be shifted. Those numbers move
when behaviour changes, and they are the fastest way to see whether a change did
what you intended. `doctor` explains anything that looks wrong.

## The one thing to understand

The tool works because it **steals every musical decision from the original
singer**, when each syllable starts, how long it lasts, what note it lands on
rather than inventing any of them. That is what makes Mode A tractable and Mode B
(a song with no vocals) hard enough to be deliberately refused. Any change that
starts inventing musical decisions is going the wrong way.
