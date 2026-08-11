# How the front end looks, and why

The application had no design at all: browser defaults, Times New Roman, a
blue link. This document is the rule set that replaced it. It is short on
taste and long on constraints, because the constraints are the part that
survives somebody else editing this later.

## The one rule

**A component stylesheet may position things. It may not choose colours,
sizes, radii, shadows or timings.** Those come from tokens in
`src/styles.css`, so a change of palette is a change to one block instead of a
search across twelve files.

The build states the same rule as a number: 4 kB of warning and 8 kB of error
per component stylesheet. A component that needs more than that is usually a
component reinventing something `styles.css` already has.

## What it is meant to look like

A tool that lives in a room with a desktop in it. The reference is a level
meter and a piece of rack hardware, not a marketing page: dark ground, one
warm signal colour, technical values in a monospace face, and no decoration
that is not saying something.

Amber is the signal: the thing happening right now. Mint is finished, coral is
broken, violet is the wilder of the two playfulness levels. Nothing else gets
a colour, because a palette where everything is coloured is a palette where
nothing stands out.

There are no web fonts. The page is served to strangers, and a font request is
a request to somebody else's server for no gain a system stack does not
already give.

## The tokens

`src/styles.css` is in ten numbered sections. The two worth knowing:

- **Section 1, palette primitives.** Raw values named for what they are
  (`--amber-400`). Nothing outside section 2 may refer to them.
- **Section 2, semantic tokens.** Named for the job (`--accent`, `--bad-text`,
  `--surface-sunk`). This is what components use, always.

Three colour tokens exist per meaning rather than one, and the distinction is
what makes both themes work without a second set of rules:

| Token           | For                                                |
| --------------- | -------------------------------------------------- |
| `--accent`      | a fill, a border, a glow                           |
| `--accent-text` | that colour as text, dark enough to read on `--bg` |
| `--accent-ink`  | text placed **on top of** an `--accent` fill       |

`--ok`, `--bad` and `--wild` follow the same shape.

## Dark and light

Dark is the default because it is the identity of the thing. Light is a real
design rather than an inversion: warm paper, its own shadows, and its own
darker readings of every accent so text keeps its contrast.

The palette is declared three times, and that is deliberate. CSS cannot attach
one block to both a media query and an attribute selector, so the light values
appear once under `prefers-color-scheme` and once under `[data-theme='light']`.
Resolving the theme in JavaScript before first paint would remove the
duplication and flash the wrong colours at anybody whose JavaScript is slow or
off.

`ThemeSwitch` keeps `system` as a real third state and writes no attribute at
all while it holds. Somebody who has never touched the toggle follows their
machine, including when their machine changes its mind at sunset.

## Motion

Every animation is decoration over a state that is already legible without it:
the meter still shows the percentage with the sweep switched off, the stage
list still says which stage is current without the dot. That is what makes the
global `prefers-reduced-motion` block honest rather than a degraded mode.

## Accessibility, as things that were actually checked

- One focus ring, `:focus-visible` only, from the global sheet. Custom
  controls that hide their `<input>` (the bank cards, the level switch) keep
  it in the layout at 1 px rather than using `display: none`, which would take
  them out of the tab order and the accessibility tree.
- Body and muted text clear 4.5:1 in both themes. `--text-faint` is a separate
  and darker value in light for exactly that reason.
- The waveform under the heading is `aria-hidden`. It is decoration and says
  so.
- The four-column history table becomes one labelled block per row below
  44 rem, with the column names coming from `data-label` rather than being
  written twice in the template.

## Adding something

1. Look for it in section 5 to 9 of `styles.css` first. Cards, buttons,
   fields, badges and chips are already there.
2. If it is genuinely new and more than one feature will want it, add it to
   `styles.css` in the right section.
3. If only one feature will ever want it, put it in that feature's stylesheet,
   and still take every value from a token.
