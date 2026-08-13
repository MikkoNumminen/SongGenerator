"""Stage 3: lay the word bank onto the melody's slots, and mix.

No pitch shifting here -- clips go down at their own recorded pitch. This is the
first listenable version, and the point of it is to judge whether the timing and
the word choice already carry the joke before pitch is added on top.

Placement is per UNIT rather than per syllable. A unit is whatever one clip
holds: a single word, or two or three words with the singer's own transition
between them. Each unit starts exactly on its slot's onset and then plays at its
natural speed, truncated only if the next unit is due before it finishes. That
keeps the delivery inside a unit intact -- the part that carries the character --
and quantises only at the joins, which is where a listener expects movement
anyway. Fitting each syllable individually needs time-stretching, which arrives
in stage 4 along with the engine that can do it without wrecking the timbre.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import audio_io, config


class BankError(RuntimeError):
    pass


@dataclass
class Unit:
    """One clip from the bank, and everything needed to place it."""
    name: str
    words: list[str]
    syllables: int
    duration_s: float
    midi: float | None
    audio: np.ndarray
    bounds_s: list[float] = field(default_factory=list)
    syllable_midi: list[float | None] = field(default_factory=list)
    # The zero-padded index build_bank --raw writes ("0001", "0002"), which is
    # chronological order in the source. Empty for derived units and for banks
    # built before the field existed; only plan_sequence reads it.
    variant: str = ""

    @property
    def label(self) -> str:
        return "+".join(self.words)

    @property
    def is_bare_shout(self) -> bool:
        """A shout on its own -- punctuation, not vocabulary."""
        return all(w in config.SHOUT_WORDS for w in self.words)

    @property
    def is_shout_pairing(self) -> bool:
        """A shout running straight into the payoff, as recorded.

        This is the pairing the whole bank is built around, so it is protected
        twice: it is never cut apart into its words, and at a peak it is
        preferred over anything else that could go there.
        """
        return any(a in config.SHOUT_WORDS and b in config.CLIMAX_WORDS
                   for a, b in zip(self.words, self.words[1:]))

    @property
    def is_climax(self) -> bool:
        """Reserved for the song's peaks rather than ordinary vocabulary."""
        return any(w in config.CLIMAX_WORDS for w in self.words)

    @property
    def is_word_like(self) -> bool:
        """True when every part is a real word, not a bare syllable.

        A clip of "pas" fits a slot as neatly as one of "bravo" and says
        nothing, so syllables are kept for spelling words rather than sung on
        their own.
        """
        return all(w in config.WORD_SYLLABLES for w in self.words)

    def syllable_spans(self) -> list[tuple[float, float]]:
        edges = [0.0] + list(self.bounds_s) + [self.duration_s]
        return list(zip(edges[:-1], edges[1:]))

    def word_of_syllable(self, i: int) -> str | None:
        """Which of this unit's words the given syllable belongs to."""
        running = 0
        for word in self.words:
            length = config.WORD_SYLLABLES.get(word, 1)
            if i < running + length:
                return word
            running += length
        return self.words[-1] if self.words else None

    def is_shout_syllable(self, i: int) -> bool:
        return self.word_of_syllable(i) in config.SHOUT_WORDS

    def source_midi(self, i: int) -> float | None:
        if i < len(self.syllable_midi) and self.syllable_midi[i] is not None:
            return self.syllable_midi[i]
        return self.midi


@dataclass
class Slot:
    onset_s: float
    offset_s: float
    midi: float
    phrase: int
    rms_db: float = -30.0

    @property
    def dur_s(self) -> float:
        return self.offset_s - self.onset_s


@dataclass
class Placement:
    unit: Unit
    onset_s: float
    slot_span_s: float      # what the melody allotted
    play_s: float           # what actually sounds, after truncation
    n_slots: int
    phrase: int
    slots: list[Slot] = field(default_factory=list)   # the notes to land on
    shifts: list[float] = field(default_factory=list)  # semitones, after folding
    do_shift: bool = True     # False = leave it at its own recorded pitch
    # False when this clip must sound whole: one segment, one shift, no
    # syllable ever landing on its own note. Half a spoken name is not a
    # shorter name, it is a different sound.
    split: bool = True
    # The output duration the planner asks for, in seconds. None is the sung
    # fitting, where the slots decide: each syllable takes its slot's length
    # and the unshifted render truncates to play_s. Set, it is the one
    # authority on how long this unit sounds, and build_segments and BOTH
    # render branches honour it, within the engine's stretch range. It is a
    # field of its own so that which planner made a placement never has to
    # be guessed from another field's value, which is how a whole clip once
    # rendered at natural length over a half-second span.
    target_s: float | None = None
    # How far this clip may be shifted before the shift folds by octaves.
    # None is config.SHIFT_CAP_SEMITONES. Carried per placement rather than
    # read from config where it is used, because it is a property of the bank
    # the clip came from: a spoken voice tears at a distance a sung one
    # survives, and a batch renders several banks in one process.
    shift_cap: float | None = None

    def raw_distance(self) -> float:
        """Furthest any of this unit's syllables would have to move, unfolded."""
        worst = 0.0
        for i, slot in enumerate(self.slots):
            source = self.unit.source_midi(i)
            if source is not None:
                worst = max(worst, abs(slot.midi - source))
        return worst

    @property
    def stretch_needed(self) -> float:
        """How far off natural speed the unit is. 1.0 = a perfect fit."""
        return self.unit.duration_s / self.slot_span_s if self.slot_span_s > 0 else float("inf")


@dataclass
class Plan:
    placements: list[Placement] = field(default_factory=list)
    slots_used: int = 0
    slots_total: int = 0
    slots_dropped: int = 0
    merged: int = 0
    split: int = 0


# ---------------------------------------------------------------------------
# Bank
# ---------------------------------------------------------------------------

def level_clip(audio: np.ndarray) -> np.ndarray:
    """Bring one clip to the bank's common level.

    Clips arrive from dozens of sources at wildly different levels, and
    matching only the finished word bus leaves that unevenness intact inside
    it -- one word blares, the next is inaudible under the band. Measured as
    RMS over the sounding part only, so a long silent tail cannot make a clip
    read as quiet and get boosted into distortion.
    """
    audio = np.asarray(audio, dtype=np.float32)
    mono = audio.mean(axis=0) if audio.ndim > 1 else audio

    loud = mono[np.abs(mono) > 10 ** (-45 / 20)]
    if loud.size < 32:
        loud = mono
    rms = float(np.sqrt(np.mean(np.square(loud)))) if loud.size else 0.0
    if rms <= 1e-6:
        return audio

    gain = 10 ** ((config.CLIP_TARGET_RMS_DB - 20 * np.log10(rms)) / 20)
    peak = float(np.abs(audio).max()) * gain
    if peak > config.CLIP_PEAK_CEILING:
        gain *= config.CLIP_PEAK_CEILING / peak
    return (audio * gain).astype(np.float32)


def resolve_bank(words_dir: Path, prefer_standardised: bool = True) -> tuple[Path, bool]:
    """Which directory to sing from, and whether its clips are already levelled.

    A standardised tier sits beside its bank as words_hq.std and is preferred
    when it exists. A clone that has never run the pass has no such directory
    and gets the recorded clips, which is the behaviour that shipped before the
    tier existed.

    The second value says whether the clips arrive pre-levelled. Getting that
    wrong is silent: level_clip would re-measure baked audio and replace a
    considered LUFS decision with an RMS one, undoing the pass on load.
    """
    words_dir = Path(words_dir)
    if prefer_standardised:
        tier = words_dir.with_name(words_dir.name + config.STD_SUFFIX)
        if (tier / "words.json").is_file() and (tier / config.STD_MANIFEST).is_file():
            return tier, True
    # Pointing --words-dir straight at a tier has to work too, so the marker is
    # what decides, not how the directory was reached.
    return words_dir, (words_dir / config.STD_MANIFEST).is_file()


def load_bank(words_dir: Path = Path("words"),
              prefer_standardised: bool = True,
              singable_only: bool = True,
              place_bare_syllables: bool | None = None) -> list[Unit]:
    """Read a bank off disk into units.

    place_bare_syllables is a per-run request (the --bare-syllables flag) and
    travels here as an argument on purpose. It used to be written into config
    as a module global, which outlived the run that asked for it: batch calls
    the render path once per song in one process, so every later song
    inherited the first one's flag. None means the config default.
    """
    words_dir, standardised = resolve_bank(words_dir, prefer_standardised)
    index = words_dir / "words.json"
    if not index.is_file():
        raise BankError(
            f"{index} not found. Build the bank first:\n"
            "    python -m song_generator.extract_words <scene>\n"
            "    (rename the clips)\n"
            "    python -m song_generator.build_bank"
        )

    entries = json.loads(index.read_text(encoding="utf-8"))
    units: list[Unit] = []
    for name, e in entries.items():
        path = words_dir / name
        if not path.is_file():
            continue
        units.append(Unit(
            name=name,
            words=e["words"],
            syllables=e["syllables"],
            duration_s=e["duration_s"],
            midi=e.get("midi"),
            # Already levelled at bake time, to a loudness target rather than
            # an RMS one. Running level_clip over it would throw that away.
            audio=(audio_io.read_wav(path) if standardised
                   else level_clip(audio_io.read_wav(path))),
            bounds_s=e.get("syllable_bounds_s", []),
            syllable_midi=e.get("syllable_midi", []),
            variant=str(e.get("variant", "")),
        ))

    if not units:
        raise BankError(f"{index} lists no clips that exist on disk.")

    units.extend(compose_words(units))

    if place_bare_syllables is None:
        place_bare_syllables = config.PLACE_BARE_SYLLABLES

    # A clip of syllables is not singable on its own, but it is raw material:
    # arrange.py cuts it into its syllables and spells whole words out of them.
    # Dropping it here threw that material away before anything could use it,
    # which silently wasted every syllable clip somebody cut by hand.
    if singable_only and not place_bare_syllables:
        singable = [u for u in units if u.is_word_like]
        if singable:
            return singable
    return units


def _crossfade(a: np.ndarray, b: np.ndarray, sr: int) -> np.ndarray:
    """Join two clips with a short overlap, so the seam does not click."""
    n = min(int(config.COMPOSE_CROSSFADE_S * sr), a.shape[1] // 2, b.shape[1] // 2)
    if n <= 0:
        return np.concatenate([a, b], axis=1)

    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    head = a[:, :-n]
    seam = a[:, -n:] * (1.0 - ramp) + b[:, :n] * ramp
    tail = b[:, n:]
    return np.concatenate([head, seam, tail], axis=1)


def compose_words(units: list[Unit]) -> list[Unit]:
    """Spell whole words out of single-syllable clips.

    A bank of syllables reaches words that were never recorded intact --
    calculator from pa + vi + aa + ni. The joins are crossfades rather than the
    singer's own transitions, so these are worth less than a real recording of
    the same word and the mapper prefers a genuine clip wherever one exists.
    They are what makes a handful of syllables cover a whole song.
    """
    import itertools

    by_syllable: dict[str, list[Unit]] = {}
    for u in units:
        if len(u.words) == 1 and u.syllables == 1:
            by_syllable.setdefault(u.words[0], []).append(u)

    composed: list[Unit] = []
    for word, spelling in config.WORD_SPELLING.items():
        takes = [by_syllable.get(part, []) for part in spelling]
        if not all(takes):
            continue

        for i, combo in enumerate(itertools.islice(itertools.product(*takes),
                                                   config.COMPOSE_MAX_PER_WORD)):
            audio = combo[0].audio
            bounds, running = [], combo[0].duration_s
            for nxt in combo[1:]:
                bounds.append(round(running, 4))
                audio = _crossfade(audio, nxt.audio, config.SAMPLE_RATE)
                running += nxt.duration_s - config.COMPOSE_CROSSFADE_S

            pitches = [c.midi for c in combo]
            known = [p for p in pitches if p is not None]
            composed.append(Unit(
                name=f"spelled:{word}:{i + 1}",
                words=[word],
                syllables=len(spelling),
                duration_s=audio.shape[1] / config.SAMPLE_RATE,
                midi=float(np.median(known)) if known else None,
                audio=audio,
                bounds_s=bounds,
                syllable_midi=list(pitches),
            ))

    return composed


# ---------------------------------------------------------------------------
# Slot cleanup
# ---------------------------------------------------------------------------

def clean_slots(notes: list[dict]) -> tuple[list[Slot], int, int]:
    """Turn raw extracted notes into slots worth putting a syllable on.

    Two corrections, both from the constants block:
      - a slot under MIN_SYLLABLE_S is an extraction blip, merged into whichever
        neighbour is closer in pitch;
      - a slot over MAX_SYLLABLE_S is a held note, split into several syllables
        rather than having one stretched absurdly across the whole thing.
    """
    slots = [Slot(n["onset_s"], n["offset_s"], n["midi"], n["phrase"],
                  n.get("rms_db", -30.0)) for n in notes]
    if not slots:
        return [], 0, 0

    merged = 0
    out: list[Slot] = []
    for slot in slots:
        if slot.dur_s >= config.MIN_SYLLABLE_S or not out:
            out.append(slot)
            continue
        # Absorb into the previous slot unless the next one is a closer pitch
        # match and starts immediately.
        out[-1].offset_s = slot.offset_s
        merged += 1

    split = 0
    final: list[Slot] = []
    for slot in out:
        if slot.dur_s <= config.MAX_SYLLABLE_S:
            final.append(slot)
            continue
        pieces = min(config.MAX_SLOT_SPLIT,
                     max(2, int(round(slot.dur_s / config.TARGET_SYLLABLE_S))))
        edges = np.linspace(slot.onset_s, slot.offset_s, pieces + 1)
        for a, b in zip(edges[:-1], edges[1:]):
            final.append(Slot(float(a), float(b), slot.midi, slot.phrase))
        split += 1

    return final, merged, split


def _split_long(group: list[Slot]) -> list[list[Slot]]:
    """Break a phrase that runs longer than a phrase should, at its widest gap.

    Silence alone cannot find the ends of continuous delivery. Rapped verses do
    not pause, so gap detection returned one 25-second phrase on a test song,
    and since density is decided per phrase, dropping that one phrase left the
    first quarter of the track wordless while the original was singing from 4s.

    Splitting at the widest internal gap is not musical analysis, it is the
    least arbitrary cut available: whatever the smallest breath in the run is,
    that is where a listener is most likely to hear a join anyway.
    """
    span = group[-1].offset_s - group[0].onset_s
    if span <= config.PHRASE_MAX_S or len(group) < 4:
        return [group]

    gaps = [(b.onset_s - a.offset_s, i + 1)
            for i, (a, b) in enumerate(zip(group, group[1:]))]
    # Keep the cut away from the very ends, so a split never leaves a stub.
    margin = max(1, len(group) // 8)
    inner = [g for g in gaps if margin <= g[1] <= len(group) - margin]
    if not inner:
        return [group]

    _, at = max(inner)
    return _split_long(group[:at]) + _split_long(group[at:])


def group_phrases(slots: list[Slot]) -> list[list[Slot]]:
    """Re-derive phrases after cleanup, so groups match the slots being filled.

    WRITES slot.phrase. This reads like a query and is not one: the slots it is
    handed come back renumbered, because a group is what the rest of the tool
    means by a phrase and nothing downstream would agree with a slot still
    carrying the number it was detected with. Idempotent, so calling it twice
    changes nothing the second time.

    The consequence worth knowing: the phrase numbers in an arrangement file
    are these, and the ones in analysis.json are the detector's. They do not
    line up, and neither is wrong.
    """
    groups: list[list[Slot]] = []
    for slot in slots:
        if groups and slot.onset_s - groups[-1][-1].offset_s <= config.PHRASE_GAP_S:
            groups[-1].append(slot)
        else:
            groups.append([slot])

    out: list[list[Slot]] = []
    for group in groups:
        out.extend(_split_long(group))

    # Renumber. A slot carries the phrase it was detected in, and both the
    # length cap and the gap rule can put slots from one detected phrase into
    # different groups. Anything reading slot.phrase afterwards then sees a
    # placement spanning two phrases when it spans one group, which is what the
    # rest of the tool means by a phrase from here on.
    for number, group in enumerate(out):
        for slot in group:
            slot.phrase = number
    return out


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def find_climaxes(groups: list[list[Slot]], min_slots: int = 1,
                  share: float | None = None) -> set[int]:
    """Which phrases are the song's peaks.

    Ranked on pitch and loudness together, since a climax is usually both
    higher and louder than what surrounds it. Each is scored against the song's
    own spread rather than an absolute threshold, so a quiet song has peaks too.

    Only phrases long enough to hold the payoff are eligible. Ranking on
    intensity alone picked two four-slot phrases in a song whose shortest
    calculator unit is five syllables, so the climax could never be placed and
    silently never was.
    """
    if not groups:
        return set()

    eligible = [i for i, g in enumerate(groups) if len(g) >= min_slots]
    if not eligible:
        return set()

    pitch = np.array([float(np.mean([s.midi for s in groups[i]])) for i in eligible])
    loud = np.array([float(np.mean([s.rms_db for s in groups[i]])) for i in eligible])

    def z(values: np.ndarray) -> np.ndarray:
        spread = values.std()
        return (values - values.mean()) / spread if spread > 1e-6 else np.zeros_like(values)

    score = (config.CLIMAX_PITCH_WEIGHT * z(pitch)
             + config.CLIMAX_LOUDNESS_WEIGHT * z(loud))

    how_many = max(config.CLIMAX_MIN_PEAKS,
                   int(round(len(groups) * (config.CLIMAX_PHRASE_SHARE
                                            if share is None else share))))
    ranked = [eligible[j] for j in np.argsort(-score)]
    return set(ranked[:how_many])


def core_words() -> set[str]:
    """The words the song is mostly made of.

    Named by the bank when it knows, since which words carry a song is a
    property of the recordings and not something a general rule can guess.
    Falling back to "short, not the shout, not the payoff" gets it right for a
    bank that has not said.
    """
    named = getattr(config, "PLAY_CORE_WORDS", None)
    if named:
        return set(named)
    return {w for w, n in config.WORD_SYLLABLES.items()
            if n <= 2 and w not in config.SHOUT_WORDS and w not in config.CLIMAX_WORDS}


# Every origin unit_origin can return, and the knob that prices it. A clip the
# singer sang whole is free, so it has no knob.
#
# Listed rather than built from the origin name at the point of use. Looking up
# f"{origin}_cost" meant a renamed or newly added origin silently priced itself
# at zero and the preference vanished with nothing to notice, which is the
# failure this repo keeps finding and keeps refusing to leave in place.
ORIGIN_COSTS = {
    "recorded": None,
    "slice": "slice_cost",
    "joined": "joined_cost",
    "spelled": "spelled_cost",
}


def unit_origin(unit: Unit) -> str:
    """How this unit came to exist, from most to least like a real recording.

      recorded  a clip the singer sang, transitions and all
      slice     one word cut out of such a clip. Genuine audio of that word.
      joined    real words crossfaded into an order nobody sang
      spelled   a word assembled out of syllable fragments

    They are not equal and should not compete as if they were. A whole take
    carries the singer's own movement between syllables; a word built out of
    "pas" and "ka" carries a join where that movement should be.
    """
    name = unit.name
    if name.startswith("spelled:"):
        return "spelled"
    if name.startswith(("invented:", "joined:")):
        return "joined"
    return "slice" if "#" in name else "recorded"


def crown_words() -> set[str]:
    """Long words that finish a combination rather than carry it."""
    return {w for w, n in config.WORD_SYLLABLES.items()
            if n > 2 and w not in config.SHOUT_WORDS and w not in config.CLIMAX_WORDS}


def _choose(units: list[Unit], remaining: int, span_s: float,
            rng: random.Random, last: str | None,
            allow_shouts: bool = True, allow_climax: bool = False,
            targets: list[float] | None = None,
            play: dict | None = None,
            used: dict[str, int] | None = None,
            shift_cap: float | None = None) -> Unit | None:
    """Pick a unit that fits the slots left.

    Three things compete: how naturally the clip fills the time it is given, a
    preference for longer units, and -- when targets are supplied -- how far the
    clip would have to be shifted to reach the notes it would cover.
    """
    fits = [u for u in units if u.syllables <= remaining]
    if not allow_climax:
        # aah and calculator are a payoff, not vocabulary. Outside a peak the
        # song runs on bravo, tango, delta and kilometer.
        fits = [u for u in fits if not u.is_climax]
    if not allow_shouts:
        fits = [u for u in fits if not u.is_bare_shout] or fits
    if not fits:
        return None

    pool = [u for u in fits if u.name != last] or fits

    # Rank by how little the clip would have to be rushed or dragged to fill
    # the slots it would occupy. Ties and near-ties are broken randomly so a
    # song does not come out using the same clip over and over.
    def pitch_cost(u: Unit) -> float:
        """How far this take would have to move, and whether it must fold.

        Measured over the notes the unit would actually cover rather than the
        whole phrase, since a two-syllable word and an eight-syllable one face
        different stretches of melody.
        """
        if not (config.PREFER_NEAREST_SOURCE_PITCH and targets and u.midi is not None):
            return 0.0

        from .pitchshift import fold_shift

        covered = targets[:u.syllables] or targets[:1]
        want = float(np.mean(covered))
        raw = want - u.midi

        # The bank's own cap, not the tool's. Choosing a unit is where the
        # folding is predicted, and predicting it against 12 for a bank that
        # folds at 6 kept picking units the planner believed landed exactly
        # and which were folded on the way out.
        cap = config.SHIFT_CAP_SEMITONES if shift_cap is None else shift_cap
        cost = abs(fold_shift(raw, cap)) / 12.0
        if abs(raw) > cap:
            # Folding changes the register, so the melody survives only in
            # part. That is a worse outcome than a merely large shift.
            cost += config.FOLD_PENALTY
        return config.PITCH_FIT_WEIGHT * cost

    core = core_words()
    crown = crown_words()

    def role_cost(u: Unit) -> float:
        """What each kind of word is worth, as a proportion of the song.

        The bank has four roles and they are not interchangeable. A handful of
        short words carry the thing; one long word is rarer and finishes a
        combination; the shout and the payoff are seasoning. Left to compete on
        duration fit alone the shout wins constantly, because it is a third of
        the recordings and fits any slot, and the song becomes shouting.
        """
        if not play:
            return 0.0
        words = u.words
        cost = 0.0
        if any(w in config.SHOUT_WORDS for w in words):
            cost += float(play.get("shout_cost", 0.0))
        if any(w in crown for w in words):
            cost += float(play.get("crown_cost", 0.0))
        if any(w not in core and w not in crown
               and w not in config.SHOUT_WORDS and w not in config.CLIMAX_WORDS
               for w in words):
            # A fourth kind: words the bank has but the song is not about.
            # They read as novel, so the bonus for saying something new picks
            # them up hard, and they crowd out the words that carry the thing.
            cost += float(play.get("extra_cost", 0.0))
        if words and all(w in core for w in words):
            cost -= float(play.get("core_bonus", 0.0))
        knob = ORIGIN_COSTS[unit_origin(u)]
        if knob is not None:
            cost += float(play.get(knob, 0.0))
        return cost

    def variety_cost(u: Unit) -> float:
        """What it costs to say the same thing again.

        The bank holds fourteen recorded phrases, so without this one clip that
        happens to fit the song's typical slot wins most of them and the track
        becomes a loop. Charged per label rather than per clip, since hearing
        the same words in a different take is the same repetition to a
        listener.
        """
        if not play or used is None:
            return 0.0
        seen = used.get(u.label, 0)
        if seen == 0:
            return -float(play.get("unused_bonus", 0.0))
        return float(play.get("repeat_penalty", 0.0)) * np.log1p(seen)

    def mismatch(u: Unit) -> float:
        allotted = span_s * (u.syllables / remaining) if remaining else span_s
        if allotted <= 0:
            return float("inf")
        # Longer units are preferred at equal fit: fewer, longer placements
        # read as singing, while many short ones read as chatter.
        length_bonus = config.PREFER_LONGER_UNITS * np.log(u.syllables + 1)
        return (abs(np.log(u.duration_s / allotted)) - length_bonus
                + pitch_cost(u) + variety_cost(u) + role_cost(u))

    band = float(play.get("tie_band", 0.35)) if play else 0.35
    ranked = sorted(pool, key=mismatch)
    top = [u for u in ranked if mismatch(u) <= mismatch(ranked[0]) + band] or ranked[:1]
    return rng.choice(top)


def plan_words(slots: list[Slot], units: list[Unit], seed: int | None = None,
               play: dict | None = None, shift_cap: float | None = None) -> Plan:
    """Lay units onto slots. With `play`, vary what gets said and how often.

    `play` is a parameter set from config.PLAY_LEVELS. Passing None keeps the
    behaviour this had before playfulness existed, which is what the tests for
    everything else depend on.
    """
    def pick(*args, **kwargs):
        """_choose with this bank's cap already attached.

        Bound here rather than passed at each of the five call sites below,
        because the cap is a property of the run and forgetting it at one of
        them would leave that one predicting the folding against the wrong
        number with nothing to show for it.
        """
        kwargs.setdefault("shift_cap", shift_cap)
        return _choose(*args, **kwargs)

    rng = random.Random(config.WORD_ROTATION_SEED if seed is None else seed)
    forced = config.WORD_SEQUENCE
    plan = Plan(slots_total=len(slots))

    by_label = {u.label: u for u in units}
    forced_queue: list[str] = list(forced) if forced else []
    used: dict[str, int] = {}

    groups = group_phrases(slots)
    smallest_climax = min((u.syllables for u in units if u.is_climax), default=1)
    climax_share = float(play.get("climax_share", config.CLIMAX_PHRASE_SHARE)) if play         else config.CLIMAX_PHRASE_SHARE
    climaxes = find_climaxes(groups, min_slots=smallest_climax, share=climax_share)

    # Leave some phrases instrumental. Filling every one makes the words a
    # texture rather than events, which buries them on a smooth song.
    #
    # Peaks are exempt: thinning at random was silently discarding the very
    # phrases reserved for calculator, so the payoff never arrived at all.
    fill = float(play.get("phrase_fill", config.PHRASE_FILL)) if play else config.PHRASE_FILL
    # The opening is never thinned away. Whatever the density setting, the
    # first thing a listener decides is whether this song has words in it, and
    # a track that stays instrumental through its first phrase has answered no
    # by the time it starts. Peaks are exempt for the same kind of reason.
    keep = {id(g) for i, g in enumerate(groups) if i in climaxes or i == 0}
    if fill >= 1.0:
        keep = {id(g) for g in groups}
    else:
        # Never drop two phrases in a row. Thinning at random once removed two
        # adjacent phrases from an eleven-phrase song, leaving an 8.7 second
        # hole where the original was singing throughout -- audible as a dead
        # section rather than as breathing space. Spacing the drops keeps the
        # same overall density while guaranteeing the gaps stay short.
        ordinary = [i for i in range(len(groups)) if i not in climaxes]
        want_drop = max(0, len(ordinary) - (int(round(len(groups) * fill)) - len(keep)))
        max_gap = float(play.get("max_gap_s", 0.0)) if play else 0.0

        def silence_around(i: int, dropped: set[int]) -> float:
            """How long the hole would be if this phrase went too.

            Counted across neighbours already dropped, because two short
            phrases dropped either side of a kept one still read as one long
            absence once the kept phrase is over.
            """
            first = last = i
            while (first - 1) in dropped:
                first -= 1
            while (last + 1) in dropped:
                last += 1
            return groups[last][-1].offset_s - groups[first][0].onset_s

        dropped: set[int] = set()
        for i in rng.sample(ordinary, len(ordinary)):
            if len(dropped) >= want_drop:
                break
            if (i - 1) in dropped or (i + 1) in dropped:
                continue
            # Capping phrase length turned eleven phrases into thirty on a test
            # song, so the same drop RATE went from about two holes to seven.
            # A proportion of phrases stopped meaning a proportion of silence
            # once phrases became short, and the result was audible as the song
            # dropping out while the original was still singing.
            if max_gap > 0.0 and silence_around(i, dropped) > max_gap:
                continue
            dropped.add(i)

        keep |= {id(groups[i]) for i in ordinary if i not in dropped}

    shout_share = float(play.get("shout_share", config.SHOUT_MAX_SHARE)) if play         else config.SHOUT_MAX_SHARE
    shout_budget = max(1, int(round(len(groups) * shout_share)))
    shouts_used = 0

    # A chant: the same thing said several times running, on purpose. Not the
    # same as the monotony repeat_penalty exists to stop, which is one clip
    # quietly winning every slot because it happens to fit best. This is chosen,
    # it is bounded, and it ends.
    chant_label: str | None = None
    chant_left = 0

    for index, group in enumerate(groups):
        if id(group) not in keep:
            plan.slots_dropped += len(group)
            continue

        # A peak may take one; anywhere else it is an occasional joke, which
        # only works while it stays unexpected.
        at_peak = index in climaxes and rng.random() < config.CLIMAX_USE_CHANCE
        wildcard_chance = float(play.get("climax_wildcard", config.CLIMAX_WILDCARD_CHANCE))             if play else config.CLIMAX_WILDCARD_CHANCE
        wildcard = index not in climaxes and rng.random() < wildcard_chance
        climax_left = 1 if (at_peak or wildcard) else 0

        i = 0
        last: str | None = None
        while i < len(group):
            remaining = len(group) - i
            span_s = group[-1].offset_s - group[i].onset_s
            targets = [s.midi for s in group[i:]]

            if remaining == 1:
                # A one-syllable unit -- a shouted "aah" -- fits the leftover
                # slot exactly, which beats every ODD_SLOT_POLICY fudge. But it
                # is the ONLY thing that fits, so without a budget it wins every
                # odd phrase in the song and the shout stops being an event.
                filler = None
                if shouts_used < shout_budget and climax_left > 0:
                    filler = pick([u for u in units if u.syllables == 1],
                                      1, span_s, rng, last, allow_climax=True,
                                      targets=targets, play=play, used=used)
                if filler is not None:
                    shouts_used += 1
                    covered = group[i:i + 1]
                    plan.placements.append(Placement(
                        unit=filler,
                        onset_s=covered[0].onset_s,
                        slot_span_s=covered[0].dur_s,
                        play_s=filler.duration_s,
                        n_slots=1,
                        phrase=covered[0].phrase,
                        slots=list(covered),
                    ))
                    plan.slots_used += 1
                    used[filler.label] = used.get(filler.label, 0) + 1
                    break

                # Only into a placement in THIS phrase. Reaching for the last
                # placement whatever it was held a word across a phrase gap,
                # which contradicts the rule the gap exists to enforce, and made
                # the placement cover slots that are not next to each other.
                mergeable = (config.ODD_SLOT_POLICY == "merge_last"
                             and plan.placements
                             and plan.placements[-1].phrase == group[i].phrase)
                if mergeable:
                    prev = plan.placements[-1]
                    prev.slot_span_s = group[i].offset_s - prev.onset_s
                    prev.play_s = min(prev.unit.duration_s, prev.slot_span_s)
                    prev.n_slots += 1
                    plan.slots_used += 1
                elif config.ODD_SLOT_POLICY == "truncate":
                    plan.slots_dropped += 1
                else:
                    plan.slots_dropped += 1
                break

            unit = by_label.get(forced_queue.pop(0)) if forced_queue else None

            # At a peak, take the payoff first rather than merely allowing it.
            # Left to compete on time-fit alone it usually lost, and a climax
            # that never arrives is worse than none at all.
            if unit is None and climax_left > 0:
                payoff = [u for u in units if u.is_climax]
                # The shout and the payoff travel together by default. Slicing
                # the bank into words gave the planner a dozen ways to say the
                # payoff alone, and they outvoted the one recording that says
                # it properly, so the pairing has to be asked for rather than
                # left to compete.
                detach = float(play.get("detach_pairing", 1.0)) if play else 1.0
                if rng.random() >= detach:
                    paired = [u for u in payoff if u.is_shout_pairing
                              and u.syllables <= remaining]
                    payoff = paired or payoff
                unit = pick(payoff, remaining, span_s, rng, last,
                               allow_climax=True, targets=targets,
                               play=play, used=used)

            if unit is None and chant_left > 0 and chant_label:
                again = [u for u in units
                         if u.label == chant_label and u.syllables <= remaining]
                if again:
                    # Inside a chant the repeat penalty is exactly wrong, so the
                    # pool is narrowed to the chanted label and it cannot fire.
                    unit = pick(again, remaining, span_s, rng, None,
                                   allow_shouts=True, allow_climax=True,
                                   targets=targets, play=play, used=None)
                    chant_left -= 1
                else:
                    chant_left = 0

            if unit is None:
                unit = pick(units, remaining, span_s, rng, last,
                               allow_shouts=shouts_used < shout_budget,
                               allow_climax=False, targets=targets,
                               play=play, used=used)
            if unit is not None and unit.is_bare_shout:
                shouts_used += 1
            if unit is not None and unit.is_climax:
                climax_left -= 1
            if unit is None:
                plan.slots_dropped += remaining
                break

            # A shout announcing the unit that follows. Expected before the
            # payoff and occasionally not, which is where the surprise lives:
            # an ear set up for calculator and given kilometer is the joke.
            # Skipped when a recorded aah+calculator already fits, since that clip
            # carries the singer's own transition and cannot be bettered by
            # butting two clips together.
            if (not unit.is_bare_shout
                    and not (unit.words[:1] and unit.words[0] in config.SHOUT_WORDS)
                    and shouts_used < shout_budget
                    and remaining > unit.syllables):
                bias = config.SHOUT_LEAD_IN_CLIMAX_BIAS if unit.is_climax else 1.0
                if rng.random() < min(0.95, config.SHOUT_LEAD_IN_CHANCE * bias):
                    lead = pick([u for u in units if u.is_bare_shout],
                                   1, group[i].dur_s, rng, last, allow_climax=True,
                                   targets=targets, play=play, used=used)
                    if lead is not None:
                        plan.placements.append(Placement(
                            unit=lead,
                            onset_s=group[i].onset_s,
                            slot_span_s=group[i].dur_s,
                            play_s=lead.duration_s,
                            n_slots=1,
                            phrase=group[i].phrase,
                            slots=[group[i]],
                        ))
                        plan.slots_used += 1
                        shouts_used += 1
                        used[lead.label] = used.get(lead.label, 0) + 1
                        i += 1
                        remaining -= 1

                        # Rarely, nothing follows. The ear is set up for filth
                        # and gets a gap instead. Only the unit that would have
                        # come next is dropped: abandoning the whole phrase
                        # made the joke cost several seconds of song, which is
                        # how wild ended up with almost no words in it.
                        if (play and not unit.is_climax
                                and rng.random() < float(play.get("bare_shout", 0.0))):
                            skip = min(unit.syllables, len(group) - i)
                            plan.slots_dropped += skip
                            i += skip
                            last = lead.name
                            continue

                        if remaining < unit.syllables:
                            last = lead.name
                            continue

            covered = group[i:i + unit.syllables]
            start = covered[0].onset_s
            end = covered[-1].offset_s
            plan.placements.append(Placement(
                unit=unit,
                onset_s=start,
                slot_span_s=end - start,
                play_s=unit.duration_s,
                n_slots=unit.syllables,
                phrase=covered[0].phrase,
                slots=list(covered),
            ))
            plan.slots_used += unit.syllables
            used[unit.label] = used.get(unit.label, 0) + 1
            last = unit.name
            i += unit.syllables

            # Say it again. Started after a placement rather than before one, so
            # a chant is always a repeat of something the song just said.
            if play and chant_left <= 0 and rng.random() < float(play.get("chant_chance", 0.0)):
                chant_label = unit.label
                chant_left = rng.randint(1, max(1, int(play.get("chant_max", 2))))

    # Nothing may run into whatever comes next, and nothing may ring past the
    # slots it was given. Only the first was enforced, so the LAST placement in
    # a phrase had nothing after it to be cut against and sounded for its whole
    # length: a four second clip over a 1.7 second span, straight through the
    # gap the original singer left and into the next phrase.
    for placement in plan.placements:
        placement.play_s = min(placement.play_s, placement.slot_span_s)
    for a, b in zip(plan.placements, plan.placements[1:]):
        a.play_s = min(a.play_s, max(0.0, b.onset_s - a.onset_s))

    return plan


def plan_sequence(slots: list[Slot], units: list[Unit],
                  reading_speed: float = 1.0, split: bool = True,
                  keep_order: bool = False) -> Plan:
    """Replay the bank in the order it was recorded. plan_words chooses;
    this recites.

    Built for a bank whose words were spoken in an order that carries the
    meaning, so the one placement rule is that order. Units are sorted by
    their variant field, the zero-padded index build_bank --raw writes in
    chronological order, compared as strings so the padding does the sorting,
    with the name breaking ties. When the units run out the sequence starts
    again from the first, so a long song against a short bank keeps going.

    No randomness anywhere: no seed, no draws, no coverage redraw, because
    there is no vocabulary to cover. Two calls over the same slots and units
    are the same plan.

    What happens once the order is decided belongs to recite, which lays the
    units out at the cursor's pace and is documented there. This function is
    the ordering and the rotation; arrange.realise runs the same placement
    over units a saved arrangement names instead.

    reading_speed is the pace of the reciting: 1.0 is the pace the words were
    spoken at, lower is slower. A slower pace widens every span, so it also
    advances through the bank more slowly, which means fewer times around for
    the same song. It is bounded to the paces the stretch engine delivers,
    the reciprocals of TIME_STRETCH_RANGE, because the cursor advances by
    each unit's duration at this pace and the renderer clamps its stretch to
    that range: an unbounded pace would advance the cursor by a duration the
    renderer refuses to produce, and every word would sound on top of the
    next. bank.json refuses an out-of-range declaration by name; this bound
    is for the callers that pass a speed directly.
    """
    from .banks import deliverable_speed

    # keep_order is the shuffled strategy handing over an order it drew from
    # the seed. Sorting it back into the recording's order would undo exactly
    # what was asked for.
    ordered = (list(units) if keep_order
               else sorted(units, key=lambda u: (u.variant, u.name)))
    if not ordered:
        return Plan(slots_total=len(slots))

    return recite(slots, lambda k: ordered[k % len(ordered)],
                  deliverable_speed(reading_speed), split=split)


def recite(slots: list[Slot], next_unit: Callable[[int], Unit | None],
           speed: float, split: bool = True) -> Plan:
    """Lay a run of units along the slots at the reciting cursor's pace.

    Where a recitation is actually placed, for both the planner and replay.
    It lives in one function because they have to agree exactly: a recited
    onset is deliberately not its slot's onset, so the time in a saved
    arrangement does not say which slot the word was placed on, and replay
    anchoring each line to the nearest slot found a different one. The take
    that came back was not the take that was rendered. Two copies of a rule
    can disagree; one cannot.

    next_unit(k) supplies the unit for the k-th placement, or None when there
    are none left. plan_sequence rotates through the bank; arrange.realise
    hands over the units a saved arrangement names, in its order.

    Nothing is shortened to fit its slots. A spoken word cut short stops
    being the word, so every placement's target is the time the unit needs to
    be said at this speed: its natural duration over that speed, written to
    target_s and play_s both.

    One time cursor decides the rest. Inside a phrase a unit starts
    RECITE_WORD_GAP_S after the previous one stops sounding, wherever the
    melody's next note happens to fall, because keeping the words coming
    matters more than reproducing how the original singer phrased them; the
    melody supplies pitch alone. At a phrase boundary it starts on that
    phrase's first note instead, since the singer paused long enough there
    for group_phrases to call it a new phrase, which is where a sentence
    ends.

    The cursor is the single authority on collision, so a unit that needs
    more time than its slots give simply takes longer to clear, and a slot
    the cursor has already passed is sung over rather than landed on.
    Nothing overlaps and nothing is starved, and there is no backtracking to
    do either of those jobs badly.

    Phrases come from group_phrases and a placement's slots never cross a
    group, the same as plan_words, so a phrase number in the log means the
    same thing whichever planner wrote it.
    """
    plan = Plan(slots_total=len(slots))
    flat = [slot for group in group_phrases(slots) for slot in group]

    at = 0                  # how many placements have been made
    cursor = float("-inf")  # when the previous word stops sounding
    last_phrase: int | None = None
    i = 0
    while i < len(flat):
        slot = flat[i]
        same_phrase = slot.phrase == last_phrase
        if slot.onset_s < cursor - 1e-9:
            # The previous word is still sounding here. Sung over, not
            # silent, so it counts as used; it is simply nothing's landing.
            plan.slots_used += 1
            i += 1
            continue

        unit = next_unit(at)
        if unit is None:
            break
        at += 1
        target = unit.duration_s / speed

        covered = [slot]
        j = i + 1
        while (j < len(flat) and flat[j].phrase == slot.phrase
               and flat[j].onset_s < slot.onset_s + target - 1e-9):
            covered.append(flat[j])
            j += 1

        # Where the word actually starts.
        #
        # Not the note's onset. Reciting to a melody means keeping the
        # delivery's own rhythm and borrowing only its pitch: two words said
        # 90ms apart are said 90ms apart here too, whatever the singer was
        # doing in between. Waiting for the next note instead inserted 45
        # seconds of silence into a three minute song and chopped every
        # phrase into note-shaped pieces.
        #
        # A phrase boundary is the exception, and it is why this reads the
        # phrase rather than a gap threshold. The singer stopped there long
        # enough for group_phrases to call it a new phrase, so the recitation
        # stops too and picks up on the next phrase's first note. Small rests
        # inside a phrase are sung straight through; long ones end the
        # sentence.
        onset = slot.onset_s
        if same_phrase and cursor != float("-inf"):
            # Straight after the previous word, wherever the melody's next note
            # happens to be. Keeping the words coming is what this is for.
            onset = cursor + config.RECITE_WORD_GAP_S

        plan.placements.append(Placement(
            unit=unit,
            onset_s=onset,
            slot_span_s=covered[-1].offset_s - covered[0].onset_s,
            play_s=target,
            n_slots=len(covered),
            phrase=slot.phrase,
            # One landing note per syllable. The remaining covered slots
            # widen the span without giving the word another note, the same
            # shape merge_last leaves behind, and the same cut realise makes
            # when it rebuilds a line, so a replay lands on the same notes.
            slots=list(covered[:max(1, unit.syllables)]),
            split=split,
            target_s=target,
        ))
        plan.slots_used += len(covered)
        cursor = onset + target
        last_phrase = slot.phrase
        i = j

    return plan


# ---------------------------------------------------------------------------
# Render and mix
# ---------------------------------------------------------------------------

def unit_fit(p: Placement) -> float:
    """How much of the original melody this unit would carry, if shifted.

    A syllable inside the shift cap lands exactly on the melody's note and
    counts fully. One that had to be octave-folded carries the right note name
    and the melody's shape but sits in the wrong octave, so it only partly
    mimics the original -- recognisably the tune, still audibly wrong.
    """
    fits = []
    for i, slot in enumerate(p.slots):
        source = p.unit.source_midi(i)
        if source is None:
            continue
        raw = abs(slot.midi - source)
        cap = p.shift_cap if p.shift_cap is not None else config.SHIFT_CAP_SEMITONES
        fits.append(1.0 if raw <= cap else config.FOLDED_FIT)
    return float(np.mean(fits)) if fits else 0.0


def mimicry(plan: Plan) -> float:
    """How much of the original singing survives in the result, 0.0 to 1.0."""
    if not plan.placements:
        return 0.0
    got = sum(unit_fit(p) for p in plan.placements if p.do_shift)
    return got / len(plan.placements)


def decide_by_mimicry(plan: Plan, target: float, mode: str | None = None,
                      seed: int | None = None) -> float:
    """Shift as many units as it takes to reach the wanted mimicry.

    How many that is depends on the song: one whose melody sits far above the
    bank folds most of its syllables, each carrying less of the original, so
    more units have to be shifted to reach the same result.
    """
    mode = mode or config.SHIFT_MIX_MODE
    placements = plan.placements
    if not placements:
        return 0.0

    for p in placements:
        p.do_shift = False

    if mode == "furthest":
        # Shift the closest-fitting units first: most mimicry per unit, and it
        # leaves the big jumps clashing, which is where they are funniest.
        order = sorted(placements, key=lambda p: p.raw_distance())
    else:
        rng = random.Random(config.WORD_ROTATION_SEED if seed is None else seed)
        order = list(placements)
        rng.shuffle(order)

    n = len(placements)
    running = 0.0
    for p in order:
        if running / n >= target:
            break
        p.do_shift = True
        running += unit_fit(p)

    return mimicry(plan)


def decide_shifts(plan: Plan, mix: float | None = None, mode: str | None = None,
                  seed: int | None = None, target_mimicry: float | None = None) -> None:
    """Mark which units sing along and which keep their own pitch.

    Everything shifted sounds sung and stops being funny; nothing shifted is
    funny but never sounds like singing. The setting worth using is in between,
    and which units are left alone matters as much as how many.
    """
    placements = plan.placements
    if not placements:
        return

    # A mimicry target overrides the raw count, because it is the one that means
    # the same thing across songs.
    if mix is None:
        target = config.MIMICRY if target_mimicry is None else target_mimicry
        if target is not None:
            decide_by_mimicry(plan, target, mode, seed)
            return

    mix = config.SHIFT_MIX if mix is None else mix
    mode = mode or config.SHIFT_MIX_MODE

    if mix >= 1.0:
        for p in placements:
            p.do_shift = True
        return
    if mix <= 0.0:
        for p in placements:
            p.do_shift = False
        return

    n_shift = int(round(len(placements) * mix))

    if mode == "furthest":
        # Shift the ones closest to their target; leave the big jumps alone.
        order = sorted(placements, key=lambda p: p.raw_distance())
    else:
        rng = random.Random(config.WORD_ROTATION_SEED if seed is None else seed)
        order = list(placements)
        rng.shuffle(order)

    for i, p in enumerate(order):
        p.do_shift = i < n_shift


def build_segments(p: Placement) -> tuple[list, float]:
    """Where each piece of this unit lands, how long it sounds, how far it moves.

    Three fittings, told apart by the explicit contract on the placement
    rather than by guessing which planner made it:

      split, no target   sung. Each syllable is pinned to its own slot and
                         stretched to that slot's length, which is what
                         following a melody means. Where the melody rests
                         between two notes of the same word, the earlier
                         syllable holds its vowel across the rest rather than
                         stopping, so the word is not cut in half. See
                         WORDS_SING_THROUGH.
      split, target      recited. The syllables are laid end to end and
                         stretched to fill target_s, each still taking a
                         slot's pitch. Pinning them to slots is wrong for
                         speech: a slot longer than its syllable leaves a
                         hole after every word, heard as a stutter rather
                         than as slow speech.
      never split        one segment for the whole clip, one shift from the
                         first slot, stretched toward the target. It still
                         follows the tune; it simply is not taken apart to
                         do so.
    """
    from .pitchshift import Segment, fold_shift, fold_unit

    spans = p.unit.syllable_spans()
    lo, hi = config.TIME_STRETCH_RANGE

    if not p.split:
        source = p.unit.midi
        first = p.slots[0] if p.slots else None
        shift = (0.0 if (source is None or first is None)
                 else fold_shift(first.midi - source, p.shift_cap))
        p.shifts = [shift]
        natural = p.unit.duration_s or 1e-3
        target = p.target_s if p.target_s is not None else natural
        # Clamped to the engine's range but NOT floored at 1.0. A span too
        # short for the clip used to leave it at natural length, which meant
        # it played over the word after it. A word said a little faster is
        # better than two words at once, and better than one cut off.
        ratio = min(max(target / natural, lo), hi)
        out = natural * ratio
        return [Segment(
            src_start_s=0.0,
            src_end_s=p.unit.duration_s,
            out_start_s=0.0,
            out_dur_s=out,
            semitones=shift,
        )], max(out, 1e-3)

    segments, shifts = [], []
    origin = p.onset_s

    if p.target_s is None:
        pieces = []
        for i, (src_a, src_b) in enumerate(spans):
            if i >= len(p.slots):
                break
            slot = p.slots[i]
            source = p.unit.source_midi(i)
            if source is None:
                continue

            raw = config.SHOUT_KEEP_RAW and p.unit.is_shout_syllable(i)
            pieces.append((src_a, src_b, slot, raw,
                           0.0 if raw else slot.midi - source))

        # One octave for the whole word rather than one per syllable, so the
        # intervals inside it are the ones the melody asked for. A shout keeps
        # its own pitch, so it neither votes on the octave nor takes it.
        folded = iter(fold_unit([w for *_, raw, w in pieces if not raw],
                                p.shift_cap))

        for i, (src_a, src_b, slot, raw, _) in enumerate(pieces):
            shift = 0.0 if raw else next(folded)
            shifts.append(shift)

            # A shout keeps its own length as well as its own pitch: stretching
            # it to fit a slot smooths out the attack that makes it a shout.
            out_dur = (src_b - src_a) if raw else slot.dur_s

            # Hold the vowel until the next syllable of this word starts. Where
            # the melody leaves a rest between two notes, stopping on the note
            # cut the word in half with real silence. Only where another
            # syllable follows: the last one must be allowed to stop, or every
            # word would end on a held vowel running into the next.
            hold_to = None
            if config.WORDS_SING_THROUGH and not raw and i + 1 < len(pieces):
                hold_to = pieces[i + 1][2].onset_s - origin

            segments.append(Segment(
                src_start_s=src_a,
                src_end_s=src_b,
                out_start_s=slot.onset_s - origin,
                out_dur_s=out_dur,
                semitones=shift,
                glide=not raw,
                sustain_to_s=hold_to,
            ))

        total = (p.slots[-1].offset_s - origin) if p.slots else p.unit.duration_s
        p.shifts = shifts
        return segments, max(total, 1e-3)

    # Recited. The stretch is computed over the syllables that keep no fixed
    # length of their own: a raw shout keeps its recorded length, because
    # stretching it smooths out the attack that makes it a shout, so the
    # others share out whatever time the target leaves over. Every syllable
    # advances the cursor, raw ones included, which is what keeps a shout
    # from sounding on top of its neighbours.
    raw_flags = [config.SHOUT_KEEP_RAW and p.unit.is_shout_syllable(i)
                 for i in range(len(spans))]
    raw_s = sum(b - a for (a, b), raw in zip(spans, raw_flags) if raw)
    flex_s = sum(b - a for (a, b), raw in zip(spans, raw_flags) if not raw)
    ratio = min(max((p.target_s - raw_s) / flex_s, lo), hi) if flex_s > 0 else 1.0

    # Reciting never drops a syllable. Past the last landing slot the last
    # slot's pitch is reused, and a syllable with no measured pitch sounds
    # unshifted rather than not at all: half a spoken word is not a shorter
    # word. None marks the syllables that take no shift, and so take no part in
    # choosing the word's octave either.
    wanted: list[float | None] = []
    for i in range(len(spans)):
        landing = p.slots[min(i, len(p.slots) - 1)] if p.slots else None
        source = p.unit.source_midi(i)
        wanted.append(None if raw_flags[i] or landing is None or source is None
                      else landing.midi - source)
    folded = iter(fold_unit([w for w in wanted if w is not None], p.shift_cap))

    cursor = 0.0
    for i, (src_a, src_b) in enumerate(spans):
        raw = raw_flags[i]
        shift = 0.0 if wanted[i] is None else next(folded)
        shifts.append(shift)

        out_dur = (src_b - src_a) * (1.0 if raw else ratio)
        segments.append(Segment(
            src_start_s=src_a,
            src_end_s=src_b,
            out_start_s=cursor,
            out_dur_s=out_dur,
            semitones=shift,
            glide=not raw,
        ))
        cursor += out_dur

    p.shifts = shifts
    return segments, max(cursor, 1e-3)


def precompute_shifted(plan: Plan, sr: int = config.SAMPLE_RATE,
                       engine: str | None = None) -> dict[int, np.ndarray]:
    """Shift every unit once, whether or not this variant will use it.

    Resynthesis is the only expensive part of rendering, and which units a
    variant shifts is purely a selection over the same set. Doing the work once
    makes every additional mimicry setting almost free, so there is no reason
    to make anyone choose a single one up front.

    The cache is per arrangement, and a two-level run pays for it twice. That
    looks like an obvious saving and is not: measured across two songs, the
    conservative and wild arrangements share 2 to 3 percent of their
    (unit, shift) work, because different words land on different notes. A
    cache keyed across levels would carry the bookkeeping and save nothing.
    """
    from .pitchshift import render_unit

    cache: dict[int, np.ndarray] = {}
    for idx, p in enumerate(plan.placements):
        if not p.slots or p.unit.duration_s <= 0:
            continue
        if config.SHOUT_KEEP_RAW and p.unit.is_bare_shout:
            continue  # never resynthesised, so nothing to precompute
        segments, total = build_segments(p)
        if not segments:
            continue
        mono = audio_io.to_mono(p.unit.audio)
        voiced = render_unit(mono, sr, segments, total, engine)
        cache[idx] = np.stack([voiced, voiced]).astype(np.float32)
    return cache


def render(plan: Plan, n_samples: int, sr: int = config.SAMPLE_RATE,
           shift: bool = True, engine: str | None = None,
           cache: dict[int, np.ndarray] | None = None) -> np.ndarray:
    bus = np.zeros((2, n_samples), dtype=np.float32)
    fade = max(1, int(config.EDGE_FADE_S * sr))

    for idx, p in enumerate(plan.placements):
        # A shout on its own never goes near the vocoder. There is nothing to
        # gain -- it has no melody to follow -- and everything to lose, since
        # resynthesis is what turns a shout into a melted vowel.
        raw_shout = config.SHOUT_KEEP_RAW and p.unit.is_bare_shout

        if shift and p.do_shift and not raw_shout and p.slots and p.unit.duration_s > 0:
            if cache is not None and idx in cache:
                clip = np.array(cache[idx], dtype=np.float32)
            else:
                from .pitchshift import render_unit

                segments, total = build_segments(p)
                if segments:
                    mono = audio_io.to_mono(p.unit.audio)
                    voiced = render_unit(mono, sr, segments, total, engine)
                    clip = np.stack([voiced, voiced]).astype(np.float32)
                else:
                    clip = np.array(p.unit.audio, dtype=np.float32)
        elif (p.target_s is not None and not raw_shout and p.unit.duration_s > 0
                and abs(p.target_s - p.unit.duration_s) > 1e-3):
            # The paced duration is the planner's decision, not the shifter's,
            # so it holds when this unit keeps its own pitch too: one whole-clip
            # segment at zero semitones, stretched toward the target exactly as
            # the shifted branch would stretch it. Truncating to play_s here,
            # clamped to the clip's natural length, is what made reading_speed
            # apply only to shifted units and put the stutter back at --no-shift.
            from .pitchshift import Segment, render_unit

            lo, hi = config.TIME_STRETCH_RANGE
            natural = p.unit.duration_s
            out = natural * min(max(p.target_s / natural, lo), hi)
            segment = Segment(src_start_s=0.0, src_end_s=natural,
                              out_start_s=0.0, out_dur_s=out, semitones=0.0)
            mono = audio_io.to_mono(p.unit.audio)
            voiced = render_unit(mono, sr, [segment], out, engine)
            clip = np.stack([voiced, voiced]).astype(np.float32)
        else:
            audio = p.unit.audio
            if audio.shape[0] == 1:
                audio = np.repeat(audio, 2, axis=0)
            take = min(audio.shape[1], max(1, int(p.play_s * sr)))
            clip = np.array(audio[:, :take], dtype=np.float32)
            if take < audio.shape[1] and take > fade:
                clip[:, -fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)

        if clip.shape[0] == 1:
            clip = np.repeat(clip, 2, axis=0)
        if clip.shape[1] > fade * 2:
            ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
            clip[:, :fade] *= ramp
            clip[:, -fade:] *= ramp[::-1]

        start = int(p.onset_s * sr)
        end = min(n_samples, start + clip.shape[1])
        if end > start:
            bus[:, start:end] += clip[:, :end - start]

    return bus


def _normalise(audio: np.ndarray, target_lufs: float, sr: int) -> np.ndarray:
    from .detect import integrated_lufs

    loudness = integrated_lufs(audio, sr)
    if not np.isfinite(loudness):
        return audio
    return (audio * (10 ** ((target_lufs - loudness) / 20))).astype(np.float32)


def mix(word_bus: np.ndarray, instrumental: np.ndarray,
        sr: int = config.SAMPLE_RATE,
        word_bus_lufs: float | None = None) -> np.ndarray:
    """Words over the bed. word_bus_lufs lets a bank sit at its own level.

    None keeps config.WORD_BUS_LUFS, which is what every bank did before one
    of them needed to be louder, so passing nothing changes nothing.
    """
    target = config.WORD_BUS_LUFS if word_bus_lufs is None else word_bus_lufs
    words = _normalise(word_bus, target, sr)
    bed = _normalise(instrumental, config.INSTRUMENTAL_LUFS, sr)

    n = min(words.shape[1], bed.shape[1])
    out = words[:, :n] + bed[:, :n]

    ceiling = 10 ** (config.OUTPUT_PEAK_CEILING_DB / 20)
    peak = float(np.abs(out).max())
    if peak > ceiling:
        out *= ceiling / peak
    return out.astype(np.float32)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def report(plan: Plan, units: list[Unit]) -> str:
    lines = ["  word placement"]
    add = lines.append

    if not plan.placements:
        add("    nothing placed -- no slots survived cleanup")
        return "\n".join(lines)

    used: dict[str, int] = {}
    for p in plan.placements:
        used[p.unit.label] = used.get(p.unit.label, 0) + 1

    stretches = np.array([p.stretch_needed for p in plan.placements])
    # Read off the placements, because the bank may declare its own. Printing
    # the config default beside a max the bank capped lower said two numbers
    # that disagreed and blamed neither.
    caps = {p.shift_cap for p in plan.placements if p.shift_cap is not None}
    cap = caps.pop() if len(caps) == 1 else config.SHIFT_CAP_SEMITONES
    truncated = sum(1 for p in plan.placements if p.play_s < p.unit.duration_s - 1e-3)

    add(f"    bank              {len(units)} units")
    add(f"    placed            {len(plan.placements)} units over "
        f"{plan.slots_used}/{plan.slots_total} slots")
    if plan.slots_dropped:
        add(f"    left silent       {plan.slots_dropped} slots "
            f"(ODD_SLOT_POLICY={config.ODD_SLOT_POLICY!r})")
    add(f"    slot cleanup      {plan.merged} merged as blips, {plan.split} held notes split")
    add(f"    truncated         {truncated} units cut short by the next entry")
    add(f"    time fit          median {np.median(stretches):.2f}x natural speed "
        f"(1.00 = the clip already fits)")
    add(f"                      {int((np.abs(np.log(stretches)) < 0.3).sum())} of "
        f"{len(stretches)} within 30% of a natural fit")
    add("    units used        " + ", ".join(
        f"{k} x{v}" for k, v in sorted(used.items(), key=lambda kv: -kv[1])))

    singing = sum(1 for p in plan.placements if p.do_shift)
    ceiling = sum(unit_fit(p) for p in plan.placements) / len(plan.placements)
    add("")
    add("  how much it mimics the original")
    add(f"    mimicry           {mimicry(plan):.2f}  "
        f"(0 = ignores the tune, 1 = sings it exactly)")
    add(f"    sings along       {singing} of {len(plan.placements)} units "
        f"({singing / len(plan.placements) * 100:.0f}%), mode {config.SHIFT_MIX_MODE!r}")
    add(f"    ceiling           {ceiling:.2f} -- the most this song can mimic even")
    add("                      with every unit shifted, because octave-folded")
    add("                      syllables only carry the tune in part")

    shifts = np.array([s for p in plan.placements if p.do_shift for s in p.shifts])
    if shifts.size:
        raw = np.array([
            slot.midi - (p.unit.source_midi(i) or 0.0)
            for p in plan.placements
            for i, slot in enumerate(p.slots)
            if p.unit.source_midi(i) is not None
        ])
        add("")
        add("  pitch shift")
        add(f"    requested         median {np.median(np.abs(raw)):.1f} semitones, "
            f"max {np.abs(raw).max():.1f}")
        add(f"    after folding     median {np.median(np.abs(shifts)):.1f} semitones, "
            f"max {np.abs(shifts).max():.1f} "
            f"(cap {cap:g})")
        folded = int((np.abs(raw) > cap).sum())
        add(f"    octave-folded     {folded} of {len(raw)} syllables "
            f"({folded / len(raw) * 100:.0f}%) were too far to shift directly")
        add(f"    engine            {config.SHIFT_ENGINE}, "
            f"formants held at {config.FORMANT_SCALE:.2f}")
    return "\n".join(lines)
