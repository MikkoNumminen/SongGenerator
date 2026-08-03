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

    @property
    def label(self) -> str:
        return "+".join(self.words)


@dataclass
class Slot:
    onset_s: float
    offset_s: float
    midi: float
    phrase: int

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

def load_bank(words_dir: Path = Path("words")) -> list[Unit]:
    index = words_dir / "words.json"
    if not index.is_file():
        raise BankError(
            f"{index} not found. Build the bank first:\n"
            "    python -m luokkaretki.extract_words <scene>\n"
            "    (rename the clips)\n"
            "    python -m luokkaretki.build_bank"
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
            audio=audio_io.read_wav(path),
        ))

    if not units:
        raise BankError(f"{index} lists no clips that exist on disk.")
    return units


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
    slots = [Slot(n["onset_s"], n["offset_s"], n["midi"], n["phrase"]) for n in notes]
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


def group_phrases(slots: list[Slot]) -> list[list[Slot]]:
    """Re-derive phrases after cleanup, so groups match the slots being filled."""
    groups: list[list[Slot]] = []
    for slot in slots:
        if groups and slot.onset_s - groups[-1][-1].offset_s <= config.PHRASE_GAP_S:
            groups[-1].append(slot)
        else:
            groups.append([slot])
    return groups


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def _choose(units: list[Unit], remaining: int, span_s: float,
            rng: random.Random, last: str | None) -> Unit | None:
    """Pick a unit that fits the slots left, preferring a natural time fit."""
    fits = [u for u in units if u.syllables <= remaining]
    if not fits:
        return None

    pool = [u for u in fits if u.name != last] or fits

    # Rank by how little the clip would have to be rushed or dragged to fill
    # the slots it would occupy. Ties and near-ties are broken randomly so a
    # song does not come out using the same clip over and over.
    def mismatch(u: Unit) -> float:
        allotted = span_s * (u.syllables / remaining) if remaining else span_s
        if allotted <= 0:
            return float("inf")
        return abs(np.log(u.duration_s / allotted))

    ranked = sorted(pool, key=mismatch)
    top = [u for u in ranked if mismatch(u) <= mismatch(ranked[0]) + 0.35] or ranked[:1]
    return rng.choice(top)


def plan_words(slots: list[Slot], units: list[Unit], seed: int | None = None) -> Plan:
    rng = random.Random(config.WORD_ROTATION_SEED if seed is None else seed)
    forced = config.WORD_SEQUENCE
    plan = Plan(slots_total=len(slots))

    by_label = {u.label: u for u in units}
    forced_queue = list(forced) if forced else []

    for group in group_phrases(slots):
        i = 0
        last: str | None = None
        while i < len(group):
            remaining = len(group) - i
            span_s = group[-1].offset_s - group[i].onset_s

            if remaining == 1:
                # Every unit in the bank is an even number of syllables, so a
                # phrase of odd length always ends here and nowhere else.
                if config.ODD_SLOT_POLICY == "merge_last" and plan.placements:
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

            unit = (by_label.get(forced_queue.pop(0)) if forced_queue else None) \
                or _choose(units, remaining, span_s, rng, last)
            if unit is None:
                plan.slots_dropped += remaining
                break

            start = group[i].onset_s
            end = group[i + unit.syllables - 1].offset_s
            plan.placements.append(Placement(
                unit=unit,
                onset_s=start,
                slot_span_s=end - start,
                play_s=unit.duration_s,
                n_slots=unit.syllables,
                phrase=group[i].phrase,
            ))
            plan.slots_used += unit.syllables
            last = unit.name
            i += unit.syllables

    # Nothing may run into whatever comes next.
    for a, b in zip(plan.placements, plan.placements[1:]):
        a.play_s = min(a.play_s, max(0.0, b.onset_s - a.onset_s))

    return plan


# ---------------------------------------------------------------------------
# Render and mix
# ---------------------------------------------------------------------------

def render(plan: Plan, n_samples: int, sr: int = config.SAMPLE_RATE) -> np.ndarray:
    bus = np.zeros((2, n_samples), dtype=np.float32)
    fade = max(1, int(config.EDGE_FADE_S * sr))

    for p in plan.placements:
        audio = p.unit.audio
        if audio.shape[0] == 1:
            audio = np.repeat(audio, 2, axis=0)

        take = min(audio.shape[1], max(1, int(p.play_s * sr)))
        clip = np.array(audio[:, :take], dtype=np.float32)

        if take < audio.shape[1] and take > fade:
            clip[:, -fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)

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
        sr: int = config.SAMPLE_RATE) -> np.ndarray:
    words = _normalise(word_bus, config.WORD_BUS_LUFS, sr)
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
    return "\n".join(lines)
