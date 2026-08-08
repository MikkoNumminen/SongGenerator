# AI-first score

How legible this repo is to an agent picking it up cold, with no memory of how
it was built. Eleven dimensions, each scored 0-10; the score is the mean.

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

## Current: 9.3

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
| 11 | Audible verification | 6 | 6 |

**Mean: 9.3**, up from 5.0 but down from the 9.6 this claimed while scoring
only ten dimensions. The suite was 159 tests at baseline; what it is now lives
in the README, which is checked against it.

Audible verification (6) is the largest single gap and the one most worth
closing next, because it is the only dimension where a green suite says nothing
about whether the tool did its job.

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

