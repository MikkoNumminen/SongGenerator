# AI-first score

How legible this repo is to an agent picking it up cold, with no memory of how
it was built. Twelve dimensions, each scored 0-10; the score is the mean.

"AI-first" is not a standard metric, so the rubric is written down rather than
assumed. Each dimension states what a 10 looks like, so a score can be argued
with instead of taken on faith.

## Rubric

| # | Dimension | A 10 looks like |
|---|---|---|
| 1 | **Agent onboarding** | A `AGENTS.md` at root that tells an agent what to run, what never to touch, and where the traps are. |
| 2 | **README accuracy** | Every claim is true today. No stale status, no features described that no longer work that way. |
| 3 | **Architecture legibility** | A module map and a data-flow diagram, so nobody has to read 18 files to learn what calls what. |
| 4 | **Configuration** | Every tunable in one place, each with the reasoning behind its value, not just the value. |
| 5 | **Behaviour pinned by tests** | Tests assert the specific failures that actually happened, not just the happy path. |
| 6 | **Determinism** | Same inputs, same outputs. Every random choice seeded and documented. |
| 7 | **Machine-readable artifacts** | Intermediate state on disk as JSON an agent can read without re-running anything. |
| 8 | **Actionable errors** | Every failure says what to do next, with the exact command. |
| 9 | **Domain glossary** | Terms of art defined once. An agent should never have to infer what "slot" means. |
| 10 | **Runbooks** | The common jobs written as steps, so a task does not need reconstructing from history. |
| 11 | **Audible verification** | A command that measures the properties a listener complains about, so "it sounds wrong" becomes a number an agent can check without ears. |
| 12 | **Rendered verification** | A command that renders the front end and checks what a visitor actually gets: at a phone's width, from the keyboard, in both themes, and on the deployed address rather than a local one. |

## Iteration log

### Iteration 0, baseline: 5.0

| # | Dimension | Score | Why |
|---|---|---|---|
| 1 | Agent onboarding | 0 | No `AGENTS.md`. An agent starts cold with no idea the venv is isolated or that `words/` holds hand-reviewed work. |
| 2 | README accuracy | 3 | Says "Commit 1 of 4" and "outputs the instrumental bed". Both false for many commits. No mention of mimicry, banks, density or climaxes. |
| 3 | Architecture legibility | 4 | Module docstrings are strong, but 18 modules with no map. The pipeline order is only discoverable by reading `cli.py`. |
| 4 | Configuration | 9 | `config.py` holds everything, grouped by stage, with the reasoning recorded. Loses a point only for not naming which module consumes each block. |
| 5 | Behaviour pinned by tests | 8 | 159 tests, and the important ones pin real regressions. Nothing covers the newer density and climax logic. |
| 6 | Determinism | 8 | Seeded throughout and ASR pinned to greedy decoding, but nowhere states this as a guarantee. |
| 7 | Machine-readable artifacts | 7 | `analysis.json`, `words.json`, `detect.json`, `--json`. No schema documented. |
| 8 | Actionable errors | 7 | `BankError` and `LabelError` give exact next commands. Others just raise. |
| 9 | Domain glossary | 1 | "Slot", "unit", "phrase", "mimicry", "fold" and "bank" all carry specific meanings, defined nowhere. |
| 10 | Runbooks | 3 | `TODO.md` carries the build order. Nothing describes how to add a song, extend the bank, or tune density. |

**Mean: 5.0**

The gap is documentation, not code. The code is in good shape; what is missing
is everything that lets someone who was not there pick it up.

---

### Iteration 1. The four lowest: 7.4

Wrote the missing documents, worst score first.

- `AGENTS.md`, how to run things, the one irreversible rule, the traps that
  have already bitten (illegal filename characters, non-deterministic ASR,
  filenames as a parsing contract), and a reading order.
- `docs/GLOSSARY.md`, slot, note, phrase, unit, bank, shift, fold, mimicry,
  ceiling, climax, shout, plus the prefix table.
- `docs/ARCHITECTURE.md`, pipeline diagram, module tables, what lands on disk
  and whether it can be regenerated, and why decisions live where they do.
- `docs/WORKFLOWS.md`, make a track, extend the bank, tune density, chase down
  a missing `calculator`, handle a Mode B verdict, verify a change.
- `README.md`, rewritten. It had claimed "Commit 1 of 4" and "outputs the
  instrumental bed" for many commits after both stopped being true.

Onboarding 0→9, README 3→9, architecture 4→9, glossary 1→10, runbooks 3→9.

### Iteration 2, cover the untested logic: 8.9

The density and climax rules had no tests, and every one of their failures had
been **silent**, wrong output, never an error. `tests/test_density.py` pins each
one, including the bug where a peak was chosen on intensity alone and turned out
too short to hold the payoff, so `calculator` could never be placed in any render.

Tests 8→9, and `docs/DATA-FORMATS.md` documented every on-disk schema, 7→10.

### Iteration 3, stop the docs from rotting: 9.6

Documentation that drifts is worse than none: an agent trusting a stale
instruction runs the wrong command confidently. So the docs are now checked by
`tests/test_docs.py`, which fails when they disagree with the code

- every module appears in the architecture map, and none that was deleted
- every constant named in a doc exists in `config.py`
- every module a runbook tells you to run exists and has a `main()`
- every term of art is defined in the glossary
- every review prefix is documented
- the README does not carry its old stale status claims

It found two real problems on its first run: `config.py` and `util.py` were
missing from the architecture map, which I had written minutes earlier.

Error messages also now give the exact command or the exact config block to
change, rather than only naming what went wrong. Errors 7→9.

### Iteration 4, the dimension that was missing: 9.3

The score went down, because the rubric was wrong.

Three real defects shipped and survived in a repo scoring 10 for "behaviour
pinned by tests": a word torn across two octaves by folding each syllable
separately, a word cut in half by real silence wherever the melody rested
between two of its notes, and a held vowel that also stretched the syllable
until it smeared. The suite passed throughout. It could not have caught any of
them, because nothing in it can hear, and none of the ten dimensions asked
whether it needed to. The one that mattered most was found by the owner
listening, after the tests, the types and the linters were all green.

So an eleventh dimension is added rather than pretending the other ten covered
it. It scores 6.

What closed the three defects was turning each audible complaint into a
measurable property of the plan, and pinning that:

| complaint | property | before | after |
|---|---|---|---|
| words spelled out a syllable at a time | silence inside a word | 103 of 154 words | 0 |
| words falling apart mid-way | interval inside a word after folding | enlarged in 21% | preserved |
| held vowels sounding smeared | stretch ratio | pulled toward the 2.0 ceiling | 1.20x median |

That is the pattern worth keeping: an ear finds it, a number pins it, a
revert-check proves the number moves for the stated reason.

It is a 6 and not higher because those measurements were written in the session
and thrown away. Nothing in the repo runs them, so the next agent gets the same
green suite and the same silence. A 10 is a committed command reporting these
per render, which is the next iteration.

The same work produced a trap now recorded in `AGENTS.md`, and it is recorded
because it bit: the first measurement of silence inside words said 37% and was
wrong, because it measured what the planner asked for rather than what sounds.
`TIME_STRETCH_RANGE` caps the stretch, so a segment routinely sounds for less
than its `out_dur_s`. The true figure was 67%, and the wrong one had already
been quoted.

---

### Iteration 5, the part nobody could see: 8.7

The score went down again, for the same reason as last time. Something did not
work and no dimension asked about it.

A front end was designed, reviewed, tested and merged, and the deployed site
did not change. The suite was green, the build was clean, the merge was clean,
and a visitor was served a build six commits old. Nothing in the repository
noticed, because nothing in the repository was looking.

The suspect is the trigger in `azure-pipelines.yml`, which filtered on `web/*`,
and the correlation is strong: all five deploys the site has ever had came from
commits that also touched `azure-pipelines.yml`, the filter's other entry, and
none from a change to the site alone. It was corrected to `web`, which means
everything beneath the directory under every reading of the documentation, and
nothing ran.

It is worth being exact about what that is, because the first two explanations
written for it were both wrong, and one of them was committed. `web/*` was
called a literal string matching nothing, which is false, and then a wildcard
that cannot cross a directory separator, which is defensible but does not fit
the evidence: the merge in question added `web/DESIGN.md`, sitting directly
inside `web`, which every reading of the old filter matches, and no build ran.
So the filter is a plausible cause rather than a proven one, and the honest
record says so and names the run list as the only place that can settle it.

That mistake is the dimension in miniature. Twice, a confident mechanism was
written down from a correlation, because the thing that could have checked it
lives in a web console rather than in the repository.

A change that never reaches anybody is a class of failure none of the eleven
dimensions covered. Ten of them ask whether the repository is legible; the
eleventh asks whether a render sounds right. None asks whether what a person
receives is what the repository says it is.

The publisher has since moved to `.github/workflows/deploy.yml`, which is the
same steps in a place this repository can see, and it ends by asking the site
which build it is serving and failing if the answer is not the one it just
made. That last step is dimension 12 in its smallest possible form: not a
rendered check, just a check that the render reached anybody. The Azure version
is kept with its trigger off, because reading the two side by side is the whole
lesson.

A review of the same branch then found three defects with one shape between
them:

| defect | why nothing caught it |
|---|---|
| the top bar scrolled the whole page sideways on a phone | nothing in the suite renders at a width |
| "Skip to the page" never moved focus | nothing in the suite presses a key |
| a stored light theme flashed a dark page on every load | nothing in the suite looks at a first paint |

Each was found by opening the thing in a browser and using it, which is the
same instrument as the ear in iteration 4 and the same lesson: green answers a
question about the code, not about what somebody receives.

A fourth from that review was a test's job and is now pinned by two: a stage
the front end has never heard of drew five grey rows and a motionless meter,
which is indistinguishable from a stalled run.

So dimension 12 is added rather than pretending 11 covered it. It scores 2. Two
and not zero because the browser checks were actually done this time and the
findings written down, and not higher because none of it is a command anybody
can run: the next agent gets the same green suite and the same silence about
what the page looks like. A 10 is a committed command that loads the built
site, checks it at a phone's width, tabs through it, and says which build is
being served.

The deploy trap and the render gap are both in `AGENTS.md` now, and the
"Put the site online" runbook gained the step that would have caught it: after
a merge that should change the site, ask the site what it is serving instead of
assuming.

The same work closed a smaller gap. The front end had no design and, worse, no
rule for one, so every component invented its own colours. `web/DESIGN.md` and
the tokens in `web/src/styles.css` are dimension 4 for the front end: every
visual value in one place with the reasoning next to it, and the build's
per-component stylesheet budget stating the same rule as a number.

---

### Iteration 6, the check that agreed with the mistake: 8.8

A fault took four wrong diagnoses before it was found, and every one of them
was confirmed by measurement before being committed. That is the interesting
part, and it is not a story about carelessness.

Word endings were breaking. In order, they were blamed on the placement
strategy, on the mimicry shift, on the pitch engine, and on the clip cuts, and
each explanation came with a number that supported it. Three of the four were
wrong. Lowering the shift cap made the fault quieter, which read as
confirmation and was not: a smaller shift mangles any discontinuity less,
whatever caused it. A fix that reduces a symptom has not located it.

The clip-cut diagnosis was wrong in a way worth recording. The check that
verified the cuts used a silence gate set at floor+12 dB, and so did the tool
that made them. A decaying vowel sits below that while still being audible, so
the cuts ran through the ends of words and the check agreed they were clean,
three times. The verification shared the fault's own assumption, which makes it
not a verification. Two rules came out of it: test a cut against the source
recording on both sides rather than against the clip's own body, and cut at the
middle of a measured silence so both sides are quiet by construction rather
than by threshold.

What it actually was: these voices are 57 to 86 per cent unvoiced, and WORLD
rebuilds an unvoiced frame from aperiodicity alone. Long breathy stretches came
back as a tearing scratch, worst in the lowest voice, which has the most breath
and the furthest to move. Unvoiced sound carries no pitch, so shifting it
changes nothing a listener can hear: `render_segments` now puts the original
samples back wherever the source had no f0. Measured as mel-spectral distance
from the source, the male clips went from 1.8 to 1.0 and the female from 3.1 to
2.3.

The owner found it. Every observation that moved this forward came from
listening: which words failed, that a new voice failed identically, that it
broke earlier in the lower voice. Nothing in the repository was capable of
noticing any of it, which is dimension 11 measuring exactly what it says.

What went in, so the next one is cheaper: a diagnostic ladder in
`docs/WORKFLOWS.md` that rules out placement, cuts, shift and voice in that
order and says which numbers decide each; the two traps above in `AGENTS.md`;
and tests that fail without the restore. Audible verification moves 6 to 8, on
the strength of the ladder and the measurements behind it rather than any new
listening the repository can do by itself. It still cannot hear.

---

### Iteration 7, writing down what the ear found: 8.9

The tuning of a three-voice bank produced a working configuration and a long
list of things that do not work, and none of it was anywhere a later bank would
look. A score for a repository that cannot hear should still reward knowing
what to measure and in what order, because that is the part a machine can carry
between banks.

`docs/WORKFLOWS.md` gained the procedure: what the voiced fraction governs, why
cuts belong in the middle of a measured silence, which placement strategy
survives which material, why the bus level is measured rather than copied from
a bank that sounds similar, why folding an octave beats baking one in, and why
the engine is left alone with the numbers that say so. `doctor --bank` now
prints the first measurement it starts from, so the runbook opens with
something runnable rather than something to set up.

Audible verification moves 8 to 9. The repository still cannot hear, and the
entry says so: every fault in that session was found by ear and only then
explained. What changed is that the explanation, the order to look in, and the
values that were settled are written down instead of living in one session.

---

## Current: 8.9

| # | Dimension | 0 | now |
|---|---|---|---|
| 1 | Agent onboarding | 0 | 9 |
| 2 | README accuracy | 3 | 10 |
| 3 | Architecture legibility | 4 | 10 |
| 4 | Configuration | 9 | 9 |
| 5 | Behaviour pinned by tests | 8 | 10 |
| 6 | Determinism | 8 | 9 |
| 7 | Machine-readable artifacts | 7 | 10 |
| 8 | Actionable errors | 7 | 9 |
| 9 | Domain glossary | 1 | 10 |
| 10 | Runbooks | 3 | 10 |
| 11 | Audible verification | 0 | 9 |
| 12 | Rendered verification | 0 | 2 |

**Mean: 8.9**, against **4.2** at baseline scored the same way.

Both of those numbers are over twelve dimensions, and every earlier score in
this log is a mean over however many dimensions existed when it was written, so
they are not comparable to each other. Only the two numbers in this paragraph
are. Dimensions 11 and 12 score 0 at baseline rather than being left blank: the
repo had nothing that measured what a render sounds like, and nothing that
looked at what a visitor is served. Dimension 12 is a little unfair to the
baseline, which had no site to serve, and it is scored anyway, because a 0 for
"there was nothing" and a 0 for "there is something and nobody checks it" are
the same number to whoever is reading the table.

The suite was 159 tests at baseline; what it is now lives in the README, which
is checked against it.

Rendered verification (2) and audible verification (6) are the two largest
gaps, and they are the same gap twice: the only dimensions where a green suite
says nothing about whether the thing did its job. One is answered by listening
and the other by opening a browser, and neither is answered by a command yet.
Rendered verification is worth closing first, because its failure mode is the
cheapest to hit and the most embarrassing: a change that never reaches
anybody.

The four remaining 9s are honest rather than modest:

- **Onboarding (9)**: good, but only proven on this repo's actual traps. A
  fresh agent might still hit something nobody has hit yet.
- **Configuration (9)**. Every value carries its reasoning, but the file does
  not say which module consumes each block.
- **Determinism (9)**: seeded and documented, though nothing *tests* that two
  runs produce identical output.
- **Errors (9)**. The common paths are actionable; the rarer ones still just
  raise.

Each is a real gap rather than a rounding-down, which is why they are not 10s.

