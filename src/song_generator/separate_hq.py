"""Re-separate sources with Mel-Band Roformer, alongside the Demucs stems.

    python -m song_generator.separate_hq "sources/*.mp4"
    python -m song_generator.separate_hq --for-bank

Writes `vocal_hq.wav` into each source's existing work directory, leaving the
Demucs `vocal.wav` untouched. Both then sit side by side, so the two can be
compared and nothing already built is put at risk.

Roformer scores around 11.4 SDR on vocals against Demucs's 9.0. That difference
is mostly instrumental bleed, which is exactly the synthesiser tone audible
under some of the bank clips -- residue baked in at cut time rather than
anything wrong with the recording.
"""

from __future__ import annotations

import argparse
import glob
import sys
import traceback
from pathlib import Path

from . import audio_io, config
from .util import resolve_device, slugify


def sources_needed_by_bank(bank: Path) -> set[str]:
    """Work-dir names the current bank was cut from."""
    from .recut_bank import by_correlation, from_name, work_dirs
    import json

    index = bank / "words.json"
    if not index.is_file():
        return set()

    entries = json.loads(index.read_text(encoding="utf-8"))
    dirs = work_dirs()
    cache: dict[Path, object] = {}
    needed: set[str] = set()

    for name, e in entries.items():
        origin = from_name(str(e.get("source_clip", "")), dirs)
        if origin is None and (bank / name).is_file():
            origin = by_correlation(audio_io.read_wav(bank / name), dirs, cache)
        if origin:
            needed.add(origin.work_dir.name)
    return needed


def separate_one(path: Path, device: str) -> Path | None:
    from audio_separator.separator import Separator

    work = Path(config.WORK_DIR) / slugify(path.stem)
    work.mkdir(parents=True, exist_ok=True)
    target = work / "vocal_hq.wav"
    if target.is_file():
        return target

    out_dir = work / "_roformer"
    out_dir.mkdir(parents=True, exist_ok=True)

    separator = Separator(output_dir=str(out_dir), output_format="wav")
    separator.load_model(model_filename=config.ROFORMER_MODEL)
    produced = separator.separate(str(path))

    vocal = next((out_dir / n for n in produced if "vocal" in n.lower()), None)
    if vocal is None or not vocal.is_file():
        return None

    audio_io.write_wav(target, audio_io.read_wav(vocal))
    for leftover in out_dir.glob("*.wav"):
        leftover.unlink()
    out_dir.rmdir()
    return target


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="song_generator.separate_hq",
        description="Produce cleaner vocal stems with Mel-Band Roformer.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("sources", nargs="*", help="files or globs to separate")
    p.add_argument("--for-bank", action="store_true",
                   help="only the sources the current bank was cut from")
    p.add_argument("--bank", type=Path, default=Path("words"))
    p.add_argument("--device", default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    paths: list[Path] = []
    for pattern in args.sources:
        hits = [Path(p) for p in glob.glob(pattern)]
        paths.extend(sorted(hits) if hits else
                     ([Path(pattern)] if Path(pattern).is_file() else []))

    if args.for_bank:
        needed = sources_needed_by_bank(args.bank)
        print(f"  bank was cut from {len(needed)} sources")
        paths = [p for p in paths if slugify(p.stem) in needed]

    if not paths:
        print("error: nothing to separate. Pass source files or globs.", file=sys.stderr)
        return 2

    device = resolve_device(args.device)
    print(f"  {len(paths)} sources on {device}\n")

    done = failed = skipped = 0
    for i, path in enumerate(paths, start=1):
        work = Path(config.WORK_DIR) / slugify(path.stem)
        if (work / "vocal_hq.wav").is_file():
            skipped += 1
            continue
        print(f"  [{i:>3}/{len(paths)}] {path.name}", flush=True)
        try:
            done += 1 if separate_one(path, device) else 0
        except Exception as exc:
            failed += 1
            print(f"      failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    print(f"\n  {done} separated, {skipped} already done, {failed} failed")
    print("  Demucs stems untouched; vocal_hq.wav sits alongside vocal.wav")
    print("\n  Then:  python -m song_generator.recut_bank")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
