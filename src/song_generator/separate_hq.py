"""Re-separate sources with Mel-Band Roformer, alongside the Demucs stems.

    python -m song_generator.separate_hq "sources/*.mp4"
    python -m song_generator.separate_hq --for-bank "sources/*.mp4"

The second form narrows the given files to the ones the current bank was cut
from. The sources are still passed, because --for-bank cannot find them on
its own: the bank records which work directories its clips separated into,
not where the source media lives.

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
import sys
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

from . import audio_io, config
from .util import expand, resolve_device, slugify

if TYPE_CHECKING:  # only for the cache annotation; numpy is not needed at runtime here
    import numpy as np


def sources_needed_by_bank(bank: Path) -> set[str]:
    """Work-dir names the current bank was cut from."""
    import json

    from .recut_bank import by_correlation, from_name, work_dirs

    index = bank / "words.json"
    if not index.is_file():
        return set()

    entries = json.loads(index.read_text(encoding="utf-8"))
    dirs = work_dirs()
    # by_correlation stores decimated stems here and reads them back, so the
    # value type is load-bearing rather than decorative: object hid the fact
    # that this dict is the correlation cache.
    cache: dict[Path, np.ndarray] = {}
    needed: set[str] = set()

    for name, e in entries.items():
        origin = from_name(str(e.get("source_clip", "")), dirs)
        if origin is None and (bank / name).is_file():
            origin = by_correlation(audio_io.read_wav(bank / name), dirs, cache)
        if origin:
            needed.add(origin.work_dir.name)
    return needed


def make_separator(staging: Path):
    """One Separator for the whole batch.

    Loading the model weights is the slow part and the model does not change
    per file, so it used to be absurd that the batch loop paid for it once
    per source. Built lazily by main, only when at least one source actually
    needs separating.
    """
    from audio_separator.separator import Separator

    separator = Separator(output_dir=str(staging), output_format="wav")
    separator.load_model(model_filename=config.ROFORMER_MODEL)
    return separator


def separate_one(path: Path, separator, staging: Path) -> Path | None:
    work = Path(config.WORK_DIR) / slugify(path.stem)
    work.mkdir(parents=True, exist_ok=True)
    target = work / "vocal_hq.wav"
    if target.is_file():
        return target

    produced = separator.separate(str(path))

    vocal = next((staging / n for n in produced if "vocal" in n.lower()), None)
    if vocal is None or not vocal.is_file():
        return None

    audio_io.write_wav(target, audio_io.read_wav(vocal))
    # Only the stems this call produced, never everything in the directory.
    # Staging is shared now that the model is loaded once, so a glob would
    # delete a concurrent run's stems in the gap between its separator writing
    # them and its copy reading them. That run would then find no vocal, return
    # None, and be counted neither done nor failed: minutes of GPU work gone
    # with nothing printed.
    for name in produced:
        (staging / name).unlink(missing_ok=True)
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

    # Checked before the bank is even opened: locating the bank's sources can
    # cost minutes of correlation, and with nothing to filter the answer is
    # already known.
    if args.for_bank and not args.sources:
        print("error: --for-bank narrows the sources you pass; it cannot find "
              "them alone.\n"
              "       The bank records which work directories its clips came "
              "from, not\n"
              "       where the source media lives, so pass the files or "
              "globs too:\n"
              "           python -m song_generator.separate_hq --for-bank "
              "\"sources/*.mp4\"",
              file=sys.stderr)
        return 2

    paths = expand(args.sources)

    # Before the bank is opened, so a mistyped glob is reported as a mistyped
    # glob. Reading the bank can cost minutes of correlation, and paying that
    # only to be told the sources do not match it points at the wrong thing.
    if not paths:
        print("error: nothing to separate. Pass source files or globs.", file=sys.stderr)
        return 2

    if args.for_bank:
        needed = sources_needed_by_bank(args.bank)
        print(f"  bank was cut from {len(needed)} sources")
        paths = [p for p in paths if slugify(p.stem) in needed]
        if not paths:
            print(f"error: none of the given sources is among the "
                  f"{len(needed)} the bank was cut from.", file=sys.stderr)
            return 2

    device = resolve_device(args.device)
    print(f"  {len(paths)} sources on {device}\n")

    staging = Path(config.WORK_DIR) / "_roformer"
    separator = None

    done = failed = skipped = 0
    for i, path in enumerate(paths, start=1):
        work = Path(config.WORK_DIR) / slugify(path.stem)
        if (work / "vocal_hq.wav").is_file():
            skipped += 1
            continue
        print(f"  [{i:>3}/{len(paths)}] {path.name}", flush=True)
        try:
            if separator is None:
                staging.mkdir(parents=True, exist_ok=True)
                separator = make_separator(staging)
            done += 1 if separate_one(path, separator, staging) else 0
        except Exception as exc:
            failed += 1
            print(f"      failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    if staging.is_dir() and not any(staging.iterdir()):
        # Tidiness, not correctness. Another run may be writing into the shared
        # directory between the check and the call, and losing an empty
        # directory is not worth ending a run over.
        try:
            staging.rmdir()
        except OSError:
            pass

    print(f"\n  {done} separated, {skipped} already done, {failed} failed")
    print("  Demucs stems untouched; vocal_hq.wav sits alongside vocal.wav")
    print("\n  Then:  python -m song_generator.recut_bank")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
