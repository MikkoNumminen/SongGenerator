"""Who is singing when, so several banks can take turns in one song.

A posse cut has four or five people on it, and a render sung by one bank
flattens all of them into one voice. With --voices the tool sings each turn
from a different bank instead, switching wherever the original singer changes.

Nothing here decides anything musical. The turns are measured from the vocal
stem, the same way every other decision in this tool is taken from the
original singer:

1. The stem is cut into overlapping windows, and only windows that are mostly
   inside notes the melody analysis found are kept. The rest is bleed.
2. Each window becomes a speaker embedding (ECAPA, via speechbrain).
3. The embeddings are clustered by cosine distance, with no speaker count
   given, because nobody knows it in advance.
4. Consecutive windows in one cluster are a run. A run shorter than
   TURN_MIN_S is a handover straddled by a window, not a singer, and is
   absorbed into its neighbours.

The voices then alternate at every change: the first turn gets the first
voice, the next turn the next, and round again. Not one voice per singer,
because with five singers and two voices, mapping singers to voices can put
two different singers next to each other in the same voice, and then the
change the listener is supposed to hear does not happen.

The measurement is cached as turns.json beside the stems, together with the
settings that produced it and a fingerprint of the vocal stem it was measured
on. It is reused while both match, so a boundary moved by hand in the file
stays moved, and stems separated again are measured again.

Only detect() needs the model. Everything else is plain arithmetic on times
and is what the tests exercise.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from . import config
from .mapping import Placement, Plan

TURNS_FILE = "turns.json"

# The sample rate ECAPA was trained at. A property of the model, not a knob.
_EMBED_SR = 16000


class TurnError(RuntimeError):
    pass


@dataclass
class Turn:
    start_s: float
    end_s: float
    speaker: int


def settings() -> dict:
    """What a cached measurement has to have been made with to be reused."""
    return {
        "model": config.TURN_MODEL,
        "window_s": config.TURN_WINDOW_S,
        "hop_s": config.TURN_HOP_S,
        "min_voiced": config.TURN_MIN_VOICED,
        "distance": config.TURN_DISTANCE,
        "min_turn_s": config.TURN_MIN_S,
    }


# ---------------------------------------------------------------------------
# From window labels to turns
# ---------------------------------------------------------------------------

def runs(centres: Sequence[float], labels: Sequence[int]) -> list[list]:
    """Consecutive windows with one label, as [first centre, last centre, label]."""
    out: list[list] = []
    for c, lab in zip(centres, labels):
        if out and out[-1][2] == lab:
            out[-1][1] = c
        else:
            out.append([c, c, int(lab)])
    return out


def _length(run: list, hop_s: float) -> float:
    # A single window still covers one hop of the timeline.
    return run[1] - run[0] + hop_s


def _merge_neighbours(rs: list[list]) -> list[list]:
    out: list[list] = []
    for r in rs:
        if out and out[-1][2] == r[2]:
            out[-1][1] = r[1]
        else:
            out.append(list(r))
    return out


def absorb_short(rs: list[list], min_s: float, hop_s: float) -> list[list]:
    """Fold every run shorter than min_s into the runs beside it.

    Shortest first, because absorbing one run can join its neighbours into a
    single long one, and a short run next to it may then have nothing left to
    be a blip between. Between two runs of one singer a blip becomes that
    singer; between two different singers it is split at its middle, which is
    the best guess at where the handover it straddles happened.
    """
    rs = _merge_neighbours([list(r) for r in rs])
    while len(rs) > 1:
        i = min(range(len(rs)), key=lambda k: _length(rs[k], hop_s))
        if _length(rs[i], hop_s) >= min_s:
            break
        blip = rs.pop(i)
        before = rs[i - 1] if i > 0 else None
        after = rs[i] if i < len(rs) else None
        if before is None:
            after[0] = blip[0]
        elif after is None:
            before[1] = blip[1]
        elif before[2] == after[2]:
            before[1] = after[1]
            rs.pop(i)
        else:
            middle = (blip[0] + blip[1]) / 2
            before[1] = middle
            after[0] = middle
        rs = _merge_neighbours(rs)
    return rs


def to_turns(rs: list[list], duration_s: float) -> list[Turn]:
    """Runs as turns that cover the whole song with no gap.

    A handover is placed halfway between the last window of one singer and the
    first of the next. The first turn reaches back to the start of the song
    and the last one on to its end, so every moment belongs to somebody.
    """
    if not rs:
        return []
    turns = []
    for k, r in enumerate(rs):
        start = 0.0 if k == 0 else (rs[k - 1][1] + r[0]) / 2
        end = duration_s if k == len(rs) - 1 else (r[1] + rs[k + 1][0]) / 2
        turns.append(Turn(round(start, 3), round(end, 3), r[2]))
    return turns


def from_labels(centres: Sequence[float], labels: Sequence[int],
                duration_s: float, min_s: float | None = None,
                hop_s: float | None = None) -> list[Turn]:
    """Window labels to turns. Separate from detect() so it can be tested."""
    min_s = config.TURN_MIN_S if min_s is None else min_s
    hop_s = config.TURN_HOP_S if hop_s is None else hop_s
    return to_turns(absorb_short(runs(centres, labels), min_s, hop_s), duration_s)


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def voiced_windows(notes: list[dict], duration_s: float) -> list[float]:
    """Start times of the windows worth embedding: mostly inside sung notes."""
    grid = np.zeros(int(duration_s * 100) + 2, dtype=bool)  # 10 ms
    for n in notes:
        lo = int(n["onset_s"] * 100)
        hi = int((n["onset_s"] + n["dur_s"]) * 100) + 1
        grid[lo:hi] = True
    starts = []
    t = 0.0
    while t + config.TURN_WINDOW_S <= duration_s:
        lo, hi = int(t * 100), int((t + config.TURN_WINDOW_S) * 100)
        if grid[lo:hi].mean() >= config.TURN_MIN_VOICED:
            starts.append(round(t, 3))
        t += config.TURN_HOP_S
    return starts


def detect(vocal: np.ndarray, sr: int, notes: list[dict],
           device: str = "cpu") -> list[Turn]:
    """Measure the turns in a vocal stem. Needs speechbrain and its model."""
    try:
        from speechbrain.inference.speaker import EncoderClassifier
    except ImportError as exc:
        raise TurnError(
            "telling singers apart needs speechbrain, which is optional.\n"
            "    Install it into this venv with: pip install -e .[voices]"
        ) from exc
    import librosa
    import torch
    from sklearn.cluster import AgglomerativeClustering

    from .audio_io import to_mono

    mono = librosa.resample(to_mono(vocal).astype(np.float32),
                            orig_sr=sr, target_sr=_EMBED_SR)
    duration = len(mono) / _EMBED_SR
    starts = voiced_windows(notes, duration)
    if len(starts) < 2:
        raise TurnError(
            f"only {len(starts)} window of the vocal is sung enough to tell"
            " whose voice it is, so there are no turns to take."
        )

    # speechbrain names a device "cuda:0"; a bare "cuda" gets a warning.
    run_on = "cuda:0" if device == "cuda" else device
    model = EncoderClassifier.from_hparams(
        source=config.TURN_MODEL, run_opts={"device": run_on})
    width = int(config.TURN_WINDOW_S * _EMBED_SR)
    chunks = [mono[int(s * _EMBED_SR):int(s * _EMBED_SR) + width] for s in starts]
    embeddings = []
    with torch.inference_mode():
        for i in range(0, len(chunks), 64):
            batch = torch.from_numpy(np.stack(chunks[i:i + 64])).to(run_on)
            embeddings.append(model.encode_batch(batch).squeeze(1).cpu().numpy())
    E = np.concatenate(embeddings)
    E /= np.linalg.norm(E, axis=1, keepdims=True)

    labels = AgglomerativeClustering(
        n_clusters=None, distance_threshold=config.TURN_DISTANCE,
        metric="cosine", linkage="average").fit_predict(E)
    centres = [s + config.TURN_WINDOW_S / 2 for s in starts]
    return from_labels(centres, labels, duration)


def fingerprint(vocal: np.ndarray) -> str:
    """Which vocal stem the turns were measured on.

    The settings alone cannot say: separating a song again, with --force or
    another separator, writes new stems to the same paths, and turns measured
    on the old stem would then be laid over the new one without a word.
    """
    import hashlib

    return hashlib.sha1(np.ascontiguousarray(vocal, dtype=np.float32)
                        .tobytes()).hexdigest()


def _read_turns(path: Path, saved) -> list[Turn]:
    """The turns in a cache file, refused by name when they cannot be used.

    The file is documented as editable by hand, so a missing key, a misspelt
    field or a boundary moved past its neighbour is a person's typo and gets
    an error naming the file, not a traceback.
    """
    try:
        turns = [Turn(float(t["start_s"]), float(t["end_s"]), int(t["speaker"]))
                 for t in saved["turns"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise TurnError(
            f"{path} cannot be read as turns ({exc!r}).\n"
            "    Each turn needs start_s, end_s and speaker. Delete the file"
            " to measure the turns again.") from exc
    if not turns:
        raise TurnError(f"{path} holds no turns. Delete it to measure again.")
    for a, b in zip(turns, turns[1:]):
        if not (a.start_s < a.end_s <= b.start_s):
            raise TurnError(
                f"{path}: the turn starting at {a.start_s:g}s ends at"
                f" {a.end_s:g}s, which does not come before the next one at"
                f" {b.start_s:g}s. Turns must be in order and not overlap.")
    return turns


def load_or_detect(work: Path, vocal: np.ndarray, sr: int, notes: list[dict],
                   device: str = "cpu") -> tuple[list[Turn], bool]:
    """The cached turns when they were measured the way config says on this
    vocal stem, else fresh.

    Returns the turns and whether they came from the cache.
    """
    path = Path(work) / TURNS_FILE
    stem = fingerprint(vocal)
    if path.is_file():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise TurnError(f"{path} is not valid JSON: {exc}") from exc
        if (isinstance(saved, dict) and saved.get("settings") == settings()
                and saved.get("vocal") == stem):
            return _read_turns(path, saved), True

    turns = detect(vocal, sr, notes, device)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps({"settings": settings(), "vocal": stem,
                               "turns": [asdict(t) for t in turns]}, indent=2),
                   encoding="utf-8")
    tmp.replace(path)
    return turns, False


# ---------------------------------------------------------------------------
# Handing turns to voices
# ---------------------------------------------------------------------------

def voice_of(turns: list[Turn], n_voices: int, t: float) -> int:
    """Which voice owns the moment t. The voices alternate turn by turn."""
    for k, turn in enumerate(turns):
        if t < turn.end_s:
            return k % n_voices
    return (len(turns) - 1) % n_voices if turns else 0


def take_turns(plans: list[Plan], turns: list[Turn],
               slots: list[list] | None = None) -> tuple[Plan, list[int]]:
    """One plan, each placement taken from the voice whose turn it starts in.

    Every voice was arranged over the whole song, so each already has a
    placement wherever the song has words. Keeping each voice's own placements
    inside its own turns gives every turn a complete arrangement, rather than
    one voice's leftovers.

    A placement is owned by where it starts. A word begun just before a
    handover finishes in its own voice; cutting it at the boundary would chop
    the word, and a moment of overlap at a handover is what two singers do.

    slots, one list per voice, is the grid each voice was planned on. Voices
    swallowing at different paces plan on different grids, so the slots the
    combined plan had to fill are each voice's own slots inside its own turns.
    Without them, the first voice's total stands in for all of them.

    Returns the plan and the voice index of every placement in it.
    """
    kept: list[tuple[Placement, int]] = []
    for v, plan in enumerate(plans):
        kept += [(p, v) for p in plan.placements
                 if voice_of(turns, len(plans), p.onset_s) == v]
    kept.sort(key=lambda pv: pv[0].onset_s)
    if slots is not None:
        total = sum(1 for v, grid in enumerate(slots) for s in grid
                    if voice_of(turns, len(plans), s.onset_s) == v)
    else:
        total = plans[0].slots_total if plans else 0
    combined = Plan(
        placements=[p for p, _ in kept],
        slots_used=sum(p.n_slots for p, _ in kept),
        slots_total=total,
        # slots_dropped is counted per arrangement and cannot be attributed to
        # a turn afterwards, so it is left out rather than estimated.
    )
    return combined, [v for _, v in kept]
