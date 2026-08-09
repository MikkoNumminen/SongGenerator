# How the front end is put together

Two features are deliberately missing from the first cut: building a bank from
a second link, and a snapshot mode that works while the backend is off. Both
are written up in `docs/TODO.md`. Everything here is arranged so that when they
arrive they are **new files, not edits to old ones**. That is the test this
document exists to pass, and the reason for most of the rules below.

## The pipeline is the source of truth

The Python pipeline does separation, analysis, word mapping, pitch shifting,
the seven mimicry rungs and the ceiling calculation. The front end displays its
results and never recomputes them. If a number appears in the UI, it came from a
run, not from arithmetic done here.

The HTTP edge shells out to the existing entry points. It does not import the
pipeline's internals, so pipeline changes cannot break the UI silently and UI
needs cannot leak into pipeline behaviour.

## Ports, and why before they are needed

Every piece of data the UI shows arrives through an interface, not a concrete
client.

| Port | Today | Later |
|---|---|---|
| `RunSource` | live API | a second implementation reading static assets |
| `BankCatalog` | live API | unchanged; the list simply grows |
| `AuthContext` | Google token | unchanged |

Snapshot mode is then one class and one provider swap, chosen at bootstrap by a
health check. No component learns which one it got.

This is the rule most worth keeping honestly: **it is only worth writing a port
before it has two implementations when retrofitting it would mean touching
every caller.** That is true here and it is not true of most things, so this
pattern applies to these three and nothing else.

It also buys the thing that is hard to get otherwise: "the backend is down" is
testable by providing a different `RunSource`, with no HTTP mocking and no
running Python.

## Bank names are data, never an enum

The banks live in a gitignored local override, so their names are not knowable
at build time and differ per machine. The UI asks the catalog and renders what
it gets. A `'curated' | 'muslimbank'` union type anywhere would be wrong on a
fresh clone and would have to be edited every time a bank is added.

## Feature boundaries

```
src/app/
  core/      ports, adapters, auth, health. Injectable, and one component
  shared/    presentational pieces with no feature knowledge
  features/
    submit/  job/  results/  history/
```

The one component in `core` is the Google sign-in button, and the exception is
worth stating rather than hiding. It is not presentational: Google renders into
the element itself, from a script the adapter loads, using a client id only the
adapter knows. Taking all of that through inputs would be the same code with an
extra hop, and would leave `shared` knowing what Google is.

A feature may import `core` and `shared`. **A feature may never import another
feature.** Where two need the same thing, it moves to `shared`, or they talk
through a port. Lazy-loaded routes make this structural rather than a
convention: a feature that reaches sideways will not build cleanly on its own.

## One contract, generated

The DTOs come from the backend's OpenAPI schema, generated into TypeScript at
build time. Hand-written interfaces mirroring a Python model drift the first
time somebody renames a field, and the drift shows up as `undefined` at
runtime rather than as a red build.

## No `HttpClient` in a component

Components take a port or a facade. This is what makes the snapshot swap
possible at all, so it is not style.

## State

Signals for view state, RxJS for streams that are genuinely streams: the job
poll, cancellation, backoff while the backend is unreachable.

**No NgRx.** There is one long-running job and a table of past ones. A store
would be ceremony around a single `switchMap`, and the interesting concurrency
here is retry and cancellation, which RxJS already expresses.

## Loading, error and empty are states, not decorations

Every async view is one of `idle | loading | ready | empty | error | offline`,
rendered explicitly. `offline` is separate from `error` on purpose: the backend
being a desktop that is often off is the normal case, not a fault, and it must
never read as a broken app.

## Testing boundaries

- Ports and validators: unit tested, no HTTP.
- The job status machine: tested per state, including cancellation mid-run and
  the fall back to offline.
- Nothing asserts how audio sounds. The pipeline's own suite covers what the
  audio is; this suite covers what the screen does.
