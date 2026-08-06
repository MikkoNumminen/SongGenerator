"""Mine many source clips at once for bank material.

    python -m song_generator.mine_words "sources/*.mp4"

For each source it separates the vocal, cuts candidate regions, and where the
recogniser is confident renames them to a bank name. Each source gets its own
subfolder, because a few hundred candidates in one flat directory is unusable
to listen through.

Shouts get special handling. A sustained single-nucleus region is very likely a
held "aah" or a yell rather than a clipped word, so it is flagged as such --
speech recognition is no help at all for non-verbal noise, and these are worth
keeping: a one-syllable unit fills the leftover slot an odd phrase produces,
which nothing else in the bank can do.

Nothing here decides what a clip actually contains. Everything lands as a
suggestion for you to confirm, correct or delete by ear.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from . import audio_io, config
from .extract_words import Thresholds, cut, find_candidates, write_labels
from .separate import separate
from .util import expand, resolve_device, slugify, work_dir_for


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


def partial_labels_path(folder: Path) -> Path:
    """A labels filename no earlier interrupted run has claimed.

    Numbered rather than fixed, because two interrupted runs over the same
    folder would otherwise leave the second one clobbering the first's rows,
    which is the exact failure this path exists to avoid on labels.tsv.
    """
    p = folder / "labels.partial.tsv"
    n = 2
    while p.exists():
        p = folder / f"labels.partial{n}.tsv"
        n += 1
    return p


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

    # labels.tsv lands whatever happens to the cutting. It used to be written
    # only after every clip, so a run dying halfway left candidates on disk
    # with no labels file to review them against; now an interrupted run
    # still records whatever was cut, and a clip not yet written simply has
    # no filename in its row.
    #
    # The failure path must not land on labels.tsv when one is already there.
    # A re-run over a reviewed folder dying halfway used to replace a file
    # that may carry hand-typed words with fresh auto rows, so the partial
    # rows go to a name of their own instead. A successful run still
    # overwrites, as it always has: its rows describe every clip on disk.
    try:
        for c in candidates:
            hint = "shout" if looks_like_shout(c) else f"{c.n_syllables}syl"
            name = f"c{c.i:02d}__{hint}__{c.note}__{c.start_s:.2f}-{c.end_s:.2f}.wav"
            c.path = audio_io.write_wav(folder / name, cut(vocal, c))
            if hint == "shout":
                result.shouts += 1
    except BaseException:
        labels = folder / "labels.tsv"
        target = partial_labels_path(folder) if labels.exists() else labels
        # Guarded on its own: a write failing here must not replace the
        # exception that stopped the cut, which is the one worth reading.
        try:
            write_labels(target, candidates)
        except Exception as exc:
            print(f"  the cut failed and no labels file could be written "
                  f"either ({exc}); the rows for {folder} are lost",
                  file=sys.stderr)
        else:
            if target != labels:
                print(f"  interrupted mid-cut. {labels} already exists and "
                      "may be hand-edited, so it was left alone; this run's "
                      f"rows went to {target}", file=sys.stderr)
        raise
    write_labels(folder / "labels.tsv", candidates)
    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="song_generator.mine_words",
        description="Mine many sources for word-bank candidates.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("sources", nargs="+",
                   help="files or glob patterns, e.g. 'sources/*.mp4'")
    p.add_argument("-o", "--out", type=Path, default=Path("words/candidates"))
    p.add_argument("--device", default=None)
    p.add_argument("--asr", action="store_true",
                   help="also run speech recognition and pre-name confident matches")
    p.add_argument("--model", default="large-v3")
    p.add_argument("--silence-db", type=float, default=config.WORD_SILENCE_DB)
    p.add_argument("--gap", type=float, default=config.WORD_GAP_S)
    p.add_argument("--min-dur", type=float, default=config.WORD_MIN_S)
    return p


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

    asr_failed = _run_asr(summary, sources, args) if args.asr else 0

    total = sum(s.candidates for s in summary.ok)
    shouts = sum(s.shouts for s in summary.ok)
    named = sum(s.named for s in summary.ok)

    print(f"\n  {len(summary.ok)} sources mined, {len(summary.failed)} failed")
    print(f"  {total} candidates, of which {shouts} look like held shouts")
    if named:
        print(f"  {named} pre-named by the recogniser")
    for s in summary.failed:
        print(f"    FAILED {s.name}: {s.error}")
    if asr_failed:
        print(f"  recognition failed on {asr_failed} of them, so their clips "
              f"are unnamed. The clips are still there to name by ear.")

    print(f"\n  folder    {args.out.resolve()}")
    print("  One subfolder per source. Play them, delete the junk, and rename")
    print("  the keepers after what you hear:")
    print("      bravo1.wav   tangodelta2.wav   eee1.wav   huuto3.wav")
    print("      eeecalculator1.wav      (multi-word names are read as sequences)")
    print("\n  Then:  python -m song_generator.build_bank")
    # One source failing must not vanish into exit 0 because another mined.
    # Every source is still attempted; the code only reports what happened.
    return 1 if summary.failed else 0


def _run_asr(summary: MineSummary, sources: list[Path], args) -> int:
    """Run the recogniser over each vocal. Returns how many sources it failed on.

    A failure here is deliberately NOT counted into summary.failed. Mining is
    what this tool does; recognition is a labelling hint that gets checked by
    ear afterwards either way, so a source whose clips were cut correctly has
    not failed just because the recogniser fell over on it. It is reported
    rather than swallowed, and it leaves the exit code alone.
    """
    from .label_words import rename_candidates, transcribe

    device = resolve_device(args.device)
    failed = 0
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
            failed += 1
            print(f"  [{i:>3}/{len(sources)}] {path.name}: ASR failed ({exc})",
                  file=sys.stderr)
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
