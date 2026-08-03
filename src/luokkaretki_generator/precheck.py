"""Guess what each candidate clip contains, to make reviewing them bearable.

    python -m luokkaretki_generator.precheck

Three states, kept visibly separate so they never blur together:

    paska1.wav                              yours. Confirmed. Never touched.
    AI_paska__kirby2__c07__1.42-1.98.wav    a machine guess. Needs your ear.
    TODO_4syl__muumit__c03__0.50-1.10.wav   no guess. Unknown.

Only a clip with no prefix counts. Neither AI_ nor TODO_ parses as a bank word,
so an unverified guess is structurally incapable of reaching the bank however
confident it looked.

Two things make the guessing better than transcribing whole sources:

  Syllable count constrains the answer. A two-nucleus clip can only be paska,
  perse or pillu; a four-nucleus one only pornolehti or paviaani -- pa-vi-aa-ni
  and por-no-leh-ti being the same length, that is the one pair the recogniser
  actually has to tell apart. The measurement comes from the envelope, so it is
  independent of anything the model thinks.

  Clips are transcribed in batches. Whisper pads every input to thirty seconds
  whatever its length, so a half-second clip costs as much as a full window.
  Packing many clips into one window with silence between them, then mapping
  words back by timestamp, is around twenty times faster for the same audio.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np

from . import audio_io, config
from .build_bank import parse_phrase
from .extract_words import _count_syllables, _envelope_db
from .label_words import normalise
from .util import resolve_device

AI = "AI_"
TODO = "TODO_"
PREFIXES = (AI, TODO)

PROMPT = "paska, perse, pillu, pornolehti, paviaani"

STRONG = 0.72
WEAK = 0.45

BATCH_SECONDS = 24.0    # Whisper's window is 30s; leave room for the padding
GAP_S = 0.7             # silence between clips, so word timings stay separable


@dataclass
class Clip:
    path: Path
    syllables: int = 0
    duration_s: float = 0.0
    offset_s: float = 0.0          # where it sits in its batch
    heard: list[str] = field(default_factory=list)
    words: list[str] = field(default_factory=list)
    score: float = 0.0

    @property
    def is_shout(self) -> bool:
        return self.syllables <= 1 and self.duration_s >= config.SHOUT_MIN_S

    @property
    def label(self) -> str:
        if self.words:
            name = "-".join(self.words)
            return name if self.score >= STRONG else f"{name}-weak"
        if self.is_shout:
            return "shout"
        return f"{self.syllables}syl"

    @property
    def prefix(self) -> str:
        return AI if self.words else TODO


def candidates_for(syllables: int) -> list[str]:
    """Bank words matching the measured length, allowing one syllable either way.

    The nucleus counter is approximate -- a rolled consonant adds a bump, a
    slurred join hides one -- so an exact match would be too strict.
    """
    out = [w for w, n in config.WORD_SYLLABLES.items()
           if w not in config.SHOUT_WORDS and abs(n - syllables) <= 1]
    return out or [w for w in config.WORD_SYLLABLES if w not in config.SHOUT_WORDS]


def match_single(heard: str, syllables: int) -> tuple[list[str], float]:
    if not heard:
        return [], 0.0
    best, score = None, 0.0
    for target in candidates_for(syllables):
        ratio = SequenceMatcher(None, heard, target).ratio()
        if len(heard) >= 4 and target.startswith(heard):
            ratio = max(ratio, 0.75)
        if ratio > score:
            best, score = target, ratio
    return ([best], score) if best and score >= WEAK else ([], score)


def match_sequence(tokens: list[str], syllables: int) -> tuple[list[str], float]:
    """Match a run of heard tokens onto a sequence of bank words."""
    if not tokens:
        return [], 0.0

    joined = "".join(tokens)
    parsed = parse_phrase(joined)
    if parsed is not None and parsed[0]:
        return parsed[0], 0.9

    words, scores = [], []
    for token in tokens:
        got, score = match_single(token, config.WORD_SYLLABLES.get(token, 2))
        if got:
            words.extend(got)
            scores.append(score)

    if not words:
        return match_single(joined, syllables)

    total = sum(config.WORD_SYLLABLES[w] for w in words)
    agreement = 1.0 - min(1.0, abs(total - syllables) / max(syllables, 1))
    return words, float(np.mean(scores)) * (0.6 + 0.4 * agreement)


def measure(path: Path) -> tuple[int, float]:
    mono = audio_io.to_mono(audio_io.read_wav(path))
    dur = mono.shape[0] / config.SAMPLE_RATE
    env = _envelope_db(mono, config.SAMPLE_RATE, 256)
    return _count_syllables(env, 256 / config.SAMPLE_RATE), dur


def make_batches(clips: list[Clip]) -> list[list[Clip]]:
    batches, current, used = [], [], 0.0
    for clip in clips:
        cost = clip.duration_s + GAP_S
        if current and used + cost > BATCH_SECONDS:
            batches.append(current)
            current, used = [], 0.0
        clip.offset_s = used
        current.append(clip)
        used += cost
    if current:
        batches.append(current)
    return batches


def render_batch(batch: list[Clip], sr: int) -> np.ndarray:
    total = int((batch[-1].offset_s + batch[-1].duration_s + GAP_S) * sr)
    buffer = np.zeros(total, dtype=np.float32)
    for clip in batch:
        mono = audio_io.to_mono(audio_io.read_wav(clip.path))
        start = int(clip.offset_s * sr)
        end = min(total, start + len(mono))
        buffer[start:end] = mono[:end - start]
    return buffer


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="luokkaretki_generator.precheck",
        description="Guess each candidate clip's contents to speed up reviewing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--folder", type=Path, default=Path("words/candidates"))
    p.add_argument("--model", default="large-v3")
    p.add_argument("--device", default=None)
    p.add_argument("--limit", type=int, default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    folder = args.folder
    if not folder.is_dir():
        print(f"error: {folder} not found", file=sys.stderr)
        return 2

    # Anything without a prefix is yours. It is never read, renamed or
    # considered here -- your labelling is the one thing no automatic pass
    # is allowed to touch.
    everything = sorted(folder.glob("*.wav"))
    pending = [p for p in everything if p.name.startswith(PREFIXES)]
    confirmed = [p for p in everything if not p.name.startswith(PREFIXES)]
    if args.limit:
        pending = pending[:args.limit]

    if not pending:
        print(f"  nothing left to check in {folder}.")
        return 0

    import whisper

    device = resolve_device(args.device)
    print(f"  {len(pending)} clips to check, {args.model} on {device}")
    print(f"  {len(confirmed)} confirmed by you -- untouched\n")

    clips = []
    for path in pending:
        syllables, dur = measure(path)
        clips.append(Clip(path=path, syllables=syllables, duration_s=dur))

    speech = [c for c in clips if not c.is_shout]
    batches = make_batches(speech)
    print(f"  {len(speech)} to transcribe in {len(batches)} batches "
          f"({sum(1 for c in clips if c.is_shout)} shouts skipped -- a recogniser")
    print("  has nothing useful to say about non-verbal noise)\n")

    model = whisper.load_model(args.model, device=device)
    sr = config.SAMPLE_RATE

    for i, batch in enumerate(batches, start=1):
        audio = render_batch(batch, sr)
        try:
            result = model.transcribe(
                audio, language="fi", temperature=0.0, word_timestamps=True,
                condition_on_previous_text=False, initial_prompt=PROMPT,
            )
        except Exception as exc:
            print(f"    batch {i} failed ({exc})", file=sys.stderr)
            continue

        for segment in result.get("segments", []):
            for w in segment.get("words", []):
                mid = (float(w["start"]) + float(w["end"])) / 2
                for clip in batch:
                    if clip.offset_s <= mid <= clip.offset_s + clip.duration_s:
                        token = normalise(w.get("word", ""))
                        if token:
                            clip.heard.append(token)
                        break

        if i % 5 == 0 or i == len(batches):
            print(f"    [{i:>3}/{len(batches)}] batches", flush=True)

    for clip in speech:
        clip.words, clip.score = match_sequence(clip.heard, clip.syllables)

    renamed = 0
    for clip in clips:
        stem = clip.path.stem
        for prefix in PREFIXES:
            if stem.startswith(prefix):
                stem = stem[len(prefix):]
                break
        tail = "__".join(stem.split("__")[1:]) or stem
        target = folder / f"{clip.prefix}{clip.label}__{tail}.wav"
        if target == clip.path or target.exists():
            continue
        clip.path.rename(target)
        renamed += 1

    guessed = [c for c in clips if c.words]
    strong = sum(1 for c in guessed if c.score >= STRONG)

    print(f"\n  folder    {folder.resolve()}")
    print(f"  {len(guessed)} guessed ({strong} confident), "
          f"{len(clips) - len(guessed)} still unknown, {renamed} renamed")
    print(f"  {len(confirmed)} confirmed by you, untouched")

    by_label: dict[str, int] = {}
    for c in clips:
        by_label[c.prefix + c.label] = by_label.get(c.prefix + c.label, 0) + 1
    print("\n  by tag:")
    for label, n in sorted(by_label.items(), key=lambda kv: -kv[1])[:20]:
        print(f"    {n:>4}  {label}")

    print(f"\n  {AI}* are guesses to check. {TODO}* had no guess at all.")
    print("  Renaming a clip -- dropping the prefix -- is what confirms it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
