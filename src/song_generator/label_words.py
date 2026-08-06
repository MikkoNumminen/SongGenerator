"""Pre-fill labels.tsv by running local speech recognition over the vocal.

    python -m song_generator.label_words

Transcribes the separated vocal with Whisper, then keeps only the words that
fuzzy-match the bank (bravo, tango, delta, kilometer, calculator) and writes
their timings into labels.tsv. Everything else the recogniser produced is
discarded rather than reported: the goal is to locate five known words, not to
transcribe the scene.

Treat the output as a first draft. Whisper is trained on speech, not singing,
and Finnish is not one of its strongest languages -- a sung word is routinely
returned as something spelled quite differently. That is why matching is fuzzy
against a five-word closed vocabulary rather than exact, and why every match is
printed with its similarity so you can see which ones to distrust.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import config
from .build_bank import LabelError, _find_vocal
from .util import resolve_device, word_similarity

# Below this similarity a hit is more likely noise than a mangled target word.
MATCH_THRESHOLD = 0.55

# At or above this, a candidate clip is renamed straight to a bank name. Below
# it, the guess is only prefixed with "maybe-", which deliberately does NOT
# parse as a bank word -- a shaky guess from a speech model should never be able
# to walk into the bank without someone having listened to it first.
RENAME_CONFIDENT = 0.85

WORD_RE = re.compile(r"[^a-zåäö]+")

# c07__4syl__F#3__9.43-9.98.wav -- times are what let a match find its clip.
CANDIDATE_RE = re.compile(r"__(\d+\.\d+)-(\d+\.\d+)$")


@dataclass
class Match:
    word: str
    start_s: float
    end_s: float
    similarity: float
    heard: str


def normalise(text: str) -> str:
    """Lowercase, strip punctuation, keep Finnish vowels intact."""
    text = unicodedata.normalize("NFC", text.lower().strip())
    return WORD_RE.sub("", text)


def best_target(heard: str) -> tuple[str | None, float]:
    """Closest bank word to what the recogniser produced, and how close."""
    if not heard:
        return None, 0.0

    best, score = None, 0.0
    for target in config.WORD_SYLLABLES:
        # Shouts are non-verbal; a recogniser has nothing useful to say about
        # them, and a 3-letter target like "aah" scores highly against all
        # sorts of unrelated short tokens. The sustained-nucleus heuristic in
        # mine_words finds these instead.
        if target in config.SHOUT_WORDS:
            continue
        # Shared with precheck, which scores the same clips at its own stage.
        # The prefix reward and its reasoning live with MATCH_PREFIX_SCORE.
        ratio = word_similarity(heard, target)
        if ratio > score:
            best, score = target, ratio
    return best, score


def transcribe(vocal_path: Path, model_name: str, device: str, language: str) -> list[Match]:
    import whisper

    print(f"  model     {model_name} on {device} (first run loads ~3 GB of weights)")
    model = whisper.load_model(model_name, device=device)

    result = model.transcribe(
        str(vocal_path),
        language=language,
        word_timestamps=True,
        # Without this, one bad guess on sung material conditions everything
        # after it and the whole run drifts into invented text.
        condition_on_previous_text=False,
        # Greedy, not sampled. Whisper's default is a temperature ladder
        # (0.0, 0.2 ... 1.0) that it climbs whenever its confidence checks
        # fail -- which singing triggers constantly. Two runs over this scene
        # returned 25 matches and then 3. Determinism does not make the guesses
        # correct, but it does mean a result can be checked and reproduced
        # rather than being a fresh roll of the dice each time.
        temperature=0.0,
        beam_size=5,
    )

    matches: list[Match] = []
    for segment in result.get("segments", []):
        for w in segment.get("words", []):
            heard = normalise(w.get("word", ""))
            target, score = best_target(heard)
            if target and score >= MATCH_THRESHOLD:
                matches.append(Match(
                    word=target,
                    start_s=float(w["start"]),
                    end_s=float(w["end"]),
                    similarity=score,
                    heard=heard,
                ))
    return matches


# ---------------------------------------------------------------------------
# labels.tsv merging
# ---------------------------------------------------------------------------

@dataclass
class LabelRow:
    word: str
    variant: str
    start_s: float
    end_s: float
    syl: str
    pitch: str
    candidate: str

    def to_tsv(self) -> str:
        return (f"{self.word}\t{self.variant}\t{self.start_s:.3f}\t{self.end_s:.3f}\t"
                f"{self.syl}\t{self.pitch}\t{self.candidate}")


def read_all_rows(path: Path) -> tuple[list[str], list[LabelRow]]:
    header, rows = [], []
    for n, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if raw.startswith("#") or not raw.strip():
            header.append(raw)
            continue
        parts = raw.split("\t")
        if parts[0].strip().lower() == "word":
            header.append(raw)
            continue
        if len(parts) < 4:
            continue
        parts += [""] * (7 - len(parts))
        # The file is edited by hand, so a typo in a timestamp is routine.
        # Refused by file and line, like build_bank's read_labels, rather than
        # left to surface as a bare traceback.
        try:
            start_s, end_s = float(parts[2]), float(parts[3])
        except ValueError as exc:
            raise LabelError(
                f"{path}:{n}: start/end must be numbers ({exc})") from exc
        rows.append(LabelRow(parts[0].strip(), parts[1].strip(),
                             start_s, end_s,
                             parts[4].strip(), parts[5].strip(), parts[6].strip()))
    return header, rows


def overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def merge(rows: list[LabelRow], matches: list[Match]) -> tuple[int, int]:
    """Fill unlabelled rows from matches; add rows for matches with no region."""
    filled = added = 0
    for m in matches:
        best, best_ov = None, 0.0
        for row in rows:
            ov = overlap(m.start_s, m.end_s, row.start_s, row.end_s)
            if ov > best_ov:
                best, best_ov = row, ov

        if best is not None and best_ov > 0:
            if best.word in ("?", "", "-"):
                best.word = m.word
                filled += 1
            continue

        rows.append(LabelRow(m.word, "", m.start_s, m.end_s, "", "", "(asr)"))
        added += 1

    rows.sort(key=lambda r: r.start_s)
    return filled, added


def candidate_span(stem: str) -> tuple[float, float] | None:
    m = CANDIDATE_RE.search(stem)
    return (float(m.group(1)), float(m.group(2))) if m else None


def rename_candidates(folder: Path, matches: list[Match]) -> tuple[int, int, list[str]]:
    """Rename candidate clips to the word the recogniser heard in them.

    Confident hits get a real bank name and are usable immediately. Weaker ones
    get a "maybe-" prefix, which does not parse as a bank word, so they stay out
    of the bank until a human renames them properly.
    """
    from .build_bank import parse_name

    clips = []
    for path in sorted(folder.glob("*.wav")):
        span = candidate_span(path.stem)
        if span and parse_name(path.stem) is None:
            clips.append((path, span))

    confident = maybe = 0
    notes: list[str] = []
    used: dict[str, int] = {}

    for m in sorted(matches, key=lambda x: -x.similarity):
        best, best_ov = None, 0.0
        for path, (start, end) in clips:
            ov = overlap(m.start_s, m.end_s, start, end)
            if ov > best_ov:
                best, best_ov = path, ov

        if best is None or best_ov <= 0 or not best.exists():
            notes.append(f"no candidate clip covers {m.word} at {m.start_s:.2f}s")
            continue

        used[m.word] = used.get(m.word, 0) + 1
        if m.similarity >= RENAME_CONFIDENT:
            new = folder / f"{m.word}{used[m.word]}.wav"
            confident += 1
        else:
            new = folder / f"maybe-{m.word}__{best.stem}.wav"
            maybe += 1

        if new.exists():
            continue
        best.rename(new)
        clips = [(p, s) for p, s in clips if p != best]

    return confident, maybe, notes


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="song_generator.label_words",
        description="Pre-fill labels.tsv using local speech recognition.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--rename", action="store_true",
                   help="rename the candidate clips in place instead of writing labels.tsv")
    p.add_argument("--candidates", type=Path, default=Path("words/candidates"))
    p.add_argument("--labels", type=Path, default=Path("words/labels.tsv"))
    p.add_argument("--vocal", type=Path, default=None,
                   help="separated vocal wav [default: newest under work/*/vocal.wav]")
    p.add_argument("--model", default="large-v3", help="whisper model name")
    p.add_argument("--language", default="fi")
    p.add_argument("--device", default=None)
    p.add_argument("--force", action="store_true",
                   help="overwrite words you have already filled in by hand")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        vocal_path = _find_vocal(args.vocal)
    except LabelError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.rename:
        if not args.candidates.is_dir():
            print(f"error: {args.candidates} not found. Run extract_words first.", file=sys.stderr)
            return 2
    else:
        if not args.labels.is_file():
            print(f"error: {args.labels} not found. Run extract_words first.", file=sys.stderr)
            return 2
        header, rows = read_all_rows(args.labels)
        already = [r for r in rows if r.word not in ("?", "", "-")]
        if already and not args.force:
            print(f"error: {args.labels} already has {len(already)} labelled rows.\n"
                  "       Re-run with --force to overwrite your labelling.", file=sys.stderr)
            return 2

    device = resolve_device(args.device)
    print(f"  vocal     {vocal_path}")
    matches = transcribe(vocal_path, args.model, device, args.language)

    if not matches:
        print("\n  No bank words recognised. Whisper is trained on speech, not singing,")
        print("  so this is a plausible outcome rather than a malfunction.")
        print("  Fall back to labelling by ear -- the candidate clips are already cut.")
        return 1

    print(f"\n  {len(matches)} probable bank words:\n")
    print("   start    end   word         similarity  heard as")
    print("  " + "-" * 56)
    for m in sorted(matches, key=lambda x: x.start_s):
        flag = "" if m.similarity >= 0.8 else "  <- check"
        print(f"  {m.start_s:6.2f} {m.end_s:6.2f}   {m.word:<12} {m.similarity:>6.2f}     "
              f"{m.heard}{flag}")

    counts: dict[str, int] = {}
    for m in matches:
        counts[m.word] = counts.get(m.word, 0) + 1

    if args.rename:
        confident, maybe, notes = rename_candidates(args.candidates, matches)
        for n in notes:
            print(f"  note: {n}")
        print(f"\n  {confident} clips renamed to a bank name, "
              f"{maybe} marked 'maybe-' (too weak to trust)")
        print(f"  folder    {args.candidates.resolve()}")
        print("\n  These are guesses from a model trained on speech, not singing.")
        print("  Play every one before building: fix any wrong name, delete the junk,")
        print("  and rename the 'maybe-' ones properly if they are right.")
        print("  Anything left with a 'maybe-' or generated name is ignored by the bank.")
    else:
        filled, added = merge(rows, matches)
        args.labels.write_text(
            "\n".join(header + [r.to_tsv() for r in rows]) + "\n", encoding="utf-8"
        )
        print(f"\n  {filled} candidate regions labelled, {added} rows added from ASR timings")
        print(f"  labels    {args.labels}")
        print("\n  Check it by ear before building -- anything marked 'check' above.")

    print("  " + (", ".join(f"{w}: {n}" for w, n in sorted(counts.items())) or "nothing matched"))
    missing = [w for w in config.WORD_SYLLABLES if w not in counts]
    if missing:
        print(f"  not found: {', '.join(missing)}")
    print("\n  Then:  python -m song_generator.build_bank")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
