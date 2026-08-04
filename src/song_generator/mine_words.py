"""Mine many source clips at once for bank material.

    python -m song_generator.mine_words "D:/kuvat/kuvat/pilluvittu*.mp4"

For each source it separates the vocal, cuts candidate regions, and where the
recogniser is confident renames them to a bank name. Each source gets its own
subfolder, because a few hundred candidates in one flat directory is unusable
to listen through.

Shouts get special handling. A sustained single-nucleus region is very likely a
held "eee" or a yell rather than a clipped word, so it is flagged as such --
speech recognition is no help at all for non-verbal noise, and these are worth
keeping: a one-syllable unit fills the leftover slot an odd phrase produces,
which nothing else in the bank can do.

Nothing here decides what a clip actually contains. Everything lands as a
suggestion for you to confirm, correct or delete by ear.
"""

from __future__ import annotations

import argparse
import glob
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from . import audio_io, config
from .extract_words import Thresholds, cut, find_candidates, write_labels
from .separate import separate
from .util import resolve_device, slugify, work_dir_for


@dataclass
class SourceResult:
    name: str
    candidates: int = 0
    named: int = 0
    shouts: int = 0
    error: str = ""


@dataclass
class MineSummary:
    sources: list[SourceResult] = field(default_factory=list)

    @property
    def ok(self) -> list[SourceResult]:
        return [s for s in self.sources if not s.error]

    @property
    def failed(self) -> list[SourceResult]:
        return [s for s in self.sources if s.error]


def looks_like_shout(cand) -> bool:
    """One long-held nucleus: a shout, not a word."""
    return cand.n_syllables <= 1 and cand.dur_s >= config.SHOUT_MIN_S


def mine_one(path: Path, out_root: Path, device: str, thresholds: Thresholds,
             asr_matches=None) -> SourceResult:
    result = SourceResult(name=path.name)

    work = work_dir_for(path)
    stems = separate(path, work, device=device)
    vocal = stems.vocal

    candidates = find_candidates(vocal, config.SAMPLE_RATE, device, th=thresholds)
    result.candidates = len(candidates)
    if not candidates:
        return result

    folder = out_root / slugify(path.stem)
    folder.mkdir(parents=True, exist_ok=True)

    for c in candidates:
        hint = "shout" if looks_like_shout(c) else f"{c.n_syllables}syl"
        name = f"c{c.i:02d}__{hint}__{c.note}__{c.start_s:.2f}-{c.end_s:.2f}.wav"
        c.path = audio_io.write_wav(folder / name, cut(vocal, c))
        if hint == "shout":
            result.shouts += 1

    write_labels(folder / "labels.tsv", candidates)
    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="song_generator.mine_words",
        description="Mine many sources for word-bank candidates.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("sources", nargs="+",
                   help="files or glob patterns, e.g. 'D:/kuvat/kuvat/pilluvittu*.mp4'")
    p.add_argument("-o", "--out", type=Path, default=Path("words/candidates"))
    p.add_argument("--device", default=None)
    p.add_argument("--asr", action="store_true",
                   help="also run speech recognition and pre-name confident matches")
    p.add_argument("--model", default="large-v3")
    p.add_argument("--silence-db", type=float, default=config.WORD_SILENCE_DB)
    p.add_argument("--gap", type=float, default=config.WORD_GAP_S)
    p.add_argument("--min-dur", type=float, default=config.WORD_MIN_S)
    return p


def expand(patterns: list[str]) -> list[Path]:
    found: list[Path] = []
    for pattern in patterns:
        hits = [Path(p) for p in glob.glob(pattern)]
        if hits:
            found.extend(sorted(hits))
        elif Path(pattern).is_file():
            found.append(Path(pattern))
        else:
            print(f"  warning: nothing matched {pattern!r}", file=sys.stderr)
    # Dedupe while keeping order.
    seen, out = set(), []
    for p in found:
        if p.resolve() not in seen:
            seen.add(p.resolve())
            out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sources = expand(args.sources)
    if not sources:
        print("error: no source files matched", file=sys.stderr)
        return 2

    device = resolve_device(args.device)
    thresholds = Thresholds(silence_db=args.silence_db, gap_s=args.gap, min_s=args.min_dur)
    summary = MineSummary()

    print(f"  mining    {len(sources)} sources on {device}")
    print(f"  output    {args.out.resolve()}\n")

    for i, path in enumerate(sources, start=1):
        print(f"  [{i:>3}/{len(sources)}] {path.name}", flush=True)
        try:
            result = mine_one(path, args.out, device, thresholds)
        except Exception as exc:  # one bad source must not end the batch
            result = SourceResult(name=path.name, error=f"{type(exc).__name__}: {exc}")
            traceback.print_exc(file=sys.stderr)
        summary.sources.append(result)

    if args.asr:
        _run_asr(summary, sources, args)

    total = sum(s.candidates for s in summary.ok)
    shouts = sum(s.shouts for s in summary.ok)
    named = sum(s.named for s in summary.ok)

    print(f"\n  {len(summary.ok)} sources mined, {len(summary.failed)} failed")
    print(f"  {total} candidates, of which {shouts} look like held shouts")
    if named:
        print(f"  {named} pre-named by the recogniser")
    for s in summary.failed:
        print(f"    FAILED {s.name}: {s.error}")

    print(f"\n  folder    {args.out.resolve()}")
    print("  One subfolder per source. Play them, delete the junk, and rename")
    print("  the keepers after what you hear:")
    print("      paska1.wav   persepillu2.wav   eee1.wav   huuto3.wav")
    print("      eeepaviaani1.wav      (multi-word names are read as sequences)")
    print("\n  Then:  python -m song_generator.build_bank")
    return 0 if summary.ok else 1


def _run_asr(summary: MineSummary, sources: list[Path], args) -> None:
    from .label_words import rename_candidates, transcribe

    device = resolve_device(args.device)
    print("\n  running speech recognition over each separated vocal")
    for i, path in enumerate(sources, start=1):
        folder = args.out / slugify(path.stem)
        if not folder.is_dir():
            continue
        vocal = work_dir_for(path) / "vocal.wav"
        if not vocal.is_file():
            continue
        try:
            matches = transcribe(vocal, args.model, device, "fi")
            confident, maybe, _ = rename_candidates(folder, matches)
            for s in summary.sources:
                if s.name == path.name:
                    s.named = confident
            print(f"  [{i:>3}/{len(sources)}] {path.name}: "
                  f"{confident} named, {maybe} uncertain", flush=True)
        except Exception as exc:
            print(f"  [{i:>3}/{len(sources)}] {path.name}: ASR failed ({exc})",
                  file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
