# Workflows

Recipes for the jobs that actually come up. Every command assumes the repo root
and the project's own venv.

---

## Make a track from a song

```powershell
.\.venv\Scripts\song-generator.exe input\song.mp4
```

Writes **fourteen** mp3s to `output/`: both playfulness levels, and for each,
seven mimicry settings from 0.00 (words ignore the tune entirely, clashing,
and funny for it) to 1.00 (sings the melody as closely as the song allows).

```
output/song/song.conservative.mim0p00.mp3 ... mim1p00.mp3
output/song/song.wild.mim0p00.mp3         ... mim1p00.mp3
```

Each song gets its own folder. Fourteen files a run across a dozen songs is
nearly two hundred in one directory, sorted by name, with every song's levels
and rungs interleaved. The song name stays in the filename too, so a file
dragged out of its folder still says what it is.

Both levels every time, because which is funnier is a listening decision and a
run that produced one of them has not finished the job. Pick by ear; there is
no correct value for either dial, and the right one varies by song.

Every run draws a new arrangement, so running the same song three times gives
three different takes to choose between. Each is written to
`work/<song>/arrangements/` and the path is printed, which is how a take that
turned out well is brought back.

First run on a song pays for separation (~0.45x realtime). Every later run on
the same song reuses the cached stems.

Rendering both levels costs about 50 seconds of resynthesis on a 2.5 minute
song, since each arrangement is resynthesised separately. The seven mimicry
settings within a level are nearly free, because they are a selection over the
same shifted set. `--play conservative` halves the time when only one level is
wanted.

**Useful flags**

| Flag | Effect |
|---|---|
| `--mimicry 0.45` | One file at one setting instead of the sweep |
| `--play wild` | One level instead of both |
| `--arrangement <path>` | Replay a saved arrangement exactly, or an edited one |
| `--bank chaos` | Sing with every candidate clip, identity ignored |
| `--seed 42` | Fix the arrangement seed; otherwise a new one each run |
| `--raw-clips` | Ignore the standardised tier, sing the recordings as they are |
| `--no-shift` | Words at their own recorded pitch |
| `--rows 30` | Print more of the extracted note table |
| `--json` | Machine-readable summary |

---

## Fetch a song from the web

```powershell
.\.venv\Scripts\python.exe -m song_generator.fetch "https://example.com/watch?v=abc123"
```

Lands in `input\<slug>.mp4`, best video plus audio merged, named by the same
slug the renderer would derive, so the filename on disk is already the key the
whole tool uses. Then render it as usual; the renderer never takes a URL
itself, because the network stays out of the render path on purpose. A render
must not be able to fail because a site changed.

The video is kept at the best resolution the site holds, not just the audio,
because the plan for a rendered song is to cut the original music video to fit
it. Several early songs were downloaded as convenience files at 426x238 and
cannot be cut into anything.

The origin is recorded twice: embedded in the file itself as the `comment`
tag, where `ffprobe` recovers it as long as you know which tag to read, and
as a row in `input\SOURCES.md`, the
gitignored index of where every song came from. See `docs/DATA-FORMATS.md`
for its shape. Songs that arrived before this command exist have no recorded
address; fetching does not fix history, it stops the gap growing.

A file that is already there is reported and left alone: no overwrite, no
`(1)` duplicate. Delete it first to fetch it again. The exception is when
`input\SOURCES.md` already records a different address for that name, which
means two titles slugified to the same slug; the fetch then warns on stderr,
records nothing and exits nonzero, because deleting the file would lose the
song the index describes. `--json` prints the same
fields the `fetch()` function returns, and `--out` redirects everything,
index included, somewhere other than `input\`.

---

## Make many tracks at once

```powershell
.\.venv\Scripts\python.exe -m song_generator.batch "input\*.mp4"
.\.venv\Scripts\python.exe -m song_generator.batch "input\*.mp4" --mimicry 0.45
```

One song failing does not end the batch. A song with no vocal is refused as
Mode B, recorded, and the rest continue. The exit code still tells the truth:
non-zero when any song failed, so a script or CI step sees a partial batch
rather than a clean one. Mode B refusals alone do not fail a batch, since a
song with no vocal was handled exactly as designed. The one exception is a
batch where nothing rendered at all, which exits non-zero whatever the reason:
a run that produced no audio is not a success worth reporting. A hung ffmpeg
cannot stall the run either; every call is bounded by `FFMPEG_TIMEOUT_S` in
`config.py`.

Each song writes both playfulness levels, so twenty songs is 280 files.
`--play conservative` narrows it to one level when that is more listening than
you want.

### Running it in parallel, without taking the machine down

`batch` renders one song at a time. Running several at once is tempting and is
how a workstation gets wedged, so the numbers are written down here rather than
rediscovered.

A render is **single-threaded and holds about 3.5 GB**. Measured: 99% of one
core, which on a 24-core machine reads as 4% in Task Manager and looks like
nothing is happening. It is.

The ceiling is memory, not cores. Eight at once against 19 GB free exhausted
RAM, and the swapping pinned the disk at 100% until the machine had to be
restarted. Divide the free memory by 4 GB and use that, and remember anything
else on the box counts: a local model server can hold 15 GB of RAM and 8 GB of
VRAM on its own, which leaves room for exactly one render.

Five things that each cost an hour to learn:

- **Killing the launcher does not kill the pool.** `xargs -P` keeps refilling
  after its parent shell dies, so a second run silently doubles the
  concurrency. Write the `xargs` pid to a lock file, refuse to start when it is
  live, and kill *that* pid to stop.
- **`--device cpu` does not spare the GPU, it wrecks the run.** Melody
  extraction is torchcrepe, and on this material one song went from 167 seconds
  to over nine minutes without the card. Every render needs the GPU, not just
  the first: `analysis.json` is written each run and never read back.
- **`CUDA_VISIBLE_DEVICES=""` does not hide the card.** Torch still reports
  cuda available and builds a context, so ten workers filled 11.7 GB doing no
  GPU work at all. `-1` genuinely hides it. To leave room for other GPU work
  instead, use `GPU_MEMORY_FRACTION`, and do not set it below what separation
  measurably needs: at 0.15 roformer died with "1.80 GiB allowed" while 6.25 GiB
  of the card was free.
- **`--separator` on a song that already has stems does nothing, and says it
  did.** The cache is `work/<song>/vocal.wav` plus its instrumental, and the
  check is only that both files exist; nothing records which backend wrote
  them. So asking for a different separator reuses whatever is there while the
  header still prints the backend you asked for. `--force` is what actually
  re-separates.
- **Redirect stdout and Python buffers it.** A run that has printed only its
  header looks hung and is not. Use `python -u`, or you will kill working jobs.
  For the same reason, grep batch logs with `-a`: one `ä` in a song title makes
  GNU grep call the file binary and print nothing.

---

## Bring back a take that worked

Every arrangement is logged, so nothing good is lost to a re-roll.

```powershell
.\.venv\Scripts\song-generator.exe input\song.mp4 `
    --arrangement work\song\arrangements\543686-wild.arr
```

The file is readable and editable. Change the words on a line, delete a line,
or delete the `[take]` to let the tool choose the recording. A word the bank
cannot say is refused by name rather than quietly dropped. See
`docs/DATA-FORMATS.md`.

---

## One word is too common, or too rare

Each kind of word has a share of the song it should have, weighted per level in
the `PLAYFULNESS` block of `config.py`. See `docs/GLOSSARY.md` for what the
roles mean.

| Symptom | Knob |
|---|---|
| The song is mostly shouting | `shout_cost` up, or `shout_share` down |
| The words that carry it are drowned out | `core_bonus` up |
| A long word turns up too often | `crown_cost` up |
| Words the song is not about keep appearing | `extra_cost` up |
| The payoff is everywhere / never | `climax_share`, `climax_wildcard` |
| It says the same thing too often | `repeat_penalty` up, `chant_chance` down |
| It never repeats anything, which is half the joke | `chant_chance` up |
| Words sound stitched together | `spelled_cost` and `joined_cost` up |

Measure rather than guess. The run's report prints what was used, and the
share of each role is worth counting across several seeds before deciding a
knob is wrong, since one arrangement is one draw.

Coverage outranks all of them: a required word missing is a broken rule, so
these weights are relaxed and then dropped rather than let that happen. Turning
a knob to 0 will not remove a required word from a song.

---

## Make a bank behave differently

How a bank should be placed is a property of its recordings, so it is
declared beside them: a `bank.json` in the bank directory, read from
whichever directory is actually being sung from. `docs/DATA-FORMATS.md`
documents the format.

```jsonc
{
  "levels": {
    "conservative": {"strategy": "sequence"},
    "wild": {"strategy": "arranged",
             "overrides": {"chant_chance": 0.55, "chant_max": 6}}
  }
}
```

Per level, pick a strategy. `arranged` is the planner every bank gets by
default. `sequence` replays the clips in the order they were recorded,
looping, with no randomness at all, built for a bank whose words were spoken
in an order that carries the meaning. `overrides` lean the level's
parameters from the `PLAYFULNESS` block of `config.py` without redefining
them; any knob a level sets may appear.

Name the bank in the `BANKS` table of `vocabulary_local.py`, or point
`--words-dir` at the directory; the settings are read either way. Renders
land in `output/<song>/<bank>/`, so the same song sung from two banks never
overwrites itself.

A bank with no `bank.json` behaves exactly as every bank always has, and
`tests/test_determinism.py` holds the existing bank to its exact placements
for a fixed seed. If that suite goes red, the change moved a bank that
declared nothing, which is the one thing this mechanism must never do.

---

## Check the bank is the one being sung from

```powershell
.\.venv\Scripts\python.exe -m song_generator.doctor
```

The environment section names, per bank, the directory a run would actually
sing from and whether its standardised tier still matches the recordings. A
stale tier is the quiet failure: the song is sung from clips that no longer
reflect what is on disk, and an ordinary run says nothing about it.

---

## Work out why something sounds wrong

```powershell
.\.venv\Scripts\python.exe -m song_generator.doctor
.\.venv\Scripts\python.exe -m song_generator.doctor --song input\musicHyva.mp4
```

Prints, in one go: whether the environment is sound, what the bank contains,
what pitches it covers, how a song's notes became slots, how many phrases are
long enough to hold a climax, and how far this bank would have to shift to
follow this melody.

Reach for it before changing any constant. Most "it sounds wrong" questions are
answered by the pitch-coverage histogram or the phrase-size line.

---

## Add words to the bank

Only a person can say what a clip contains, so this loop is built around
listening. It is the one part that cannot be automated.

```powershell
# 1. Cut candidates out of one or many sources
.\.venv\Scripts\python.exe -m song_generator.mine_words "sources\*.mp4"

# 2. Collapse into one flat folder, tagging what has not been reviewed
.\.venv\Scripts\python.exe -m song_generator.flatten

# 3. LISTEN. Delete junk. Rename keepers after what you hear.
#       TODO_2syl__kirby__c07__1.42-1.98.wav   ->   bravo7.wav

# 4. Build
.\.venv\Scripts\python.exe -m song_generator.build_bank
```

`mine_words` and `precheck` report like `batch` does. One bad source does not
stop the rest, and the exit code is non-zero when a source failed to mine, so a
partial run cannot pass for a complete one.

Two limits worth knowing rather than discovering. A failed `--asr` pass does
**not** make `mine_words` exit non-zero: recognition is a labelling hint that
gets checked by ear regardless, so a source whose clips were cut correctly has
not failed because the recogniser fell over. It is counted and reported, and
the clips are there to name by hand. In `precheck`, a failed transcription
batch is survived and reported, but a wav that cannot be rendered at all still
ends the run, because that happens before the part with the handler around it.

**Naming.** A variant label may begin with something the bank knows: `_low`
starts with the syllable `lo`, and the name is still read as one word plus a
label. All of these parse: `bravo`, `bravo1`, `bravo_2`, `bravo_low`,
`BRAVO3`. Multi-word clips keep the singer's own transitions and are worth more
than their parts, name them as sequences: `tangodelta`, `aahcalculator`. A shout
can be spelled however it sounded: `aah`, `aaah`, `ahh`, `aaahh`.

**Removing the prefix is what confirms a clip.** Anything still tagged is
ignored by the bank, so leaving a clip alone is always safe.

### Judging a source before cutting it

One measurement predicts whether a source can make a bank at all, and taking
it first would have saved an evening. Separate the source, then compare the
vocal against the instrumental **over the moments the vocal is actually
sounding**:

| source | voice against the band under it |
|---|---|
| `pilluvittu*`, which built `words_hq4` | **+1.5 dB** |
| a buried vocal that produced nothing usable | **−3.1 dB** |

```powershell
.\.venv\Scripts\python.exe -c @"
import pathlib, numpy as np, soundfile as sf
d = pathlib.Path('work/<slug>')
v = sf.read(d/'vocal.wav', dtype='float32', always_2d=True)[0].mean(axis=1)
i = sf.read(d/'instrumental.wav', dtype='float32', always_2d=True)[0].mean(axis=1)
n = min(len(v), len(i)); v, i = v[:n], i[:n]
# Only where the voice is sounding, or the silences flatter it.
on = np.abs(v) > 0.2 * np.percentile(np.abs(v), 99.5)
db = lambda x: 20 * np.log10(max(float(x), 1e-9))
print(db(np.sqrt((v[on]**2).mean())) - db(np.sqrt((i[on]**2).mean())))
"@
```

Above the band, the separator has something clean to take and the clips need
no rescuing. Below it, everything downstream degrades together: the stem is
quiet and full of artefacts, standardising lifts it about 8 dB with the
artefacts included, and pitch tracking stops being reliable. No cutting,
gating or level change repairs that, and four rounds of trying produced
nothing worth keeping. Measure first and say early that a source is a poor
candidate.

Roformer is the separator to use, and it was measured rather than assumed:
against the same buried source it left 0.103 correlation with the
instrumental where Demucs left 0.146. It is better and still not enough on a
bad source.

### When the words have no silence between them

`mine_words` cuts on silence, so a list recited without gaps defeats it.
Three threshold settings each returned two clips of about twenty-nine seconds;
a fourth, pushed harder, split them into four clips with half starting
mid-word. Word timestamps from the recogniser are the only boundary such audio
contains.

Two traps in doing that:

- **Never pass `initial_prompt`.** Telling Whisper the vocabulary to expect
  raised recall from 25 words to 349 and destroyed precision: the merged set
  had a median duration of 0.00 s and only 18% sat on audible vocal. It
  invents words to match the prompt.
- **One pass is not evidence.** The same seventy-three seconds gave 25 words
  on one run and 8 on the next. Merge several passes, longest detection per
  word winning.

Then keep only what survives two gates, both against the stems rather than
the clip alone: the vocal has to be **loud** where the word was heard, and
**uncorrelated** with the instrumental there. Loudness alone passes pure
backing, because the band is loud too.

### Check every clip's pitch against a second detector

The most expensive lesson. Everything downstream trusts the pitch stored for
a clip, and on a processed voice that number can simply be wrong: **9 of 15
clips disagreed with an independent `pyin` estimate by 7 to 19 semitones**. A
clip believed to be at 73 that is really at 54 gets shifted confidently in
the wrong direction, and the result screams. A wrong pitch is worse than a
missing clip.

Cross-check, discard disagreements, then look at the spread of what is left.
Six survivors still spanned **30 semitones** against melodies sitting around
62, so most were octave-folded and landed an octave from the tune. Transpose
them into one register **by whole octaves only**: an octave keeps the voice,
anything else makes it a different singer.

### The bank's own level

`words_hq4` declares no `bank.json`, so it uses `config.WORD_BUS_LUFS`,
**−14.0**. Copying `−11.0` from a spoken bank without measuring made every
render sound wrong in a way that was not simply loudness: the hotter word bus
tripped the −1 dB ceiling in `mapping.mix`, which scales the whole mix down,
so the band was dragged about 2 dB below reference while the words rode
+2.99 above it against +1.58 on a good render. Match the reference bank
unless there is a measured reason not to.

**Pitch spread matters more than quantity.** Takes at *new* pitches raise the
mimicry ceiling directly, by reducing how much has to be octave-folded. Ten more
takes at the same pitch as everything else change nothing.

---

## Re-cut the bank from cleaner stems

The clips were cut from Demucs stems, so whatever instrumental residue Demucs
left behind is baked into them. Re-separating with the Roformer and cutting
again over the same time ranges replaces the audio under every clip without
losing a name, label or syllable boundary.

```powershell
.\.venv\Scripts\python.exe -m song_generator.separate_hq --for-bank "sources\*.mp4"
.\.venv\Scripts\python.exe -m song_generator.recut_bank --out words_hq2
```

`--for-bank` narrows the files you pass to the ones the current bank was cut
from. It cannot find them on its own: the bank records which work directories
its clips separated into, not where the source media lives, so the files or
globs are always given.

`recut_bank` writes an index that describes exactly what it wrote. A clip it
could not write, because its span collapsed against the new stem, or would not
write, because it appeared in the output mid-run and may be hand work, is
dropped from `words.json` and reported, together with the `build_bank` command
that puts the words back once the clips are restored. A word only those clips
carried would otherwise vanish silently at render time, since a render reads
the index alone.

---

## The words are too dense / too sparse

All in the `DENSITY` block of `config.py`:

| Constant | Raise it to... | Lower it to... |
|---|---|---|
| `PHRASE_FILL` | fill more phrases | leave more instrumental space |
| `SHOUT_MAX_SHARE` | more `aah` | less |
| `PREFER_LONGER_UNITS` | fewer, longer placements | busier, more varied |

`PHRASE_FILL` is the blunt instrument; reach for it first. Keep
`PREFER_LONGER_UNITS` mild, at 1.4 the longest clip in the bank won nearly
every slot and the track became one phrase on repeat.

---

## `calculator` never appears / appears too often

The `CLIMAXES` block. `calculator` is refused outside the song's peaks, so it
stays a payoff.

- Never appears? Check that a climax phrase is **long enough to hold it**. The
  smallest `aah+calculator` unit is 5 syllables, and phrases shorter than that are
  excluded from being peaks. This failed silently once.
- Too often? Lower `CLIMAX_PHRASE_SHARE` or `CLIMAX_USE_CHANCE`.
- Want the occasional one off-peak as a joke? `CLIMAX_WILDCARD_CHANCE`.

---

## A song comes back "Mode B, no vocals"

It failed one of two independent tests, and the run prints which. Both must
pass, because they catch different things: loudness catches a near-silent stem,
voicing catches a stem that is loud but full of instrumental bleed.

If it genuinely has vocals, the thresholds are in the `STAGE 1b` block. Try
`--separator roformer` first. It separates vocals noticeably better, and a
weak stem is the usual cause.

---

## Put the site online

The front end is hosted on Azure Static Web Apps, Free plan, and published by
`.github/workflows/deploy.yml`. What runs in Azure and what deliberately does
not is in [AZURE.md](AZURE.md).

**1. Create the site.** Once, from a machine signed in with `az login`:

```powershell
az deployment sub what-if --location westeurope --template-file infra\main.bicep
az deployment sub create  --location westeurope --template-file infra\main.bicep
```

`what-if` changes nothing and prints what the second command would do. Both
create a resource group `rg-songgen-web` and a Free-plan site in it.

**2. Nothing to point anywhere.** `.github/workflows/deploy.yml` is already in
the repository, so a push to `main` that touches `web/` builds and publishes.
GitHub Actions is unmetered on standard runners for a public repository: no
grant request, no second console, no organisation to belong to.

This used to be Azure DevOps and `azure-pipelines.yml`, which is still here
with its trigger off so the two can be read side by side.
[AZURE.md](AZURE.md) has why it moved. The short version is that it stopped
producing runs and nothing in the repository could tell.

**3. Give the repository two secrets.** GitHub, Settings, Secrets and
variables, Actions:

| Secret | Value |
|---|---|
| `AZURE_STATIC_WEB_APPS_API_TOKEN` | see below |
| `GOOGLE_CLIENT_ID` | the OAuth client id, once there is one |

The token is the one credential here, and it is enough on its own to publish to
the site, so it is never committed:

```powershell
az staticwebapp secrets list --name songgen-web --query "properties.apiKey" -o tsv
gh secret set AZURE_STATIC_WEB_APPS_API_TOKEN
gh secret set GOOGLE_CLIENT_ID
```

`gh secret set` with no value prompts for one and does not echo it, which is
why it is written that way rather than piped from the command above it.

The client id is not secret and cannot be. The browser has to know which client
signs people in, so it is in the shipped files however it gets there. The
allowlist on the edge is what actually protects the service.

Both are secrets here even though only one is. GitHub's plain variables are
readable by any workflow in any fork's pull request, and the client id being
public in the shipped files is not a reason to hand it to arbitrary workflow
code as well.

The backend address is not among these. It is `API_BASE_URL` in
`.github/workflows/deploy.yml`, because the edge is reached through a proxy on
a domain this repository names everywhere, and hiding a public hostname bought
nothing. Committing it also removes a trap worth knowing about even now:
**editing a value in a web UI does not start a build**, and `config.json` is
written during one, so the value changed and the site did not. Editing the
workflow triggers the deploy that applies it.

Missing the client id is not a failure. Sign-in is unavailable and the site
says so, which it renders honestly. Missing the address is not a failure
either: away from localhost the site assumes no backend rather than probing the
visitor's own machine, and reports that nothing is answering.

**4. Check that a deploy actually happened.** Not optional, and not the same
question as whether the build was green:

```powershell
curl.exe -s https://<the site hostname>/ | Select-String -Pattern 'main-\w+\.js'
```

The build hashes every bundle name, so that filename changes whenever the
sources do. Run `npx ng build` in `web` and compare it against what came back:
the same hash means the deploy landed, an older one means the site is still
serving a previous build.

This step exists because a front end was rewritten, reviewed, merged with
everything green, and never published: the site went on serving a build six
commits old while nothing anywhere said so.

The suspect at the time was the Azure pipeline's path filter, `web/*`, which
is genuinely ambiguous: Azure Pipelines supports wildcards and `**` is the form
that crosses directories, which would leave a single `*` matching only the
files sitting directly in `web`, while for older servers the documentation says
a trailing `*` does nothing different from naming the directory. It was changed
to `web`, and nothing ran. The workflow that publishes today writes `web/**`,
where GitHub's own documentation is unambiguous.

**What is established, and what is not.** All five deploys this site has had
came from commits that also touched `azure-pipelines.yml`, the filter's other
entry, and none from a change to the site alone. That is a strong correlation
and it is not a proof: the merge that should have published the design added
`web/DESIGN.md`, which sits directly inside `web` and matches the old filter
under every reading, and no build ran. So something else may be involved, and
the repository cannot see it.

The repository's Actions tab is where to look now, in this order:

1. **Is there a run at all** for the commit? If not, the paths filter did not
   match, and `web/**` is the thing to read.
2. **Did the publish step succeed while the check step failed?** Then the
   upload went somewhere other than this site, and the deployment token is the
   thing to check.
3. **Did a run fail earlier than that?** Then the step that failed says why,
   and the site keeps serving the previous build, which is the intended
   behaviour rather than a second fault.

The workflow ends by asking the site what it is serving and fails if it is not
this build, so a green run means a live change rather than a successful
upload.

**5. Reach the backend from the internet.** It runs on a desktop behind a home
connection, so it needs a tunnel. Tailscale Funnel is the free one:

```powershell
tailscale funnel 8000
```

The address it prints is where the edge answers. The site does not call it
directly: `mikkonumminen.dev` proxies `/api/songgen/*` to it, and
`API_BASE_URL` in `.github/workflows/deploy.yml` points at that proxy
instead.

The proxy is not decoration. On any machine signed in to the tailnet, MagicDNS
resolves a `*.ts.net` name to the node's own `100.x` address, so a browser sees
a public page reaching into a private network and blocks it. The site then
reports the backend as unreachable for the one person most likely to be testing
it, while working for everyone else. Vercel's edge is not on the tailnet, so
routing through it makes the address behave the same for everybody.

**6. Let the browser call it.** A page on `azurestaticapps.net` calling the edge
is cross-origin, so the edge has to allow it. On the machine running the edge:

```powershell
$env:SONGGEN_ALLOWED_ORIGINS = "https://<the site hostname>"
```

**The site's hostname, not the API's.** An origin is a property of the page
making the request, so routing through the proxy does not change it: the
browser still says it came from the Static Web App. Adding the proxy's domain
here allows nothing and protects nothing.

Without it every request fails the preflight and the site reports the machine
as unreachable, which is technically true and thoroughly unhelpful.

Measured through the proxy rather than assumed. A preflight for an
authenticated `GET`, carrying the site's origin, comes back with
`Access-Control-Allow-Origin` echoing that origin, `Allow-Headers` including
`Authorization`, and `Vary: Origin`. So the proxy forwards the preflight and
the edge answers it as if the browser had called directly.

Two things about a single page app on a static host, both of which fail as a
blank screen rather than as an error:

- A Static Web App serves from the root of its own hostname, so the build takes
  no `--base-href`. Passing one, as a GitHub project page would need, 404s
  every script after the page loads.
- There is no file at `/runs/abc`, so `web/public/staticwebapp.config.json`
  rewrites unknown paths to `index.html` and hands them to the router.

### Publishing without the workflow

`.github/workflows/deploy.yml` is the normal way and this is the way out when
it cannot run, which has happened to the publisher before: `dev.azure.com`
redirects a personal Microsoft account into the Azure Portal, and the portal's
tenant picker then refuses that account outright (`AADSTS16000`). With no
access to the thing that publishes there is no way to change a value and no way
to press Run, and a broken site stays broken.

`az` on a machine that is signed in can hand over the deploy token, and the
Static Web Apps CLI takes it directly:

```bash
token=$(az staticwebapp secrets list --name songgen-web \
        --query "properties.apiKey" -o tsv)
cd web && npx ng build
cat > dist/songgen-web/browser/config.json <<'JSON'
{ "apiBaseUrl": "...", "googleClientId": "..." }
JSON
npx --yes @azure/static-web-apps-cli deploy dist/songgen-web/browser \
    --deployment-token "$token" --env production
```

The config file is written by hand here because nothing else is going to write
it; the workflow step that normally does is exactly what is being skipped.

**What this costs is the guarantee that the site matches `main`.** A workflow
run is reproducible from a commit and this is not, so after using it, land the
same change in git before the next push does. Any push touching `web` or the
workflow itself rebuilds from `main` and silently reverts whatever was
deployed by hand.

---

## Let people sign in

Every route but the health check is behind Google sign-in and an allowlist of
named accounts, because the pipeline takes an arbitrary link and spends a GPU
on it. The browser only carries a token; the edge decides who may use anything.

**1. Make an OAuth client.** In the Google Cloud console this lives under
**Google Auth platform**, then **Clients**, then **Create client**. It used to
be under APIs and Services, Credentials, and older instructions still say so.

Application type **Web application**.

Under **Authorised JavaScript origins**, add the site, and the dev server if
you develop against it. Google wants the port-less form as well as the one with
a port:

```
https://<the site hostname>
http://localhost
http://localhost:4200
```

Authorised **redirect URIs** stay empty. Identity Services hands the token back
to the page through a callback rather than redirecting anywhere, so a redirect
URI here is one more thing to get wrong for no benefit.

If this is the first client in the project, the console asks for the consent
screen first. **External**, with yourself added as a **test user**, is enough
and is the honest shape: the service is meant for a named few rather than for
whoever finds it. Leaving it in Testing rather than publishing it costs nothing
here, because only ID tokens are used and a fresh one is issued at each
sign-in; the seven-day limit that catches people in Testing applies to refresh
tokens, which this never asks for.

**2. Give the client id to both halves.** The pipeline variable
`GOOGLE_CLIENT_ID` puts it in the site. The edge needs the same id, plus the
list of who may actually use it:

```powershell
$env:SONGGEN_GOOGLE_CLIENT_ID = "<client id>.apps.googleusercontent.com"
$env:SONGGEN_ALLOWED_EMAILS   = "you@example.com,someone.else@example.com"
```

Both are required for anyone to get in. With either missing the edge reports
sign-in as unconfigured, and the site says so rather than showing a button that
cannot work.

The two lists do different jobs and both matter. The client id decides which
site Google will issue a token to; the allowlist decides whose token this
service accepts. A real Google account that is not on the list gets no further
than no account at all.

**3. Check it.** Sign in on the site, then confirm the edge agrees:

```powershell
curl.exe -H "Authorization: Bearer <token>" https://<edge>/banks
```

A 200 means the whole chain works. A 401 naming the allowlist means Google
issued a token for somebody this service does not accept, which is the check
doing its job.

---

## Verify a change

```powershell
$env:PYTHONPATH='.\src'
.\.venv\Scripts\python.exe -m pytest tests\ -q
.\.venv\Scripts\song-generator.exe input\musicHyva.mp4 --rows 0
```

The second matters more. Watch these numbers. They move when behaviour changes:

- **units placed** and **slots filled**: density
- **mimicry** and **ceiling**: how closely the tune survives
- **octave-folded %**: how far the bank sits from this song's register
- **units used**: whether the vocabulary is what you expect

---

## Set syllables aside, or bring them back

Rarely wanted now. Syllable clips used to crowd out the words, because a clip
of `bra` filled a slot as neatly as one of `bravo` and said nothing. The pool
a song is chosen from is filtered to whole words, so a bare syllable is never
placed, and those clips instead spell words no recording contains. Setting
them aside costs that and buys nothing, so the command reports which words
would stop being spellable before you decide.

```powershell
.\.venv\Scripts\python.exe -m song_generator.set_aside            # out of the bank
.\.venv\Scripts\python.exe -m song_generator.set_aside --restore  # back in
```

Renames between `bra.wav` and `SYL_bra.wav`. Nothing is deleted; the ear-work
that identified them stays recorded in the name either way.
