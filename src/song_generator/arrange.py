"""Cut the words out of the recorded phrases, so they can be said in any order.

The bank is not a set of words. It is fourteen recorded phrases, and most of
them hold several words at once: perse+pillu, paska+perse+pornolehti,
eee+paviaani. That is why the singer sounds like a person rather than a
sampler, and it is also why the automation could only ever repeat what was
recorded. There is no clip of pillu on its own, so "paska pillu" was not a
sequence the tool could produce at all.

It does not need one. build_bank already measured where every word starts
inside every clip, because stage 3 needs those boundaries to land syllables on
notes. The same numbers cut a phrase back into its words.

So a bare pillu is a slice of perse+pillu, and paska pillu is that slice
crossfaded onto the recorded paska. Both are DERIVED: they carry the clip they
came from in their name, they are never written to disk over anything, and the
recorded phrase is always preferred where one exists, because a real recording
carries the singer's own transition between two words and a crossfade does not.

What this buys is that the arrangement layer can ask for any order of any
words, and get it.
"""

from __future__ import annotations

import dataclasses
import random
from dataclasses import dataclass
from pathlib import Path



import numpy as np

from . import config
from .mapping import Unit, _crossfade

# Fade over a slice edge. Long enough to kill the click of cutting mid-phrase,
# short enough not to soften the consonant that starts a word.
SLICE_FADE_S = 0.006


def word_spans(unit: Unit) -> list[tuple[str, float, float]] | None:
    """(word, start, end) for each word in a clip, from its syllable bounds.

    Returns None when the clip does not carry enough information to be cut
    safely. That is the common case for a single-word clip and for anything
    whose boundaries were never measured, and in both cases the right answer is
    to leave the clip alone rather than guess where a word ends.
    """
    if len(unit.words) < 2:
        return None

    edges = [0.0] + list(unit.bounds_s) + [unit.duration_s]
    if len(edges) != unit.syllables + 1:
        return None

    spans: list[tuple[str, float, float]] = []
    at = 0
    for word in unit.words:
        length = config.WORD_SYLLABLES.get(word, 1)
        if at + length >= len(edges):
            return None
        spans.append((word, edges[at], edges[at + length]))
        at += length
    return spans


def _cut(unit: Unit, start_s: float, end_s: float,
         sr: int = config.SAMPLE_RATE) -> np.ndarray:
    lo = max(0, int(round(start_s * sr)))
    hi = min(unit.audio.shape[1], int(round(end_s * sr)))
    piece = np.array(unit.audio[:, lo:hi], dtype=np.float32)

    fade = min(int(SLICE_FADE_S * sr), piece.shape[1] // 2)
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        piece[:, :fade] *= ramp
        piece[:, -fade:] *= ramp[::-1]
    return piece


def slice_words(units: list[Unit], sr: int = config.SAMPLE_RATE) -> list[Unit]:
    """Every word that appears inside a multi-word clip, on its own.

    One slice per word occurrence, so a phrase holding perse+pillu+perse gives
    two perse slices and one pillu. They are worth keeping apart: they were
    sung at different points in the phrase and carry different pitch and
    attack, which is exactly the variety the bank is otherwise short of.
    """
    out: list[Unit] = []
    for unit in units:
        # Cutting the payoff pairing into words is how the payoff got lost:
        # the bare halves outnumbered the recording and won the peaks off it.
        if unit.is_shout_pairing:
            continue
        spans = word_spans(unit)
        if spans is None:
            continue

        at = 0
        for i, (word, start_s, end_s) in enumerate(spans):
            length = config.WORD_SYLLABLES.get(word, 1)
            audio = _cut(unit, start_s, end_s, sr)
            if audio.shape[1] < int(0.05 * sr):
                at += length
                continue

            pitches = unit.syllable_midi[at:at + length] or []
            known = [p for p in pitches if p is not None]
            inner = [round(b - start_s, 4)
                     for b in unit.bounds_s if start_s < b < end_s]

            out.append(Unit(
                name=f"{unit.name}#{i + 1}:{word}",
                words=[word],
                syllables=length,
                duration_s=audio.shape[1] / sr,
                midi=float(np.median(known)) if known else unit.midi,
                audio=audio,
                bounds_s=inner,
                syllable_midi=list(pitches),
            ))
            at += length
    return out


def join_words(parts: list[Unit], sr: int = config.SAMPLE_RATE) -> Unit | None:
    """Crossfade single words into one unit that says them in that order.

    The join is a crossfade, not a recorded transition, which is why a real
    clip of the same sequence always wins when one exists. What this is for is
    the sequences nobody ever sang: paska pillu, eee paska, pillu pornolehti.
    """
    parts = [p for p in parts if p.audio.shape[1] > 0]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]

    audio = parts[0].audio
    bounds = list(parts[0].bounds_s)
    running = parts[0].duration_s

    for nxt in parts[1:]:
        bounds.append(round(running, 4))
        bounds.extend(round(running + b, 4) for b in nxt.bounds_s)
        audio = _crossfade(audio, nxt.audio, sr)
        running += nxt.duration_s - config.COMPOSE_CROSSFADE_S

    known = [p for part in parts for p in part.syllable_midi if p is not None]
    duration_s = audio.shape[1] / sr
    return Unit(
        name="joined:" + "+".join(p.name for p in parts),
        words=[w for p in parts for w in p.words],
        syllables=sum(p.syllables for p in parts),
        duration_s=duration_s,
        midi=float(np.median(known)) if known else parts[0].midi,
        audio=audio,
        bounds_s=[b for b in bounds if 0.0 < b < duration_s],
        syllable_midi=[p for part in parts for p in part.syllable_midi],
    )


def label_of(words: list[str]) -> str:
    return "+".join(words)


def index_by_word(units: list[Unit]) -> dict[str, list[Unit]]:
    """Single-word units, grouped by which word they say."""
    out: dict[str, list[Unit]] = {}
    for u in units:
        if len(u.words) == 1:
            out.setdefault(u.words[0], []).append(u)
    return out


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------

def level_params(level: str) -> dict:
    if level not in config.PLAY_LEVELS:
        raise ValueError(
            f"unknown playfulness level {level!r}.\n"
            f"    Expected one of: {', '.join(sorted(config.PLAY_LEVELS))}.\n"
            "    Levels are defined in the PLAYFULNESS block of config.py."
        )
    return dict(config.PLAY_LEVELS[level])


def required_words() -> tuple[str, ...]:
    """Words every song must contain."""
    named = getattr(config, "PLAY_REQUIRED_WORDS", None)
    return tuple(named) if named else tuple(config.WORD_SYLLABLES)


# ---------------------------------------------------------------------------
# Inventing orders nobody recorded
# ---------------------------------------------------------------------------

def _combo_shapes(words: list[str], shout: str | None) -> list[list[str]]:
    """The word orders worth trying, as shapes rather than every permutation.

    Six words permute into hundreds of sequences, almost all of them the same
    joke told at different lengths. These are the shapes that actually differ:
    two short words either way round, the shout leading into something, and a
    long word crowning a pair.
    """
    short = [w for w in words if config.WORD_SYLLABLES.get(w, 1) <= 2 and w != shout]
    long = [w for w in words if config.WORD_SYLLABLES.get(w, 1) > 2 and w != shout]

    shapes: list[list[str]] = []
    for a in short:
        for b in short:
            if a != b:
                shapes.append([a, b])
    if shout:
        shapes.extend([shout, w] for w in short + long)
    for a in short:
        for b in long:
            shapes.append([a, b])
    for a in short:
        for b in short:
            for c in long:
                if a != b:
                    shapes.append([a, b, c])
    return shapes


def invent_units(by_word: dict[str, list[Unit]], how_many: int,
                 rng, existing: set[str]) -> list[Unit]:
    """Build word orders the bank never recorded.

    Sampled rather than exhaustive, and seeded, so a run makes a handful of new
    sequences and the next run makes different ones. Anything the bank already
    has as a real recording is skipped: a crossfade cannot improve on the
    singer's own transition between two words.
    """
    if how_many <= 0 or not by_word:
        return []

    shout = config.SHOUT_WORDS[0] if config.SHOUT_WORDS else None
    shapes = [s for s in _combo_shapes(sorted(by_word), shout)
              if label_of(s) not in existing and all(w in by_word for w in s)]
    if not shapes:
        return []

    rng.shuffle(shapes)
    out: list[Unit] = []
    for shape in shapes[:how_many]:
        parts = [rng.choice(by_word[w]) for w in shape]
        joined = join_words(parts)
        if joined is not None:
            joined.name = "invented:" + label_of(shape) + f":{len(out) + 1}"
            out.append(joined)
    return out


def enrich(units: list[Unit], level: str, rng) -> list[Unit]:
    """The pool the planner gets to choose from, for one run.

    Recorded clips first and always: they are the reason this sounds like a
    person. The slices and the invented orders are what let the automation say
    something that was never recorded, and they win a slot only when they fit
    it better than anything real.
    """
    from .mapping import compose_words

    params = level_params(level)
    if not params["slice_words"]:
        return [u for u in units if u.is_word_like] or list(units)

    # Cut everything into its parts first. A clip of whole words gives words; a
    # clip of syllables gives syllables, which is what spelling needs.
    slices = slice_words(units)

    # Spell whole words out of loose syllables. compose_words wants single
    # syllables as units of their own, which is exactly what slicing a syllable
    # clip produces, so a hand-cut "pas ka" reaches every word using pas or ka.
    spelled = compose_words(units + slices)

    pool = list(units) + slices + spelled

    # Invent from WORDS only. Built from every single-token unit it also
    # reached for syllables, and every order containing one was then thrown
    # away as unsingable, so the whole invention budget went nowhere.
    by_word = index_by_word([u for u in pool if u.is_word_like])
    existing = {u.label for u in units}
    pool.extend(invent_units(by_word, int(params["invent_combos"]), rng, existing))

    # Only whole words get sung. The syllables did their job by spelling.
    singable = [u for u in pool if u.is_word_like]
    return singable or pool


# ---------------------------------------------------------------------------
# The arrangement: what gets sung where, written so a person can read and edit it
# ---------------------------------------------------------------------------

@dataclass
class Line:
    """One placement, as it appears in the log."""
    phrase: int
    onset_s: float
    n_slots: int
    words: list[str]
    take: str | None = None

    @property
    def label(self) -> str:
        return label_of(self.words)


@dataclass
class Arrangement:
    song: str
    bank: str
    level: str
    seed: int
    lines: list[Line] = dataclasses.field(default_factory=list)

    def words_used(self) -> set[str]:
        return {w for line in self.lines for w in line.words}

    def missing(self) -> list[str]:
        return [w for w in required_words() if w not in self.words_used()]

    def has_pairing(self) -> bool:
        """Whether the shout runs into the payoff anywhere in this song."""
        return any(a in config.SHOUT_WORDS and b in config.CLIMAX_WORDS
                   for line in self.lines
                   for a, b in zip(line.words, line.words[1:]))


def clock(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:05.2f}"


def unclock(text: str) -> float:
    minutes, _, seconds = text.partition(":")
    return int(minutes) * 60 + float(seconds)


def describe(plan, song: str, bank: str, level: str, seed: int) -> Arrangement:
    """Read an arrangement out of a finished plan."""
    return Arrangement(song=song, bank=bank, level=level, seed=seed, lines=[
        Line(phrase=p.phrase, onset_s=round(p.onset_s, 3), n_slots=p.n_slots,
             words=list(p.unit.words), take=p.unit.name)
        for p in plan.placements
    ])


HEADER = """# SongGenerator arrangement
#   song    {song}
#   bank    {bank}
#   level   {level}
#   seed    {seed}
#
# What gets sung, in song order. Edit it and feed it back with
#     song-generator.exe <song> --arrangement <this file>
#
#   at      when it starts. The song decides the slots; this locates the line.
#   x<n>    how many melody slots it covers.
#   words   what is sung there, in order. This is the part to edit.
#   [take]  which recording. Delete it and the best fit is chosen for you, or
#           the words are built out of slices if nothing recorded says them.
#
# Words available: {vocabulary}
# Every song must contain: {required}
"""


def render_text(arr: Arrangement) -> str:
    out = [HEADER.format(song=arr.song, bank=arr.bank, level=arr.level, seed=arr.seed,
                         vocabulary=", ".join(sorted(config.WORD_SYLLABLES)),
                         required=", ".join(required_words()))]
    phrase = None
    for line in arr.lines:
        if line.phrase != phrase:
            phrase = line.phrase
            out.append(f"{chr(10)}phrase {phrase}")
        words = " ".join(line.words)
        take = f"  [{line.take}]" if line.take else ""
        out.append(f"  {clock(line.onset_s):>8}  x{line.n_slots:<2} {words:<32}{take}")
    return "\n".join(out) + "\n"


class ArrangementError(RuntimeError):
    pass


def parse_text(text: str) -> Arrangement:
    """Read an arrangement file back, including one edited by hand.

    Deliberately forgiving about spacing and about a missing take, and strict
    about anything that would change what is sung without saying so: an unknown
    word, or a slot count that is not a number. A typo that silently dropped a
    word would be the worst possible failure here, because the result would
    still play.
    """
    meta = {"song": "", "bank": "", "level": config.PLAY_DEFAULT_LEVEL, "seed": "0"}
    lines: list[Line] = []
    phrase = 0

    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            parts = stripped.lstrip("# ").split(None, 1)
            if len(parts) == 2 and parts[0] in meta:
                meta[parts[0]] = parts[1].strip()
            continue
        if stripped.startswith("phrase "):
            try:
                phrase = int(stripped.split()[1])
            except (IndexError, ValueError) as exc:
                raise ArrangementError(f"line {number}: cannot read phrase number: {raw!r}") from exc
            continue

        take = None
        if "[" in stripped and stripped.rstrip().endswith("]"):
            stripped, _, rest = stripped.partition("[")
            take = rest.rstrip("]").strip() or None

        fields = stripped.split()
        if len(fields) < 3 or not fields[1].startswith("x"):
            raise ArrangementError(
                f"line {number}: expected '<at>  x<slots>  <words>', got {raw!r}")
        try:
            onset_s = unclock(fields[0])
            n_slots = int(fields[1][1:])
        except ValueError as exc:
            raise ArrangementError(f"line {number}: {exc} in {raw!r}") from exc

        words = fields[2:]
        unknown = [w for w in words if w not in config.WORD_SYLLABLES]
        if unknown:
            raise ArrangementError(
                f"line {number}: not words in this bank: {', '.join(unknown)}."
                f" Available: {', '.join(sorted(config.WORD_SYLLABLES))}")
        if not words:
            raise ArrangementError(f"line {number}: no words given")

        lines.append(Line(phrase, onset_s, n_slots, words, take))

    if not lines:
        raise ArrangementError("no placements in this arrangement")
    try:
        seed = int(meta["seed"])
    except ValueError:
        seed = 0
    return Arrangement(meta["song"], meta["bank"], meta["level"], seed, lines)


def unit_for(words: list[str], pool: list[Unit], by_word: dict[str, list[Unit]],
             take: str | None = None) -> Unit | None:
    """The best unit that says these words, built from slices if need be.

    This is what makes the format two-way. A person can write a sequence nobody
    recorded and nobody generated, and it is assembled on the spot out of the
    words the bank does have.
    """
    if take:
        for u in pool:
            if u.name == take:
                return u
    wanted = label_of(words)
    exact = [u for u in pool if u.label == wanted]
    if exact:
        # Longest first: prefer a real recording of the whole sequence.
        return max(exact, key=lambda u: (not u.name.startswith(("invented:", "joined:")),
                                         u.duration_s))
    parts = []
    for w in words:
        if w not in by_word or not by_word[w]:
            return None
        parts.append(by_word[w][0])
    return join_words(parts)


# ---------------------------------------------------------------------------
# Building one, and getting it back
# ---------------------------------------------------------------------------

def build(slots, units: list[Unit], level: str, seed: int,
          song: str = "", bank: str = "") -> tuple[object, Arrangement, int]:
    """One arrangement, redrawn until it says every required word.

    Coverage is checked after the fact rather than forced during planning,
    because forcing a word into a slot it does not fit is audibly worse than
    the missing word was. Redrawing is cheap: nothing has been rendered yet.

    Returns the plan, its description, and how many draws it took. The seed
    that survived is recorded in the description, so a run stays reproducible
    from the number it printed.
    """
    from .mapping import plan_words

    params = level_params(level)
    wanted = set(required_words())
    tries = max(1, int(config.PLAY_COVERAGE_TRIES))

    # The pairing counts as coverage, not as an aesthetic preference. It is the
    # one thing the bank is built around, and a song without it anywhere reads
    # as a song missing its payoff rather than as a song that varied.
    possible = any(u.is_shout_pairing for u in units)

    def scored(arrangement) -> tuple[int, int]:
        return (len(wanted & arrangement.words_used()),
                int(arrangement.has_pairing()))

    best = None
    for attempt in range(tries):
        this_seed = seed + attempt

        # Coverage is a rule; how often each kind of word should be heard is a
        # preference. When a redraw alone cannot find a required word, it is
        # usually the preferences holding it out, so they give way rather than
        # the rule. A long word charged for being long is exactly the case.
        drawing = dict(params)
        if attempt >= tries // 2:
            relax = 0.0 if attempt >= (3 * tries) // 4 else 0.5
            for knob in ("crown_cost", "extra_cost", "shout_cost", "core_bonus",
                         "slice_cost", "joined_cost", "spelled_cost"):
                drawing[knob] = float(drawing.get(knob, 0.0)) * relax

        pool = enrich(units, level, random.Random(this_seed))
        plan = plan_words(slots, pool, seed=this_seed,
                          play=None if level == "off" else drawing)
        arrangement = describe(plan, song, bank, level, this_seed)

        covered = wanted <= arrangement.words_used()
        paired = arrangement.has_pairing() or not possible
        if covered and paired:
            return plan, arrangement, attempt + 1
        if best is None or scored(arrangement) > scored(best[1]):
            best = (plan, arrangement, attempt + 1)

    return best


def realise(arrangement: Arrangement, slots, units: list[Unit]) -> object:
    """Turn a description back into a plan, exactly.

    Placements are rebuilt from the file rather than replanned, so an edited
    arrangement produces what it says and nothing else. Each line is anchored
    to the slot nearest the time it records; a line that cannot be anchored is
    refused by name, since a silently misaligned word is worse than a stop.
    """
    from .mapping import Placement, Plan

    pool = list(units)
    pool.extend(slice_words(units))
    by_word = index_by_word(pool)

    plan = Plan(slots_total=len(slots))
    for line in arrangement.lines:
        start = min(range(len(slots)),
                    key=lambda i: abs(slots[i].onset_s - line.onset_s), default=None)
        if start is None:
            raise ArrangementError("this song has no slots to place words on")

        covered = slots[start:start + max(1, line.n_slots)]
        if not covered:
            raise ArrangementError(
                f"{clock(line.onset_s)}: no slots there. This arrangement was "
                "written for a different song, or the analysis has changed.")

        unit = unit_for(line.words, pool, by_word, line.take)
        if unit is None:
            raise ArrangementError(
                f"{clock(line.onset_s)}: cannot say {' '.join(line.words)!r} with "
                f"this bank. No clip holds those words and no slices exist for "
                f"all of them.")

        plan.placements.append(Placement(
            unit=unit,
            onset_s=covered[0].onset_s,
            slot_span_s=covered[-1].offset_s - covered[0].onset_s,
            play_s=unit.duration_s,
            n_slots=len(covered),
            phrase=covered[0].phrase,
            slots=list(covered),
        ))
        plan.slots_used += len(covered)

    for a, b in zip(plan.placements, plan.placements[1:]):
        a.play_s = min(a.play_s, max(0.0, b.onset_s - a.onset_s))
    return plan


def log_path(work: Path, level: str, seed: int) -> Path:
    return Path(work) / config.PLAY_LOG_DIR / f"{seed}-{level}.arr"


def save(arrangement: Arrangement, work: Path) -> Path:
    path = log_path(work, arrangement.level, arrangement.seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_text(arrangement), encoding="utf-8")
    return path


def load(path: Path) -> Arrangement:
    path = Path(path)
    if not path.is_file():
        raise ArrangementError(f"{path} not found")
    return parse_text(path.read_text(encoding="utf-8"))
