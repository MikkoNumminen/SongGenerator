"""Hunt for a shout-then-word pattern, e.g. HEEEI PA-VI-AA-NI.

    python -m song_generator.hunt
    python -m song_generator.hunt --syllables 4 --top 60

Classifying eight hundred clips one at a time is slow and, on sung shouting,
not very accurate. Searching for one specific shape is neither.

"HEEEI PA-VI-AA-NI" has an envelope you can see without understanding a word of
it: one long held nucleus, then four short ones in quick succession. That is a
template, and templates can be matched on the envelope alone -- no model, no
GPU, a few milliseconds per clip. Only the shortlist is then transcribed, which
turns an hour of recognition into a couple of minutes.

The same search finds any shout-plus-word pattern; --syllables sets how many
beats follow the shout.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks

from . import audio_io, config
from .util import resolve_device

HOP = 256

# Spellings that all mean the same held shout. Kept here rather than in the
# bank because they are one sound, however it gets written down.
SHOUT_SPELLINGS = ("heei", "heeei", "aaah", "eei", "hei", "aah", "ee")


@dataclass
class Hit:
    path: Path
    score: float
    lead_s: float          # how long the opening held nucleus runs
    following: int         # nuclei after it
    duration_s: float
    heard: str = ""

    @property
    def summary(self) -> str:
        return (f"{self.score:.2f}  lead {self.lead_s * 1000:4.0f}ms + "
                f"{self.following} syllables  ({self.duration_s:.2f}s)")


def nuclei(mono: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """Syllable nucleus frames and the smoothed envelope they came from."""
    import librosa

    rms = librosa.feature.rms(y=mono, frame_length=4 * HOP, hop_length=HOP)[0]
    env = 20 * np.log10(rms + 1e-9)
    env = uniform_filter1d(env, size=max(1, int(round(config.SYLLABLE_SMOOTH_S * sr / HOP))),
                           mode="nearest")
    peaks, _ = find_peaks(
        env,
        distance=max(1, int(round(config.SYLLABLE_MIN_SEP_S * sr / HOP))),
        prominence=config.SYLLABLE_PROMINENCE_DB,
    )
    return peaks, env


def score_clip(path: Path, want_following: int) -> Hit | None:
    """How well this clip matches 'one held shout, then N syllables'."""
    sr = config.SAMPLE_RATE
    mono = audio_io.to_mono(audio_io.read_wav(path))
    dur = len(mono) / sr
    if dur < 0.35 or dur > 4.0:
        return None

    peaks, env = nuclei(mono, sr)
    if len(peaks) < 2:
        return None

    hop_s = HOP / sr
    # The lead nucleus runs until the envelope first dips clearly before the
    # next peak; its length is what separates a shout from a normal syllable.
    first, second = peaks[0], peaks[1]
    valley = first + int(np.argmin(env[first:second])) if second > first else first
    lead_s = float((valley - max(0, first - int(0.05 / hop_s))) * hop_s)
    following = len(peaks) - 1

    # A held lead. Below SHOUT_MIN_S it is just another syllable.
    lead_score = float(np.clip(lead_s / config.SHOUT_MIN_S, 0.0, 1.5)) / 1.5
    # The right number of beats after it.
    count_score = 1.0 - min(1.0, abs(following - want_following) / max(want_following, 1))
    # Those beats should be quick and even, as a word is.
    gaps = np.diff(peaks[1:]) * hop_s if following >= 2 else np.array([0.25])
    evenness = 1.0 - min(1.0, float(np.std(gaps)) / 0.15) if len(gaps) > 1 else 0.5

    score = 0.45 * lead_score + 0.40 * count_score + 0.15 * evenness
    if lead_s < 0.12 or count_score <= 0:
        return None
    return Hit(path=path, score=score, lead_s=lead_s, following=following, duration_s=dur)


def looks_like_target(heard: str, word: str) -> bool:
    flat = re.sub(r"[^a-zåäö]", "", heard.lower())
    if word in flat:
        return True
    # Recognisers routinely drop the leading shout or mangle its spelling, so
    # accept the word arriving on its own too.
    from difflib import SequenceMatcher
    return any(SequenceMatcher(None, chunk, word).ratio() >= 0.7
               for chunk in re.findall(r"[a-zåäö]{4,}", flat))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="song_generator.hunt",
        description="Find shout-then-word clips, e.g. HEEEI PA-VI-AA-NI.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--folder", type=Path, default=Path("words/candidates"))
    p.add_argument("--word", default="calculator", help="the word expected after the shout")
    p.add_argument("--syllables", type=int, default=None,
                   help="syllables in that word [default: from the bank]")
    p.add_argument("--top", type=int, default=60, help="how many to transcribe")
    p.add_argument("--model", default="large-v3")
    p.add_argument("--device", default=None)
    p.add_argument("--no-asr", action="store_true", help="rank on the envelope only")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    folder = args.folder
    if not folder.is_dir():
        print(f"error: {folder} not found", file=sys.stderr)
        return 2

    want = args.syllables or config.WORD_SYLLABLES.get(args.word, 4)

    # Confirmed clips carry no prefix and are never touched.
    pending = [p for p in sorted(folder.glob("*.wav"))
               if p.name.startswith(("AI_", "TODO_"))]
    if not pending:
        print("  nothing left to search.")
        return 0

    print(f"  searching {len(pending)} clips for a held shout + {want} syllables")

    hits = [h for h in (score_clip(p, want) for p in pending) if h]
    hits.sort(key=lambda h: -h.score)
    print(f"  {len(hits)} match the shape; taking the top {min(args.top, len(hits))}\n")

    shortlist = hits[:args.top]

    if not args.no_asr and shortlist:
        import whisper

        device = resolve_device(args.device)
        print(f"  transcribing the shortlist with {args.model} on {device}")
        model = whisper.load_model(args.model, device=device)
        for i, hit in enumerate(shortlist, start=1):
            try:
                result = model.transcribe(
                    str(hit.path), language="fi", temperature=0.0,
                    condition_on_previous_text=False,
                    initial_prompt=f"{args.word}, hei, aah",
                )
                hit.heard = result.get("text", "").strip()
            except Exception as exc:
                print(f"    {hit.path.name}: failed ({exc})", file=sys.stderr)
            if i % 20 == 0 or i == len(shortlist):
                print(f"    [{i:>3}/{len(shortlist)}]", flush=True)

    confirmed = [h for h in shortlist if h.heard and looks_like_target(h.heard, args.word)]

    renamed = 0
    for hit in shortlist:
        matched = hit in confirmed
        label = f"aah-{args.word}" if matched else f"shout{want}"
        stem = hit.path.stem
        for prefix in ("AI_", "TODO_"):
            if stem.startswith(prefix):
                stem = stem[len(prefix):]
                break
        tail = "__".join(stem.split("__")[1:]) or stem
        rank = "" if matched else f"{hit.score:.2f}_".replace(".", "")
        target = folder / f"AI_{label}__{rank}{tail}.wav"
        if target != hit.path and not target.exists():
            hit.path.rename(target)
            hit.path = target
            renamed += 1

    print(f"\n  folder    {folder.resolve()}")
    print(f"  {len(confirmed)} clips look like \"{args.word}\" after a shout")
    print(f"  {len(shortlist) - len(confirmed)} more have the right shape but did not confirm")
    print(f"  {renamed} renamed\n")

    if confirmed:
        print(f"  best matches -- listen to these first:")
        for hit in confirmed[:25]:
            print(f"    {hit.summary}   {hit.path.name}")
    else:
        print("  best by shape alone:")
        for hit in shortlist[:15]:
            print(f"    {hit.summary}   {hit.path.name}")

    print(f"\n  AI_eee-{args.word}__* are the likely hits. Rename one to confirm it:")
    print(f"      ->  aah{args.word}1.wav      (kept whole, shout and word together)")
    print(f"  Keeping the shout attached is worth it: the clip then carries the")
    print(f"  real transition into the word, which cannot be rebuilt by splicing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
