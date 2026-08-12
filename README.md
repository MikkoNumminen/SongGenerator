# SongGenerator

Takes a song, throws away the singer, and puts a small bank of sung word clips
back in their place, on the same notes, at the same moments.

Runs entirely locally on one GPU. No cloud, no paid services, no vocal
synthesis: the words are real recordings, and the tool only separates,
analyses, re-pitches, re-times and mixes them.

**Web player:** <https://mikkonumminen.dev/songgenerator>. Sign in with Google to
play what has already been rendered; the administrator account also grants and
revokes access, from the Admin Panel. The rendering still happens on
the local GPU, so the player answers only while that machine is on.

```powershell
.\.venv\Scripts\song-generator.exe input\song.mp4
```

One command writes fourteen versions into `output/<song>/<bank>/`. Two arrangements
of the words, one tidy and one that mixes them up harder, and each rendered
from words that ignore the tune completely through to words that sing it as
closely as the song allows. Pick by ear; the right one varies by song.

## How it works

The trick is to **steal every musical decision from the original singer** rather
than invent any:

1. **Separate** the song into vocal and instrumental (Demucs).
2. **Analyse the original vocal before discarding it**. The melody, and where
   each sung syllable starts and ends.
3. **Arrange words onto those same slots**, pitch-shifted to the notes the
   singer hit, formant-corrected so they still sound like a person. The bank is
   recorded phrases rather than single words, so a phrase is cut back into its
   words where a sequence nobody sang is wanted.
4. **Mix** over the instrumental, level-matched, out as mp3.

A song with no vocals is **Mode B**: detected and refused rather than botched,
because with nothing to borrow the tool would have to invent note, onset and
duration against the backing track. That is composition, not signal processing.
See [docs/TODO.md](docs/TODO.md).

## There is a web front end too

An **Angular 22 + TypeScript** application in [`web/`](web/), talking to a
**FastAPI** edge in [`api/`](api/): paste a link, pick a bank, watch the run
through its stages, and read what was made before.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:build --factory --app-dir api
cd web ; npm install ; npm start
```

Two things shape it more than anything else.

**The machine is often switched off.** The pipeline needs a GPU, so it runs on
a desktop rather than in the cloud, and that desktop is not always on. "Not
answering" is therefore a normal state rather than a fault, and it is a state
of its own throughout: told apart from a real error at the one place that
classifies failures, and rendered in wording that does not apologise for a
computer being turned off.

**It is never openly usable.** The pipeline takes an arbitrary link and spends
a GPU on it, so every route but the health check is behind Google sign-in and
an allowlist of named accounts. The browser only carries a token; the check
that counts happens on the server.

The TypeScript interfaces are generated from the edge's own OpenAPI schema, and
tests fail if either half drifts from the other. See
[web/ARCHITECTURE.md](web/ARCHITECTURE.md) for the shape and what it leaves
out.

The site is hosted on **Azure Static Web Apps**, declared in **Bicep** and
published by an **Azure DevOps** pipeline, all on free tiers. Azure Functions
and a managed database are deliberately not used, because the work needs a GPU
and the job history has to sit beside it. [docs/AZURE.md](docs/AZURE.md) gives
the measurements behind both decisions.

## Documentation

| | |
|---|---|
| [AGENTS.md](AGENTS.md) | Start here if you are an agent. What to run, what never to touch. |
| [docs/GLOSSARY.md](docs/GLOSSARY.md) | Slot, unit, phrase, mimicry, fold. Load-bearing terms. |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | The pipeline, module by module. |
| [docs/WORKFLOWS.md](docs/WORKFLOWS.md) | Recipes: add a song, extend the bank, tune density. |
| [docs/DATA-FORMATS.md](docs/DATA-FORMATS.md) | Every file the tool writes, field by field. |
| [docs/TODO.md](docs/TODO.md) | What is deliberately unfinished. |
| [docs/AI-FIRST.md](docs/AI-FIRST.md) | How legible this repo is, scored against a written rubric. |
| [docs/AZURE.md](docs/AZURE.md) | What runs in Azure, what does not, and the measurements behind each decision. |
| [web/ARCHITECTURE.md](web/ARCHITECTURE.md) | How the Angular front end is put together, and what it deliberately leaves out. |
| [src/song_generator/config.py](src/song_generator/config.py) | Every tunable, with the reasoning behind its value. |

## Install

Windows, Python 3.11, an NVIDIA GPU, `ffmpeg` on PATH.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
.\.venv\Scripts\python.exe -m pip install -e .
```

The venv is deliberately its own island. This pulls in torch, demucs and a pile
of heavy audio dependencies, and none of it should be near another project.

Optional extras: `audio-separator[gpu]` for the better separator,
`openai-whisper` for labelling hints.

## The dial that matters

**Mimicry**, how much of the original melody survives in the result, 0 to 1.

It is not the same as how many words get shifted. A word too far from its target
is moved by whole octaves instead of stretched, so it sings the right note *name*
in the wrong octave: recognisably the tune, still audibly wrong. Such a syllable
counts for part of a mimicry point, not a whole one.

That is why every song has a **ceiling**. One whose melody ranges far above the
bank's own register cannot sound fully sung however hard it is pushed, and
that ceiling is reported on every run. It is also why the same setting sounds
different on two songs, and why the tool solves for whatever shift a particular
song needs to reach the mimicry you asked for.

More clips at *new pitches* raise the ceiling. More clips at pitches you already
have do not.

## The other dial

**Playfulness**, how freely the words are rearranged. Separate from mimicry,
and both are rendered every run: two arrangements across seven mimicry
settings, fourteen files, pick by ear.

`conservative` keeps close to what was recorded. `wild` invents more orders,
repeats itself more, and leans harder on the shout. Neither is a quality
setting; they are two different jokes.

Every run draws a new arrangement, so running the same song three times gives
three to choose between. Each is written to `work/<song>/arrangements/` as a
file you can read against the song, edit, and feed back with `--arrangement`
to get that take again or a changed one.

Which words carry a song is a property of the recordings rather than of the
tool, so the bank declares it. A handful of words carry it, a long word is
rarer and finishes a combination, and the shout is seasoning. Left to compete
on how well a clip fills the time, the shout wins constantly, because it is
short enough for any slot.

## Bring your own audio

**No audio ships with this repo, by design.** The clips it was built against
are someone else's recordings and the test songs are commercial releases. Fine
to hold locally, not fine to redistribute. `.gitignore` excludes all of it.

So a fresh clone has the tool and none of the material. To use it you supply:

- **songs** to convert, in `input/`. Either copy them in, or fetch one
  straight from a page address with
  `python -m song_generator.fetch <url>`, which keeps the video and records
  where it came from.
- **source video or audio** to cut word clips from, anywhere on disk

Then follow [docs/WORKFLOWS.md](docs/WORKFLOWS.md) to build a bank. Nothing
about the pipeline is specific to these particular words, `WORD_SPELLING` and
`WORD_SYLLABLES` in `config.py` define the vocabulary, and any set of short
sung clips will work.

## The word bank

A bank is a folder of short sung clips plus an index describing each one. The
vocabulary is entirely yours: `WORD_SYLLABLES` and `WORD_SPELLING` in
`config.py` define it, and the pipeline knows nothing else about the words.

The example vocabulary shipped in `config.py` is `bravo`, `tango`, `delta`,
`kilometer`, `calculator` and the shout `aah`. It exists to make the worked
examples in these docs concrete. Replace it with whatever you record. Two and
four syllable words plus a one syllable shout is a useful shape, because an even
syllable count fills a phrase of slots exactly and the odd shout fills whatever
is left over.

Multi-word clips are worth more than their parts. A clip holding two words also
holds the singer's own transition between them, and a transition cannot be
rebuilt by butting two recordings together.

**There can be more than one bank, and they need not behave alike.**
`--bank` picks between the ones `BANKS` in `config.py` names, and each renders
into its own folder so two banks never overwrite each other's work.

A bank may also declare how it wants to be sung, by dropping a `bank.json`
beside its clips. That file can choose a placement strategy per level, override
the playfulness knobs for that bank alone, refuse to let its clips be cut into
syllables, and set how loud it sits against the instrumental. **A bank that
declares nothing behaves exactly as it always did**, which is what makes the
whole thing safe to add to a bank you are happy with.

The strategies are `arranged`, which chooses words to fit the tune and is what
everything above describes, and `sequence`, which replays a bank's clips in the
order they were recorded and loops when the song outlasts them. `sequence`
suits a bank cut from speech, where the order carries the meaning and there is
no vocabulary to choose from. `docs/DATA-FORMATS.md` gives the file's shape.

Two clips get special handling, and both are worth understanding before you
change them.

**A shout is never pitch-shifted, time-stretched or resynthesised.** Its
character is the attack and the strain, which is exactly what a vocoder smooths
away. Processed like a sung note it comes back on the right pitch and no longer
sounds like a shout. In the example vocabulary that is `aah`; the setting is
`SHOUT_WORDS`.

**One word is allowed only at the song's peaks.** Phrases are ranked by pitch
and loudness together, and this word is refused everywhere else, so it stays a
payoff rather than becoming the texture. In the example vocabulary that is
`calculator`; the setting is `CLIMAX_WORDS`.

## Status

All four build stages are done: separation and mode detection, melody and timing
extraction, word mapping, and formant-corrected pitch shifting. 624 tests.

The HTTP edge and the Angular front end are built and carry their own suites.
Neither is deployed: that needs a Google client id and somewhere to host static
files, both of which are decisions rather than code. Listening to a finished
render still means going to the machine that made it, because the edge
deliberately serves no audio yet.

Mode B remains deliberately unimplemented.
