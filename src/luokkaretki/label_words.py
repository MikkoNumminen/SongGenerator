"""Pre-fill labels.tsv by running local speech recognition over the vocal.

    python -m luokkaretki.label_words

Transcribes the separated vocal with Whisper, then keeps only the words that
fuzzy-match the bank (paska, perse, pillu, pornolehti, paviaani) and writes
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
from difflib import SequenceMatcher
from pathlib import Path

from . import config
from .build_bank import _find_vocal, LabelError
from .util import resolve_device

# Below this similarity a hit is more likely noise than a mangled target word.
MATCH_THRESHOLD = 0.55

WORD_RE = re.compile(r"[^a-zåäö]+")


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
        ratio = SequenceMatcher(None, heard, target).ratio()
        # A long target heard as one of its own syllables ("porno" for
        # "pornolehti") scores poorly on whole-word ratio but is still very
        # likely that word, so reward a clean prefix too.
        if len(heard) >= 4 and target.startswith(heard):
            ratio = max(ratio, 0.75)
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
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
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
        rows.append(LabelRow(parts[0].strip(), parts[1].strip(),
                             float(parts[2]), float(parts[3]),
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="luokkaretki.label_words",
        description="Pre-fill labels.tsv using local speech recognition.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
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

    if not args.labels.is_file():
        print(f"error: {args.labels} not found. Run extract_words first.", file=sys.stderr)
        return 2
    try:
        vocal_path = _find_vocal(args.vocal)
    except LabelError as exc:
        print(f"error: {exc}", file=sys.stderr)
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

    filled, added = merge(rows, matches)
    args.labels.write_text(
        "\n".join(header + [r.to_tsv() for r in rows]) + "\n", encoding="utf-8"
    )

    counts: dict[str, int] = {}
    for r in rows:
        if r.word in config.WORD_SYLLABLES:
            counts[r.word] = counts.get(r.word, 0) + 1

    print(f"\n  {filled} candidate regions labelled, {added} rows added from ASR timings")
    print("  " + (", ".join(f"{w}: {n}" for w, n in sorted(counts.items())) or "nothing matched"))
    missing = [w for w in config.WORD_SYLLABLES if w not in counts]
    if missing:
        print(f"  not found: {', '.join(missing)}")

    print(f"\n  labels    {args.labels}")
    print("\n  Check it by ear before building -- anything marked 'check' above, and")
    print("  any row whose start/end clips a word short. Then:")
    print("      python -m luokkaretki.build_bank")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
