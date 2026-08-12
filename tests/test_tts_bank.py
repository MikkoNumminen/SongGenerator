"""Tests for tts_bank, the synthesized-clip bank source.

The contract that matters most here is the filename. `build_bank.parse_phrase`
decides whether a clip can enter a bank at all, and it refuses anything it
cannot read cleanly, so a naming scheme that looks fine and parses wrong
produces a bank that is silently empty. Those cases are pinned rather than
reasoned about.

The vocabulary under test is the example one (bravo/tango/delta), because
conftest sets SONG_GENERATOR_NO_LOCAL_VOCAB.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from song_generator import config, tts_bank
from song_generator.build_bank import parse_phrase


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------


def test_ladder_is_symmetric_and_includes_the_root():
    steps = tts_bank.ladder_steps()
    assert 0 in steps
    assert steps[0] == -steps[-1]


def test_ladder_reaches_exactly_as_far_as_the_renderer_shifts():
    """The stated reason for the span: a target inside the cap always has a
    near take, so FOLD_PENALTY never has to be paid."""
    assert config.TTS_LADDER_SEMITONES == config.SHIFT_CAP_SEMITONES


def test_ladder_step_respects_config(monkeypatch):
    monkeypatch.setattr(config, "TTS_LADDER_SEMITONES", 12)
    monkeypatch.setattr(config, "TTS_LADDER_STEP", 2)
    steps = tts_bank.ladder_steps()
    assert steps == list(range(-12, 13, 2))


def test_configured_shift_engine_is_one_render_unit_knows():
    assert config.TTS_BANK_SHIFT_ENGINE in {"world", "rubberband"}


# ---------------------------------------------------------------------------
# Naming: the parse_phrase contract
# ---------------------------------------------------------------------------


def test_variant_starts_with_a_digit():
    """A label starting with a known syllable gets partly eaten by the
    greedy matcher; leading with a digit is the guarantee against that."""
    assert tts_bank.variant_label(53, "scream")[0].isdigit()


def test_variant_is_zero_padded_so_a_listing_sorts_by_pitch():
    assert tts_bank.variant_label(7, "basic") == "007basic"
    assert tts_bank.variant_label(127, "basic") == "127basic"


@pytest.mark.parametrize("expression", ["sing-song", "very_loud", "a b",
                                        "hälinä", "shout!"])
def test_variant_refuses_anything_a_separator_would_split(expression):
    with pytest.raises(tts_bank.TtsBankError):
        tts_bank.variant_label(53, expression)


def test_clip_name_parses_back_as_the_word_it_claims():
    """The whole point. A name that does not parse never reaches a bank."""
    name = tts_bank.clip_name("bravo", 53, "scream")
    assert name == "bravo_053scream.wav"
    assert parse_phrase(name[:-4]) == (["bravo"], "053scream")


def test_every_rung_of_the_ladder_parses_back():
    for step in tts_bank.ladder_steps():
        midi = 53 + step
        stem = tts_bank.clip_name("bravo", midi, "dreamy")[:-4]
        parsed = parse_phrase(stem)
        assert parsed is not None, stem
        assert parsed[0] == ["bravo"], stem


@pytest.mark.parametrize("word", ["bravo", "tango", "delta", "calculator"])
def test_naming_holds_for_every_example_word(word):
    stem = tts_bank.clip_name(word, 60, "basic")[:-4]
    assert parse_phrase(stem) == ([word], "060basic")


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def _write_manifest(tmp_path, payload):
    (tmp_path / tts_bank.ROOTS_MANIFEST).write_text(
        json.dumps(payload), encoding="utf-8")
    return tmp_path


def test_missing_manifest_is_refused_by_name(tmp_path):
    with pytest.raises(tts_bank.TtsBankError) as exc:
        tts_bank.load_roots(tmp_path)
    assert tts_bank.ROOTS_MANIFEST in str(exc.value)


def test_foreign_manifest_format_is_refused(tmp_path):
    _write_manifest(tmp_path, {"format": "something/2", "roots": [{}]})
    with pytest.raises(tts_bank.TtsBankError):
        tts_bank.load_roots(tmp_path)


def test_empty_manifest_is_refused(tmp_path):
    _write_manifest(tmp_path, {"format": tts_bank.ROOTS_FORMAT, "roots": []})
    with pytest.raises(tts_bank.TtsBankError):
        tts_bank.load_roots(tmp_path)


def test_valid_manifest_loads(tmp_path):
    _write_manifest(tmp_path, {
        "format": tts_bank.ROOTS_FORMAT,
        "roots": [{"word": "bravo", "language": "fi", "expression": "basic",
                   "file": "fi/roots/bravo_basic.wav"}],
    })
    roots = tts_bank.load_roots(tmp_path)
    assert roots[0]["word"] == "bravo"


# ---------------------------------------------------------------------------
# Refusing to write over hand work
# ---------------------------------------------------------------------------


def test_refuses_a_registered_bank_that_holds_clips(tmp_path, monkeypatch):
    """AGENTS.md: never point a tool's output at a bank curated by hand."""
    bank = tmp_path / "words_hq"
    bank.mkdir()
    (bank / "paska_1.wav").write_bytes(b"")
    monkeypatch.setattr(config, "BANKS", {"ppbank": str(bank)})
    with pytest.raises(tts_bank.TtsBankError) as exc:
        tts_bank.refuse_curated_destination(bank, force=False)
    assert "BANKS" in str(exc.value)
    assert "paska_1.wav" in str(exc.value)


def test_allows_a_registered_bank_that_is_still_empty(tmp_path, monkeypatch):
    """Naming a bank in BANKS before building it is the documented setup.

    Refusing it would refuse the workflow the runbook prescribes; a name in
    config is not hand work, clips are.
    """
    bank = tmp_path / "words_tts_fi"
    bank.mkdir()
    monkeypatch.setattr(config, "BANKS", {"ttsfi": str(bank)})
    tts_bank.refuse_curated_destination(bank, force=False)


def test_refuses_clips_anywhere_under_the_destination(tmp_path):
    """A bank's clips can sit at its top level or under candidates/."""
    bank = tmp_path / "words_hq4"
    bank.mkdir()
    (bank / "perse_2.wav").write_bytes(b"")
    with pytest.raises(tts_bank.TtsBankError):
        tts_bank.refuse_curated_destination(bank, force=False)


def test_refuses_a_directory_that_already_holds_clips(tmp_path):
    candidates = tmp_path / "words_tts_fi" / "candidates"
    candidates.mkdir(parents=True)
    (candidates / "bravo_053basic.wav").write_bytes(b"")
    with pytest.raises(tts_bank.TtsBankError) as exc:
        tts_bank.refuse_curated_destination(tmp_path / "words_tts_fi",
                                            force=False)
    assert "bravo_053basic.wav" in str(exc.value)


def test_force_overrides_the_refusal(tmp_path):
    candidates = tmp_path / "words_tts_fi" / "candidates"
    candidates.mkdir(parents=True)
    (candidates / "bravo_053basic.wav").write_bytes(b"")
    tts_bank.refuse_curated_destination(tmp_path / "words_tts_fi", force=True)


def test_an_empty_destination_is_fine(tmp_path):
    tts_bank.refuse_curated_destination(tmp_path / "fresh", force=False)


# ---------------------------------------------------------------------------
# Transposition
# ---------------------------------------------------------------------------


def _voiced(seconds: float, f0: float = 165.0) -> np.ndarray:
    """A harmonic stack, not a sine.

    WORLD estimates a spectral envelope from a signal's harmonics. A pure
    sine has none to estimate from, so it resynthesises to something whose
    measured pitch is unrelated to the input, and a test built on one fails
    for reasons that have nothing to do with the code under test.
    """
    sr = config.SAMPLE_RATE
    t = np.arange(int(sr * seconds)) / sr
    wave = np.zeros_like(t)
    for harmonic in range(1, 11):
        wave += np.sin(2 * np.pi * f0 * harmonic * t) / harmonic
    return (0.4 * wave / np.max(np.abs(wave))).astype(np.float32)


def _median_f0(mono: np.ndarray, sr: int) -> float:
    import pyworld as pw

    x = np.ascontiguousarray(mono, dtype=np.float64)
    f0, t = pw.harvest(x, sr, f0_floor=config.F0_MIN_HZ,
                       f0_ceil=config.F0_MAX_HZ, frame_period=5.0)
    f0 = pw.stonemask(x, f0, t, sr)
    voiced = f0[f0 > 0]
    assert voiced.size, "no voiced frames to measure"
    return float(np.median(voiced))


def test_shift_preserves_length():
    """A ladder rung is a transposition, not a time stretch."""
    mono = _voiced(0.5)
    out = tts_bank.shift_clip(mono, config.SAMPLE_RATE, 5.0, engine="world")
    assert abs(out.shape[0] - mono.shape[0]) < config.SAMPLE_RATE * 0.02


def test_shift_of_zero_leaves_the_pitch_alone():
    mono = _voiced(0.5)
    out = tts_bank.shift_clip(mono, config.SAMPLE_RATE, 0.0, engine="world")
    assert _median_f0(out, config.SAMPLE_RATE) == pytest.approx(165.0, rel=0.05)


@pytest.mark.parametrize("semitones,ratio", [(12.0, 2.0), (-12.0, 0.5),
                                             (7.0, 2 ** (7 / 12))])
def test_shift_moves_the_pitch_by_the_asked_interval(semitones, ratio):
    mono = _voiced(0.6)
    out = tts_bank.shift_clip(mono, config.SAMPLE_RATE, semitones,
                              engine="world")
    assert _median_f0(out, config.SAMPLE_RATE) == pytest.approx(
        165.0 * ratio, rel=0.05)


def test_the_configured_engine_can_actually_run():
    """Exercises whichever engine the ladder is configured to use."""
    if config.TTS_BANK_SHIFT_ENGINE == "rubberband":
        pytest.importorskip("pylibrb")
    mono = _voiced(0.4)
    out = tts_bank.shift_clip(mono, config.SAMPLE_RATE, 12.0)
    assert out.size > 0
    assert np.isfinite(out).all()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_parse_args_requires_roots_and_out():
    with pytest.raises(SystemExit):
        tts_bank.parse_args(["--roots", "x"])


def test_parse_args_defaults():
    args = tts_bank.parse_args(["--roots", "r", "--out", "words_tts"])
    assert args.force is False
    assert args.dry_run is False
    assert args.language is None
