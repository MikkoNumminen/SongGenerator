"""Standardise a finished bank into a derivative tier that sits together.

    python -m song_generator.standardize

The hand-recorded clips are the source of truth and are never written to. This
pass reads them and produces NEW files in a sibling directory, each traceable
back to the clip it came from. Delete the tier and nothing is lost; run it
again and the same clips come back.

What it does is assembly, not enhancement: trim the dead air off each end, fade
the cut so it does not click, and bring the levels into line. What a word
SOUNDS like is the whole point of the bank, so nothing here touches timbre --
no denoise, no EQ, no compression, no resynthesis.

The guard below is the load-bearing part. Every write in this module goes
through write_derivative, which refuses any destination that could be a source
clip. Overwriting a hand-recorded original is meant to be impossible rather
than merely avoided.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import audio_io, config

# Bumped when the pass would produce different audio from the same sources and
# the same config. Folded into the parameter fingerprint, so raising it makes
# every existing derivative read as stale instead of silently surviving a
# change in how they are made.
FORMAT_VERSION = 1

# Envelope resolution for edge detection. Finer than the 256 used elsewhere:
# this measures a boundary rather than finding a region, and 2.9 ms of
# quantisation on a 25 ms guard would be a tenth of the thing being decided.
TRIM_HOP = 128


class StandardizeError(RuntimeError):
    pass


def _resolved(path: Path) -> Path:
    """Absolute, symlinks followed, so containment checks cannot be fooled."""
    return Path(path).expanduser().resolve()


def _relation(a: Path, b: Path) -> str | None:
    """How two directories overlap, or None when they are unrelated."""
    if a == b:
        return "is"
    if a in b.parents:
        return "contains"
    if b in a.parents:
        return "is inside"
    return None


def check_destination(root: Path, sources: list[Path]) -> Path:
    """Refuse an output directory that could reach a source clip.

    Three ways a derivative could land on top of an original, all refused
    before anything is written:

      --out words_hq          the tier IS the source
      --out words_hq/std      the tier is inside the source, so a later
                              rglob over the source sweeps derivatives up
      --out .                 the tier contains the source

    Checked on resolved paths, so a symlink pointing back at the source is
    caught as well as a literal path.
    """
    root_r = _resolved(root)
    for source in sources:
        source_r = _resolved(source)
        how = _relation(root_r, source_r)
        if how is not None:
            raise StandardizeError(
                f"refusing to write derivatives into {root_r}:\n"
                f"    that directory {how} the source bank {source_r}.\n"
                "    The recorded clips are the source of truth and this pass "
                "never writes to them.\n"
                "    Pick an --out that is a sibling, e.g. "
                f"{source_r.name}{config.STD_SUFFIX}"
            )
    return root_r


def write_derivative(root: Path, name: str, audio: np.ndarray,
                     sources: list[Path], protected: set[Path] | None = None) -> Path:
    """The only way this module puts a file on disk.

    Re-checks the destination on every call rather than trusting a check made
    once at startup: a guard that runs at the moment of writing cannot be
    skipped by a later code path that forgot about it.
    """
    root_r = check_destination(root, sources)
    dest = _resolved(root_r / name)

    if root_r not in dest.parents:
        raise StandardizeError(
            f"refusing to write {dest}: it is not inside {root_r}. "
            f"A clip name may not climb out of the output directory."
        )
    if protected and dest in protected:
        raise StandardizeError(
            f"refusing to write {dest}: that path is a source clip in the manifest."
        )

    root_r.mkdir(parents=True, exist_ok=True)
    return audio_io.write_wav(dest, audio)


# ---------------------------------------------------------------------------
# Trim
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Trim:
    """How much silence to remove from each end, in seconds."""
    head_s: float
    tail_s: float

    @property
    def any(self) -> bool:
        return self.head_s > 0.0 or self.tail_s > 0.0


def find_trim(mono: np.ndarray, sr: int = config.SAMPLE_RATE) -> Trim:
    """Where the sound really starts and ends, judged conservatively.

    Deliberately biased toward leaving silence in. The envelope is compared
    against the clip's own peak, a guard is subtracted from each end so the
    cut never lands on the first sound itself, and the head trim is capped
    outright. Trimming a hair short costs nothing; trimming into a soft word
    start removes the attack and cannot be undone.

    Only the two outer boundaries move. Nothing in here can reach the middle
    of a clip, which is what keeps the sung transition inside a multi-word
    clip structurally safe rather than safe by good behaviour.
    """
    from .extract_words import _envelope_db

    mono = np.asarray(mono, dtype=np.float32)
    dur_s = mono.shape[0] / sr
    if dur_s <= 0:
        return Trim(0.0, 0.0)

    env = _envelope_db(mono, sr, TRIM_HOP)
    live = np.flatnonzero(env > env.max() + config.STD_DEAD_AIR_DB)
    if live.size == 0:
        # Nothing rises above its own floor: a clip of pure silence or pure
        # noise. Neither is safe to trim, so it is passed through untouched.
        return Trim(0.0, 0.0)

    hop_s = TRIM_HOP / sr
    head = max(0.0, float(live[0]) * hop_s - config.STD_HEAD_GUARD_S)
    tail = max(0.0, float(len(env) - 1 - live[-1]) * hop_s - config.STD_TAIL_GUARD_S)

    head = min(head, config.STD_HEAD_CAP_S)

    # Never trim a clip below the length that counts as a word at all. The tail
    # gives way first: it is dead air by construction, while the head is next
    # to the attack.
    room = dur_s - config.WORD_MIN_S
    if head + tail > room:
        tail = max(0.0, min(tail, room))
        head = max(0.0, min(head, room - tail))

    return Trim(round(head, 6), round(tail, 6))


def apply_trim(clip: np.ndarray, trim: Trim, sr: int = config.SAMPLE_RATE) -> np.ndarray:
    """Cut the ends off, then fade the cuts so they do not click."""
    clip = np.atleast_2d(np.asarray(clip, dtype=np.float32))
    n = clip.shape[1]
    lo = min(int(round(trim.head_s * sr)), n)
    hi = max(lo, n - int(round(trim.tail_s * sr)))
    out = np.array(clip[:, lo:hi], dtype=np.float32)

    width = out.shape[1]
    if width == 0:
        return out

    fade_in = min(int(config.STD_FADE_IN_S * sr), width // 2)
    fade_out = min(int(config.STD_FADE_OUT_S * sr), width // 2)
    if fade_in > 0:
        out[:, :fade_in] *= np.linspace(0.0, 1.0, fade_in, dtype=np.float32)
    if fade_out > 0:
        out[:, -fade_out:] *= np.linspace(1.0, 0.0, fade_out, dtype=np.float32)
    return out


def shift_bounds(bounds: list[float], head_s: float, duration_s: float) -> list[float]:
    """Move syllable boundaries to match a clip that lost time off its front.

    syllable_bounds_s are absolute offsets into the clip, so trimming the head
    invalidates every one of them. Getting this wrong is quiet and expensive:
    a boundary off by 30 ms lands a syllable on the wrong note in stage 3, and
    nothing reports it.

    The count is preserved whatever happens. A boundary is what tells the
    mapper how many syllables the clip holds, so dropping one because it
    landed badly would change the word rather than fix it.
    """
    if not bounds:
        return []

    eps = 1e-4
    out: list[float] = []
    previous = 0.0
    for i, b in enumerate(bounds):
        # Room is reserved for every boundary still to come. Capping each one
        # at the same duration - eps collapsed them onto that value whenever a
        # tail trim pushed several past the new end, and a boundary equal to
        # the next one is a syllable of zero length: it renders as silence,
        # and the word loses its ending without anything reporting it.
        ceiling = duration_s - eps * (len(bounds) - i)
        value = min(max(float(b) - head_s, previous + eps), max(ceiling, previous + eps))
        out.append(round(value, 4))
        previous = value
    return out


# ---------------------------------------------------------------------------
# Level
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Level:
    """What levelling did to one clip, and whether it got all the way there."""
    lufs_before: float
    lufs_after: float
    gain_db: float
    ceiling_limited: bool
    skipped: bool = False


def clip_lufs(mono: np.ndarray, sr: int = config.SAMPLE_RATE) -> float:
    """Gated integrated loudness, with a block size a short clip can satisfy.

    detect.integrated_lufs answers -inf below 400 ms, which is right for a song
    stem and wrong here: a trimmed word can land under the default gating
    window and still needs a number. The block shrinks to fit rather than the
    measurement being abandoned.
    """
    import warnings

    import pyloudnorm as pyln

    mono = np.asarray(mono, dtype=np.float64)
    if mono.size == 0 or not np.any(np.abs(mono) > 0):
        return float("-inf")

    dur_s = mono.shape[0] / sr
    block_s = 0.400 if dur_s >= 0.400 else max(0.050, dur_s * 0.9)
    meter = pyln.Meter(sr, block_size=block_s)
    with warnings.catch_warnings():
        # pyloudnorm warns when the signal sits below its own gating threshold,
        # which for a quiet clip is the case being measured.
        warnings.simplefilter("ignore")
        return float(meter.integrated_loudness(mono))


def target_lufs(is_shout: bool, mode: str | None = None) -> float | None:
    """The loudness a clip should land on. None means leave it alone.

    The shout is not ordinary vocabulary. SHOUT_KEEP_RAW already exempts it
    from resynthesis because its rawness is the sound, and how loud it was
    shouted is part of that. Which of the two treatments is right is an ear
    question, so both are buildable and neither is hidden.
    """
    if not is_shout:
        return config.CLIP_TARGET_LUFS

    mode = mode or config.SHOUT_LEVEL_MODE
    if mode == "as_recorded":
        return None
    if mode == "offset":
        return config.CLIP_TARGET_LUFS - config.SHOUT_LUFS_OFFSET
    raise StandardizeError(
        f"unknown SHOUT_LEVEL_MODE {mode!r}.\n"
        "    Expected 'offset' (a quieter target of its own) or 'as_recorded' "
        "(not levelled at all).\n"
        "    Set it in the BANK STANDARDISATION block of config.py, or pass "
        "--shouts on the command line."
    )


def level(clip: np.ndarray, is_shout: bool, mode: str | None = None,
          sr: int = config.SAMPLE_RATE) -> tuple[np.ndarray, Level]:
    """Bring one clip to its target, without letting it clip.

    A clip too quiet to reach its target without going over the peak ceiling
    keeps the ceiling and lands short. That is recorded rather than silently
    accepted: a handful of clips sitting below target is worth knowing about,
    because it means the bank has takes whose peaks and loudness disagree.
    """
    clip = np.atleast_2d(np.asarray(clip, dtype=np.float32))
    before = clip_lufs(audio_io.to_mono(clip), sr)
    want = target_lufs(is_shout, mode)

    if want is None or not np.isfinite(before):
        return clip, Level(before, before, 0.0, False, skipped=True)

    gain = 10.0 ** ((want - before) / 20.0)
    peak = float(np.abs(clip).max()) * gain
    limited = peak > config.CLIP_PEAK_CEILING
    if limited:
        gain *= config.CLIP_PEAK_CEILING / peak

    out = (clip * gain).astype(np.float32)
    return out, Level(
        lufs_before=round(before, 2),
        lufs_after=round(clip_lufs(audio_io.to_mono(out), sr), 2),
        gain_db=round(20.0 * float(np.log10(max(gain, 1e-12))), 3),
        ceiling_limited=limited,
    )


# ---------------------------------------------------------------------------
# Traceability
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def params_fingerprint(mode: str) -> str:
    """Everything that decides what a derivative sounds like, as one hash.

    Hashing the parameters alongside each source is the half that a
    per-file hash alone would miss: change a trim threshold and no source
    moves, yet every derivative on disk is now wrong. With this, a config edit
    makes the whole tier read as stale at once.
    """
    payload = {
        "format": FORMAT_VERSION,
        "sample_rate": config.SAMPLE_RATE,
        "dead_air_db": config.STD_DEAD_AIR_DB,
        "head_guard_s": config.STD_HEAD_GUARD_S,
        "tail_guard_s": config.STD_TAIL_GUARD_S,
        "head_cap_s": config.STD_HEAD_CAP_S,
        "word_min_s": config.WORD_MIN_S,
        "fade_in_s": config.STD_FADE_IN_S,
        "fade_out_s": config.STD_FADE_OUT_S,
        "target_lufs": config.CLIP_TARGET_LUFS,
        "shout_mode": mode,
        "shout_offset_db": config.SHOUT_LUFS_OFFSET,
        "peak_ceiling": config.CLIP_PEAK_CEILING,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read_manifest(root: Path) -> dict:
    path = Path(root) / config.STD_MANIFEST
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StandardizeError(
            f"{path} is not readable JSON ({exc}).\n"
            "    Delete the tier and run the pass again; nothing is lost, the "
            "recorded clips are untouched."
        ) from exc


def _write_if_changed(path: Path, text: str) -> bool:
    """Leave a file alone when its content would not change.

    Idempotence has to be visible on disk, not merely true in principle: a run
    that rewrites every file with identical bytes still looks like work
    happened to anything watching timestamps.
    """
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

@dataclass
class Report:
    built: list[str] = field(default_factory=list)
    reused: list[str] = field(default_factory=list)
    missing_audio: list[str] = field(default_factory=list)
    ceiling_limited: list[str] = field(default_factory=list)
    trimmed_s: float = 0.0
    index_written: bool = False
    manifest_written: bool = False


def is_shout_entry(entry: dict) -> bool:
    """A clip that is nothing but shout, matching Unit.is_bare_shout."""
    words = entry.get("words") or []
    return bool(words) and all(w in config.SHOUT_WORDS for w in words)


def standardise_clip(clip: np.ndarray, entry: dict, mode: str,
                     sr: int = config.SAMPLE_RATE) -> tuple[np.ndarray, dict, Trim, Level]:
    """Trim, fade, level. The order matters: level measures what survives."""
    trim = find_trim(audio_io.to_mono(clip), sr)
    trimmed = apply_trim(clip, trim, sr)
    levelled, info = level(trimmed, is_shout_entry(entry), mode, sr)

    duration_s = levelled.shape[1] / sr
    updated = dict(entry)
    updated["duration_s"] = round(duration_s, 4)
    updated["syllable_bounds_s"] = shift_bounds(
        entry.get("syllable_bounds_s") or [], trim.head_s, duration_s)
    return levelled, updated, trim, info


def standardise_bank(source: Path, out: Path, mode: str,
                     force: bool = False) -> Report:
    """Build or refresh the derivative tier for one bank."""
    source = Path(source)
    index_path = source / "words.json"
    if not index_path.is_file():
        raise StandardizeError(
            f"{index_path} not found. Standardisation runs on a built bank:\n"
            "    python -m song_generator.build_bank"
        )

    check_destination(out, [source])
    entries = json.loads(index_path.read_text(encoding="utf-8"))
    fingerprint = params_fingerprint(mode)

    previous = read_manifest(out)
    previous_clips = previous.get("clips", {}) if previous.get("params_sha256") == fingerprint else {}
    previous_index = {}
    if (Path(out) / "words.json").is_file():
        previous_index = json.loads((Path(out) / "words.json").read_text(encoding="utf-8"))

    protected = {_resolved(source / name) for name in entries}
    report = Report()
    clips: dict[str, dict] = {}
    index: dict[str, dict] = {}

    for name, entry in entries.items():
        path = source / name
        if not path.is_file():
            report.missing_audio.append(name)
            continue

        digest = sha256_file(path)
        record = previous_clips.get(name)
        derivative_exists = (Path(out) / name).is_file()

        if (not force and record and record.get("source_sha256") == digest
                and derivative_exists and name in previous_index):
            clips[name] = record
            index[name] = previous_index[name]
            report.reused.append(name)
            continue

        audio, updated, trim, info = standardise_clip(
            audio_io.read_wav(path), entry, mode)
        write_derivative(out, name, audio, [source], protected=protected)

        index[name] = updated
        clips[name] = {
            "source_dir": str(source).replace("\\", "/"),
            "source_sha256": digest,
            "source_bytes": path.stat().st_size,
            "trim_head_s": round(trim.head_s, 4),
            "trim_tail_s": round(trim.tail_s, 4),
            "lufs_before": info.lufs_before,
            "lufs_after": info.lufs_after,
            "gain_db": info.gain_db,
            "ceiling_limited": info.ceiling_limited,
            "levelled": not info.skipped,
            "group": "shout" if is_shout_entry(entry) else "word",
        }
        report.built.append(name)
        report.trimmed_s += trim.head_s + trim.tail_s
        if info.ceiling_limited:
            report.ceiling_limited.append(name)

    if not index:
        raise StandardizeError(
            f"nothing to standardise: none of the {len(entries)} clips in "
            f"{index_path} exist on disk."
        )

    out = Path(out)
    report.index_written = _write_if_changed(
        out / "words.json", json.dumps(index, indent=2, ensure_ascii=False))
    report.manifest_written = _write_if_changed(
        out / config.STD_MANIFEST,
        json.dumps({
            "format": FORMAT_VERSION,
            "params_sha256": fingerprint,
            "shout_mode": mode,
            "source_dir": str(source).replace("\\", "/"),
            "clips": clips,
        }, indent=2, ensure_ascii=False))
    return report


# ---------------------------------------------------------------------------
# Check
# ---------------------------------------------------------------------------

@dataclass
class Status:
    """Whether a tier on disk still matches the clips it was made from."""
    drifted: bool = False
    stale: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)
    gone: list[str] = field(default_factory=list)
    ok: list[str] = field(default_factory=list)

    @property
    def current(self) -> bool:
        return not (self.drifted or self.stale or self.missing
                    or self.new or self.gone)


def check_tier(source: Path, out: Path, mode: str) -> Status:
    """Compare a tier against its sources, by content.

    Four ways a tier goes wrong, and they need telling apart because they call
    for different things:

      drifted  the parameters changed, so every derivative is wrong at once
      stale    a source was re-recorded or re-cut since its derivative
      new      a source has no derivative yet
      missing  a derivative the manifest claims is on disk is not
      gone     a derivative whose source no longer exists, now an orphan

    Never decided by name or timestamp. A clip re-cut to the same length under
    the same name is exactly the case a naming convention cannot see.
    """
    source, out = Path(source), Path(out)
    manifest = read_manifest(out)
    if not manifest:
        raise StandardizeError(
            f"no {config.STD_MANIFEST} in {out}. Nothing has been standardised "
            "there yet:\n    python -m song_generator.standardize"
        )

    index_path = source / "words.json"
    if not index_path.is_file():
        raise StandardizeError(f"{index_path} not found.")
    entries = json.loads(index_path.read_text(encoding="utf-8"))

    status = Status(drifted=manifest.get("params_sha256") != params_fingerprint(mode))
    clips = manifest.get("clips", {})

    for name in entries:
        path = source / name
        if not path.is_file():
            continue
        record = clips.get(name)
        if record is None:
            status.new.append(name)
        elif not (out / name).is_file():
            status.missing.append(name)
        elif record.get("source_sha256") != sha256_file(path):
            status.stale.append(name)
        else:
            status.ok.append(name)

    for name in clips:
        if name not in entries or not (source / name).is_file():
            status.gone.append(name)

    return status


def report_status(status: Status, source: Path, out: Path) -> None:
    print(f"  source    {source}")
    print(f"  tier      {out}")
    print()
    if status.drifted:
        print(f"  DRIFTED   the standardisation parameters changed since this tier "
              f"was built.\n            All {len(status.ok) + len(status.stale)} "
              f"derivatives are out of date, whatever their sources say.")
    for label, names, why in (
        ("STALE", status.stale, "source changed since the derivative was made"),
        ("NEW", status.new, "source has no derivative yet"),
        ("MISSING", status.missing, "manifest claims a derivative that is not on disk"),
        ("ORPHAN", status.gone, "derivative whose source is gone"),
    ):
        if names:
            print(f"  {label:<9} {len(names):>3}  ({why})")
            for name in names[:6]:
                print(f"              {name}")
            if len(names) > 6:
                print(f"              ... and {len(names) - 6} more")
    print(f"  current   {len(status.ok)} derivatives match their sources")
    if status.current:
        print("\n  Up to date.")
    else:
        print("\n  Rebuild:  python -m song_generator.standardize")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="song_generator.standardize",
        description="Build a standardised derivative tier from a bank, "
                    "without ever writing to the recorded clips.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--bank", default=config.DEFAULT_BANK, choices=sorted(config.BANKS),
                   help="which prebuilt bank to standardise")
    p.add_argument("--words-dir", type=Path, default=None,
                   help="a bank directory directly, overriding --bank")
    p.add_argument("--out", type=Path, default=None,
                   help=f"where the derivatives go [default: <bank>{config.STD_SUFFIX}]")
    p.add_argument("--shouts", choices=["offset", "as-recorded"],
                   default=config.SHOUT_LEVEL_MODE.replace("_", "-"),
                   help="how the shout is levelled: its own quieter target, "
                        "or not levelled at all")
    p.add_argument("--force", action="store_true",
                   help="rebuild every derivative even when nothing changed")
    p.add_argument("--check", action="store_true",
                   help="report whether the tier still matches its sources and "
                        "change nothing; exits non-zero when it does not")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = args.words_dir or Path(config.BANKS[args.bank])
    out = args.out or source.with_name(source.name + config.STD_SUFFIX)
    mode = args.shouts.replace("-", "_")

    if args.check:
        try:
            status = check_tier(source, out, mode)
        except StandardizeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        report_status(status, source, out)
        return 0 if status.current else 1

    try:
        report = standardise_bank(source, out, mode, force=args.force)
    except StandardizeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    total = len(report.built) + len(report.reused)
    print(f"  source    {source}  (never written to)")
    print(f"  tier      {out}")
    print(f"  shouts    {mode}")
    print()
    print(f"  {total} clips: {len(report.built)} built, {len(report.reused)} already current")
    if report.built:
        print(f"  trimmed   {report.trimmed_s:.1f}s of dead air off the ends")
    if report.missing_audio:
        print(f"  MISSING   {len(report.missing_audio)} clips listed in words.json "
              f"are not on disk: {', '.join(report.missing_audio[:4])}")
    if report.ceiling_limited:
        print(f"  ceiling   {len(report.ceiling_limited)} clips could not reach the "
              f"target without clipping and landed short:")
        for name in report.ceiling_limited[:6]:
            print(f"              {name}")
    if not report.index_written and not report.manifest_written and not report.built:
        print("\n  nothing changed. Sources and parameters are both untouched, so "
              "the tier\n  already on disk is the one this run would have produced.")
    print(f"\n  Use it:   song-generator.exe input\\song.mp4 --words-dir {out}")
    print("            (or just run normally: the tier is picked up automatically)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
