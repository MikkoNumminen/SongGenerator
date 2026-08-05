"""The standardisation pass: trim math, levels, traceability, and the guard.

Nothing here asserts how a clip sounds. That is a listening question and the
pass writes samples to a scratch directory for it. What IS testable is that the
arithmetic is right, that a derivative can be traced back to its source, and
that a source can never be written over -- the last one being the reason the
tier exists at all.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from song_generator import audio_io, config
from song_generator.mapping import load_bank, resolve_bank
from song_generator.standardize import (
    StandardizeError, apply_trim, check_destination, check_tier, clip_lufs,
    find_trim, level, main, params_fingerprint, sha256_file, shift_bounds,
    standardise_bank, target_lufs, write_derivative,
)

SR = config.SAMPLE_RATE


def _clip(sound_s: float = 0.5, head_s: float = 0.0, tail_s: float = 0.0,
          amp: float = 0.5, freq: float = 220.0) -> np.ndarray:
    """Silence, then a steady tone, then silence. Edges exactly where stated."""
    t = np.arange(int(SR * sound_s)) / SR
    tone = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    head = np.zeros(int(SR * head_s), dtype=np.float32)
    tail = np.zeros(int(SR * tail_s), dtype=np.float32)
    mono = np.concatenate([head, tone, tail])
    return np.stack([mono, mono])


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------

@pytest.fixture
def bank(tmp_path):
    """A source bank with one clip in it."""
    d = tmp_path / "words_hq"
    d.mkdir()
    audio_io.write_wav(d / "bravo_1.wav", _clip())
    return d


def test_refuses_writing_into_the_source_itself(bank):
    with pytest.raises(StandardizeError, match="is the source bank"):
        check_destination(bank, [bank])


def test_refuses_a_destination_inside_the_source(bank):
    with pytest.raises(StandardizeError, match="is inside the source bank"):
        check_destination(bank / "std", [bank])


def test_refuses_a_destination_containing_the_source(bank):
    with pytest.raises(StandardizeError, match="contains the source bank"):
        check_destination(bank.parent, [bank])


def test_accepts_a_sibling(bank):
    out = bank.with_name(bank.name + config.STD_SUFFIX)
    assert check_destination(out, [bank]) == out.resolve()


def test_guard_runs_before_anything_is_written(bank):
    before = (bank / "bravo_1.wav").read_bytes()
    with pytest.raises(StandardizeError):
        write_derivative(bank, "bravo_1.wav", _clip(amp=0.9), [bank])
    assert (bank / "bravo_1.wav").read_bytes() == before


def test_refuses_a_name_that_climbs_out(bank, tmp_path):
    out = tmp_path / "words_hq.std"
    with pytest.raises(StandardizeError, match="not inside"):
        write_derivative(out, "../escaped.wav", _clip(), [bank])
    assert not (tmp_path / "escaped.wav").exists()


def test_refuses_a_path_listed_as_a_source(bank, tmp_path):
    out = tmp_path / "words_hq.std"
    protected = {(out / "bravo_1.wav").resolve()}
    with pytest.raises(StandardizeError, match="source clip in the manifest"):
        write_derivative(out, "bravo_1.wav", _clip(), [bank], protected=protected)


def test_writes_a_sibling_normally(bank, tmp_path):
    out = tmp_path / "words_hq.std"
    written = write_derivative(out, "bravo_1.wav", _clip(), [bank])
    assert written.is_file()
    assert written.parent.resolve() == out.resolve()


def _link_to(link: Path, target: Path) -> bool:
    """Point link at target by whatever means this machine allows.

    Windows refuses os.symlink without Developer Mode or elevation, which left
    this test skipped and the resolution branch of the guard unexercised on the
    machine the tool actually runs on. A directory junction needs no privilege
    and is a reparse point all the same, so Path.resolve sees through it the
    same way.
    """
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if sys.platform != "win32":
        return False
    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                          capture_output=True)
    return done.returncode == 0 and link.exists()


def test_a_link_pointing_back_at_the_source_is_caught(bank, tmp_path):
    """A destination disguised as somewhere else still resolves to the source."""
    link = tmp_path / "sneaky"
    if not _link_to(link, bank):
        pytest.skip("this machine allows neither a symlink nor a junction")
    with pytest.raises(StandardizeError):
        check_destination(link, [bank])


def test_a_link_is_no_route_into_the_source_either(bank, tmp_path):
    """The same disguise one level down, where a write would actually land."""
    link = tmp_path / "sneaky"
    if not _link_to(link, bank):
        pytest.skip("this machine allows neither a symlink nor a junction")
    before = (bank / "bravo_1.wav").read_bytes()
    with pytest.raises(StandardizeError):
        write_derivative(link, "bravo_1.wav", _clip(amp=0.9), [bank])
    assert (bank / "bravo_1.wav").read_bytes() == before


# ---------------------------------------------------------------------------
# Trim
# ---------------------------------------------------------------------------

def _mono(clip):
    return audio_io.to_mono(clip)


def test_trim_leaves_the_guard_in_front_of_the_sound():
    # Head silence kept under STD_HEAD_CAP_S, so the guard is what is measured
    # here rather than the cap. The cap has its own test below.
    trim = find_trim(_mono(_clip(head_s=0.10, tail_s=0.30)))
    assert trim.head_s == pytest.approx(0.10 - config.STD_HEAD_GUARD_S, abs=0.006)
    assert trim.tail_s == pytest.approx(0.30 - config.STD_TAIL_GUARD_S, abs=0.006)


def test_trim_never_reaches_the_sound():
    """The cut must land before the first sample of the tone, always."""
    for head in (0.05, 0.12, 0.4, 1.0):
        trim = find_trim(_mono(_clip(head_s=head, tail_s=0.2)))
        assert trim.head_s < head, f"trimmed into the sound with {head}s of silence"


def test_trim_does_nothing_when_there_is_no_silence():
    trim = find_trim(_mono(_clip(head_s=0.0, tail_s=0.0)))
    assert trim.head_s == 0.0
    assert trim.tail_s == 0.0


def test_head_cap_binds_on_a_long_silence():
    trim = find_trim(_mono(_clip(head_s=2.0, tail_s=0.0)))
    assert trim.head_s == config.STD_HEAD_CAP_S


def test_tail_is_uncapped_because_dead_air_is_dead_air():
    trim = find_trim(_mono(_clip(sound_s=0.6, tail_s=2.0)))
    assert trim.tail_s > 1.5


def test_a_silent_clip_is_passed_through_untouched():
    silence = np.zeros((2, int(SR * 0.5)), dtype=np.float32)
    trim = find_trim(_mono(silence))
    assert trim == find_trim(_mono(silence))
    assert not trim.any


def test_trim_never_takes_a_clip_below_the_word_floor():
    # Almost all silence: an unguarded trim would leave nearly nothing.
    clip = _mono(_clip(sound_s=0.05, head_s=0.5, tail_s=0.5))
    trim = find_trim(clip)
    left = clip.shape[0] / SR - trim.head_s - trim.tail_s
    assert left >= config.WORD_MIN_S - 1e-6


def test_apply_trim_removes_exactly_what_was_asked_for():
    clip = _clip(sound_s=0.5, head_s=0.2, tail_s=0.2)
    out = apply_trim(clip, Trim := find_trim(_mono(clip)))
    expected = clip.shape[1] - int(round(Trim.head_s * SR)) - int(round(Trim.tail_s * SR))
    assert out.shape[1] == expected
    assert out.shape[0] == clip.shape[0]


def test_apply_trim_fades_both_edges_but_not_the_middle():
    clip = _clip(sound_s=0.5)
    out = apply_trim(clip, find_trim(_mono(clip)))
    assert abs(out[0, 0]) < 1e-6
    assert abs(out[0, -1]) < 1e-6
    middle = out[0, out.shape[1] // 2 - 200: out.shape[1] // 2 + 200]
    assert np.abs(middle).max() > 0.4


def test_the_interior_of_a_clip_is_never_touched():
    """A gap in the middle survives, which is what protects a sung transition."""
    t = np.arange(int(SR * 0.4)) / SR
    tone = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    gap = np.zeros(int(SR * 0.12), dtype=np.float32)
    mono = np.concatenate([np.zeros(int(SR * 0.2), dtype=np.float32), tone, gap, tone,
                           np.zeros(int(SR * 0.2), dtype=np.float32)])
    clip = np.stack([mono, mono])

    out = apply_trim(clip, find_trim(mono))
    quiet = np.abs(out[0]) < 1e-3
    # The interior gap is still there: a run of near-silence well inside.
    interior = quiet[int(SR * 0.05): -int(SR * 0.05)]
    assert interior.sum() > int(SR * 0.10)


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------

def test_bounds_shift_by_the_head_trim():
    assert shift_bounds([0.30, 0.60, 0.90], 0.05, 1.5) == [0.25, 0.55, 0.85]


def test_bounds_keep_their_count_even_when_crushed():
    """Count is what tells the mapper how many syllables the clip holds."""
    out = shift_bounds([0.01, 0.02, 0.03], 0.10, 0.50)
    assert len(out) == 3


def test_bounds_stay_ordered_and_inside_the_clip():
    out = shift_bounds([0.01, 0.02, 0.9, 1.4], 0.08, 1.0)
    assert out == sorted(out)
    assert all(0.0 < b < 1.0 for b in out)


def test_no_two_bounds_ever_land_on_the_same_moment():
    """Equal boundaries are a syllable of zero length, which renders as silence.

    Sorted is not enough to catch it: [0.9, 0.9] is sorted. This happened for
    real when a tail trim pushed several boundaries past the new end and each
    was capped at the same value.
    """
    for bounds, head, dur in (
        ([0.9, 1.1, 1.3, 1.5], 0.0, 1.0),      # every bound past the end
        ([1.2, 1.25, 1.3], 0.4, 0.9),          # head trim and a short clip
        ([0.05, 0.06, 0.07], 0.2, 0.3),        # bounds before the head trim
    ):
        out = shift_bounds(bounds, head, dur)
        assert len(out) == len(bounds)
        assert all(b > a for a, b in zip(out, out[1:])), out
        assert all(0.0 < b < dur for b in out), out


def test_the_spans_a_trimmed_clip_implies_are_all_real():
    """What Unit.syllable_spans builds must have no zero-length piece."""
    bounds = shift_bounds([0.8, 1.0, 1.2, 1.4], 0.1, 1.05)
    edges = [0.0] + bounds + [1.05]
    assert all(b > a for a, b in zip(edges, edges[1:])), edges


def test_bounds_survive_a_zero_trim_unchanged():
    assert shift_bounds([0.2, 0.4], 0.0, 1.0) == [0.2, 0.4]


def test_no_bounds_stays_no_bounds():
    assert shift_bounds([], 0.05, 1.0) == []


def test_bounds_are_consistent_with_the_trimmed_clip():
    """The invariant load_bank depends on: 0 < every bound < duration_s."""
    clip = _clip(sound_s=1.2, head_s=0.15, tail_s=0.3)
    trim = find_trim(_mono(clip))
    out = apply_trim(clip, trim)
    duration_s = out.shape[1] / SR

    bounds = shift_bounds([0.30, 0.60, 0.90], trim.head_s, duration_s)
    assert len(bounds) == 3
    assert bounds == sorted(bounds)
    assert all(0.0 < b < duration_s for b in bounds)
    # And the spans they imply are all real spans, which is what
    # Unit.syllable_spans builds.
    edges = [0.0] + bounds + [duration_s]
    assert all(b > a for a, b in zip(edges[:-1], edges[1:]))


# ---------------------------------------------------------------------------
# Level
# ---------------------------------------------------------------------------

def test_a_word_lands_on_the_word_target():
    out, info = level(_clip(sound_s=1.0, amp=0.1), is_shout=False)
    assert info.lufs_after == pytest.approx(config.CLIP_TARGET_LUFS, abs=0.5)
    assert not info.skipped


def test_two_words_at_different_levels_end_up_together():
    quiet, _ = level(_clip(sound_s=1.0, amp=0.03), is_shout=False)
    loud, _ = level(_clip(sound_s=1.0, amp=0.6), is_shout=False)
    assert clip_lufs(_mono(quiet)) == pytest.approx(clip_lufs(_mono(loud)), abs=0.5)


def test_offset_mode_puts_the_shout_below_the_word():
    assert target_lufs(is_shout=True, mode="offset") == pytest.approx(
        config.CLIP_TARGET_LUFS - config.SHOUT_LUFS_OFFSET)
    _, info = level(_clip(sound_s=1.0, amp=0.1), is_shout=True, mode="offset")
    assert info.lufs_after == pytest.approx(
        config.CLIP_TARGET_LUFS - config.SHOUT_LUFS_OFFSET, abs=0.5)


def test_as_recorded_mode_does_not_touch_a_shout():
    source = _clip(sound_s=1.0, amp=0.1)
    out, info = level(source, is_shout=True, mode="as_recorded")
    assert target_lufs(is_shout=True, mode="as_recorded") is None
    assert info.skipped
    assert info.gain_db == 0.0
    assert np.array_equal(out, source)


def test_as_recorded_mode_still_levels_ordinary_words():
    _, info = level(_clip(sound_s=1.0, amp=0.1), is_shout=False, mode="as_recorded")
    assert not info.skipped
    assert info.lufs_after == pytest.approx(config.CLIP_TARGET_LUFS, abs=0.5)


def test_an_unknown_shout_mode_is_refused_by_name():
    with pytest.raises(StandardizeError, match="unknown SHOUT_LEVEL_MODE"):
        target_lufs(is_shout=True, mode="loudest")


def test_peak_ceiling_wins_and_says_so():
    """A quiet clip with one loud sample cannot reach target without clipping."""
    mono = np.full(int(SR * 1.0), 0.001, dtype=np.float32)
    mono[: int(SR * 0.5)] = (0.001 * np.sin(
        2 * np.pi * 220 * np.arange(int(SR * 0.5)) / SR)).astype(np.float32)
    mono[100] = 0.94
    out, info = level(np.stack([mono, mono]), is_shout=False)
    assert info.ceiling_limited
    assert float(np.abs(out).max()) <= config.CLIP_PEAK_CEILING + 1e-6
    assert info.lufs_after < config.CLIP_TARGET_LUFS


def test_silence_is_skipped_rather_than_amplified():
    out, info = level(np.zeros((2, int(SR * 0.5)), dtype=np.float32), is_shout=False)
    assert info.skipped
    assert float(np.abs(out).max()) == 0.0


def test_levelling_is_a_scalar_gain_and_changes_nothing_else():
    """The waveform is scaled, never reshaped: no compression, no EQ."""
    source = _clip(sound_s=1.0, amp=0.2)
    out, info = level(source, is_shout=False)
    gain = 10.0 ** (info.gain_db / 20.0)
    assert np.allclose(out, source * gain, atol=1e-6)


def test_a_short_clip_can_still_be_measured():
    """Under the 400 ms gating window the block shrinks instead of giving up."""
    value = clip_lufs(_mono(_clip(sound_s=0.2, amp=0.3)))
    assert np.isfinite(value)


# ---------------------------------------------------------------------------
# The pass, end to end
# ---------------------------------------------------------------------------

@pytest.fixture
def built(tmp_path):
    """A source bank with an index, as build_bank would leave it."""
    d = tmp_path / "words_hq"
    d.mkdir()
    audio_io.write_wav(d / "bravo_1.wav", _clip(sound_s=0.8, head_s=0.2, tail_s=0.5))
    audio_io.write_wav(d / "aah_1.wav", _clip(sound_s=0.9, head_s=0.1, amp=0.2))
    audio_io.write_wav(d / "bravo-tango_1.wav",
                       _clip(sound_s=1.2, head_s=0.15, tail_s=0.4, amp=0.3))
    index = {
        "bravo_1.wav": {"words": ["bravo"], "syllables": 2, "duration_s": 1.5,
                        "midi": 53.0, "syllable_bounds_s": [0.6]},
        "aah_1.wav": {"words": ["aah"], "syllables": 1, "duration_s": 1.0,
                      "midi": 55.0, "syllable_bounds_s": []},
        "bravo-tango_1.wav": {"words": ["bravo", "tango"], "syllables": 4,
                              "duration_s": 1.75, "midi": 54.0,
                              "syllable_bounds_s": [0.4, 0.8, 1.2]},
    }
    (d / "words.json").write_text(json.dumps(index), encoding="utf-8")
    return d


def _out(built):
    return built.with_name(built.name + config.STD_SUFFIX)


def test_the_pass_builds_a_loadable_bank(built):
    out = _out(built)
    report = standardise_bank(built, out, "offset")
    assert len(report.built) == 3
    assert (out / "words.json").is_file()
    assert (out / config.STD_MANIFEST).is_file()
    for name in ("bravo_1.wav", "aah_1.wav", "bravo-tango_1.wav"):
        assert (out / name).is_file()


def test_sources_are_byte_identical_afterwards(built):
    before = {p.name: p.read_bytes() for p in built.glob("*.wav")}
    standardise_bank(built, _out(built), "offset")
    after = {p.name: p.read_bytes() for p in built.glob("*.wav")}
    assert before == after


def test_the_index_matches_the_audio_it_describes(built):
    out = _out(built)
    standardise_bank(built, out, "offset")
    index = json.loads((out / "words.json").read_text(encoding="utf-8"))
    for name, entry in index.items():
        real = audio_io.read_wav(out / name).shape[1] / SR
        assert entry["duration_s"] == pytest.approx(real, abs=0.001)
        for bound in entry["syllable_bounds_s"]:
            assert 0.0 < bound < entry["duration_s"]


def test_labels_survive_untouched(built):
    out = _out(built)
    standardise_bank(built, out, "offset")
    index = json.loads((out / "words.json").read_text(encoding="utf-8"))
    assert index["bravo-tango_1.wav"]["words"] == ["bravo", "tango"]
    assert index["bravo-tango_1.wav"]["syllables"] == 4
    assert index["bravo-tango_1.wav"]["midi"] == 54.0
    assert len(index["bravo-tango_1.wav"]["syllable_bounds_s"]) == 3


def test_a_second_run_rebuilds_nothing(built):
    out = _out(built)
    standardise_bank(built, out, "offset")
    stamps = {p: p.stat().st_mtime_ns for p in out.iterdir()}

    again = standardise_bank(built, out, "offset")
    assert again.built == []
    assert len(again.reused) == 3
    assert not again.index_written
    assert not again.manifest_written
    assert {p: p.stat().st_mtime_ns for p in out.iterdir()} == stamps


def test_the_same_inputs_give_identical_audio(built, tmp_path):
    """Determinism is a property of the samples, not of the container.

    Compared as audio rather than as file bytes on purpose. libsndfile writes a
    PEAK chunk into a float WAV carrying the wall-clock time of the write, at
    byte 60, so two runs that straddle a second boundary produce files that
    differ by exactly that one byte while the samples are bit-identical.
    Comparing bytes here made this test fail about twice in a hundred runs for
    a reason that had nothing to do with the pass.
    """
    a = standardise_bank(built, tmp_path / "a", "offset")
    b = standardise_bank(built, tmp_path / "b", "offset")
    assert len(a.built) == len(b.built) == 3
    for name in ("bravo_1.wav", "aah_1.wav", "bravo-tango_1.wav"):
        assert np.array_equal(audio_io.read_wav(tmp_path / "a" / name),
                              audio_io.read_wav(tmp_path / "b" / name))


def test_a_changed_source_is_rebuilt_and_the_rest_are_not(built):
    out = _out(built)
    standardise_bank(built, out, "offset")
    audio_io.write_wav(built / "bravo_1.wav", _clip(sound_s=0.7, head_s=0.3, amp=0.4))

    again = standardise_bank(built, out, "offset")
    assert again.built == ["bravo_1.wav"]
    assert sorted(again.reused) == ["aah_1.wav", "bravo-tango_1.wav"]


def test_changing_a_parameter_restandardises_everything(built, monkeypatch):
    out = _out(built)
    standardise_bank(built, out, "offset")
    monkeypatch.setattr(config, "STD_HEAD_GUARD_S", 0.05)

    again = standardise_bank(built, out, "offset")
    assert len(again.built) == 3


def test_the_two_shout_modes_differ_only_on_the_shout(built, tmp_path):
    standardise_bank(built, tmp_path / "offset", "offset")
    standardise_bank(built, tmp_path / "raw", "as_recorded")

    # Audio, not file bytes: the container carries a write timestamp that has
    # nothing to do with the mode. See test_the_same_inputs_give_identical_audio.
    shout_a = audio_io.read_wav(tmp_path / "offset" / "aah_1.wav")
    shout_b = audio_io.read_wav(tmp_path / "raw" / "aah_1.wav")
    assert not np.array_equal(shout_a, shout_b)

    word_a = audio_io.read_wav(tmp_path / "offset" / "bravo_1.wav")
    word_b = audio_io.read_wav(tmp_path / "raw" / "bravo_1.wav")
    assert np.array_equal(word_a, word_b)


def test_the_manifest_traces_every_derivative_to_its_source(built):
    out = _out(built)
    standardise_bank(built, out, "offset")
    manifest = json.loads((out / config.STD_MANIFEST).read_text(encoding="utf-8"))

    assert manifest["shout_mode"] == "offset"
    assert manifest["params_sha256"] == params_fingerprint("offset")
    for name, record in manifest["clips"].items():
        assert record["source_sha256"] == sha256_file(built / name)
        assert record["group"] in ("shout", "word")
    assert manifest["clips"]["aah_1.wav"]["group"] == "shout"
    assert manifest["clips"]["bravo_1.wav"]["group"] == "word"


def test_the_fingerprint_moves_with_the_shout_mode():
    assert params_fingerprint("offset") != params_fingerprint("as_recorded")


def test_a_clip_listed_but_absent_is_reported_not_fatal(built):
    (built / "aah_1.wav").unlink()
    report = standardise_bank(built, _out(built), "offset")
    assert report.missing_audio == ["aah_1.wav"]
    assert len(report.built) == 2


def test_an_unbuilt_bank_is_refused_with_the_command_to_run(built, tmp_path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    with pytest.raises(StandardizeError, match="build_bank"):
        standardise_bank(empty, tmp_path / "nothing.std", "offset")


def test_the_pass_refuses_to_target_its_own_source(built):
    with pytest.raises(StandardizeError):
        standardise_bank(built, built, "offset")


# ---------------------------------------------------------------------------
# Check
# ---------------------------------------------------------------------------

def test_a_fresh_tier_reports_current(built):
    out = _out(built)
    standardise_bank(built, out, "offset")
    status = check_tier(built, out, "offset")
    assert status.current
    assert len(status.ok) == 3
    assert main(["--words-dir", str(built), "--out", str(out), "--check"]) == 0


def test_a_re_cut_source_reads_stale_even_at_the_same_length(built):
    """The case a naming convention cannot see: same name, same length."""
    out = _out(built)
    standardise_bank(built, out, "offset")
    original = audio_io.read_wav(built / "bravo_1.wav")
    audio_io.write_wav(built / "bravo_1.wav", original * 0.5)

    status = check_tier(built, out, "offset")
    assert status.stale == ["bravo_1.wav"]
    assert not status.current
    assert main(["--words-dir", str(built), "--out", str(out), "--check"]) == 1


def test_a_new_source_reads_new(built):
    out = _out(built)
    standardise_bank(built, out, "offset")
    audio_io.write_wav(built / "delta_1.wav", _clip())
    index = json.loads((built / "words.json").read_text(encoding="utf-8"))
    index["delta_1.wav"] = {"words": ["delta"], "syllables": 2, "duration_s": 0.5,
                            "midi": 53.0, "syllable_bounds_s": [0.25]}
    (built / "words.json").write_text(json.dumps(index), encoding="utf-8")

    status = check_tier(built, out, "offset")
    assert status.new == ["delta_1.wav"]
    assert not status.current


def test_a_deleted_derivative_reads_missing(built):
    out = _out(built)
    standardise_bank(built, out, "offset")
    (out / "bravo_1.wav").unlink()

    status = check_tier(built, out, "offset")
    assert status.missing == ["bravo_1.wav"]
    assert not status.current


def test_a_removed_source_leaves_an_orphan(built):
    out = _out(built)
    standardise_bank(built, out, "offset")
    (built / "aah_1.wav").unlink()

    status = check_tier(built, out, "offset")
    assert status.gone == ["aah_1.wav"]
    assert not status.current


def test_changing_a_parameter_drifts_the_whole_tier(built, monkeypatch):
    out = _out(built)
    standardise_bank(built, out, "offset")
    monkeypatch.setattr(config, "STD_DEAD_AIR_DB", -50.0)

    status = check_tier(built, out, "offset")
    assert status.drifted
    assert not status.current


def test_checking_the_other_shout_mode_drifts_too(built):
    out = _out(built)
    standardise_bank(built, out, "offset")
    assert check_tier(built, out, "as_recorded").drifted


def test_check_refuses_when_nothing_was_ever_standardised(built, tmp_path):
    with pytest.raises(StandardizeError, match="standardize"):
        check_tier(built, tmp_path / "never", "offset")


def test_check_writes_nothing(built):
    out = _out(built)
    standardise_bank(built, out, "offset")
    stamps = {p: p.stat().st_mtime_ns for p in out.iterdir()}
    check_tier(built, out, "offset")
    assert {p: p.stat().st_mtime_ns for p in out.iterdir()} == stamps


# ---------------------------------------------------------------------------
# What the runtime picks up
# ---------------------------------------------------------------------------

def test_a_bank_with_no_tier_reads_as_recorded(built):
    """A fresh clone that has never standardised behaves exactly as before."""
    where, standardised = resolve_bank(built)
    assert where == built
    assert not standardised


def test_a_tier_is_preferred_once_it_exists(built):
    standardise_bank(built, _out(built), "offset")
    where, standardised = resolve_bank(built)
    assert where == _out(built)
    assert standardised


def test_raw_clips_opts_back_out(built):
    standardise_bank(built, _out(built), "offset")
    where, standardised = resolve_bank(built, prefer_standardised=False)
    assert where == built
    assert not standardised


def test_pointing_straight_at_a_tier_still_reads_as_standardised(built):
    """--words-dir words_hq.std must not look for words_hq.std.std."""
    out = _out(built)
    standardise_bank(built, out, "offset")
    where, standardised = resolve_bank(out)
    assert where == out
    assert standardised


def test_a_half_written_tier_is_not_trusted(built):
    """words.json without a manifest is some other bank, not a tier."""
    out = _out(built)
    out.mkdir()
    (out / "words.json").write_text("{}", encoding="utf-8")
    where, standardised = resolve_bank(built)
    assert where == built
    assert not standardised


def test_standardised_clips_are_not_levelled_again(built):
    """The silent failure this guards: level_clip replacing a LUFS decision."""
    out = _out(built)
    standardise_bank(built, out, "offset")
    units = {u.name: u for u in load_bank(built)}
    on_disk = audio_io.read_wav(out / "bravo_1.wav")
    assert np.allclose(units["bravo_1.wav"].audio, on_disk, atol=1e-6)


def test_recorded_clips_are_still_levelled_on_load(built):
    units = {u.name: u for u in load_bank(built, prefer_standardised=False)}
    on_disk = audio_io.read_wav(built / "bravo_1.wav")
    assert not np.allclose(units["bravo_1.wav"].audio, on_disk, atol=1e-6)


def test_bounds_survive_rounding_to_four_decimals():
    """Two boundaries a fraction apart must not round onto the same value.

    The guard was 1e-4 and the output is rounded to 4 decimals, so neighbours
    separated by exactly the guard collapsed after rounding. Equal boundaries
    are a syllable of zero length: it renders as silence and takes the end off
    the word, and nothing reports it.
    """
    out = shift_bounds([0.1] * 8, 0.05, 0.2)
    assert len(out) == 8
    assert all(b > a for a, b in zip(out, out[1:])), out
    assert out == [round(b, 4) for b in out]


def test_a_bound_never_lands_on_the_edges_of_the_clip():
    """0.0 and duration_s are edges, not boundaries: either makes an empty span."""
    for bounds, head, dur in (([0.5], 0.0, 0.5), ([0.5], 0.6, 1.0), ([-0.5, 0.2], 0.0, 1.0)):
        out = shift_bounds(bounds, head, dur)
        assert all(0.0 < b < dur for b in out), (bounds, head, dur, out)


def test_a_clip_too_short_for_its_bounds_still_gets_real_spans():
    """Nowhere legal left to put them is answered with wrong, not degenerate."""
    out = shift_bounds([0.9, 1.1, 1.3, 1.5], 0.0, 1.0)
    edges = [0.0] + out + [1.0]
    assert all(b > a for a, b in zip(edges, edges[1:])), edges


class TestNamesThatAreNotPaths:
    """A clip name comes from a filename and becomes one again.

    Containment catches traversal. These are the names that are not paths at
    all, which reached libsndfile and failed there with a system error nobody
    can read, or would have been written somewhere unintended.
    """

    def test_an_absolute_or_unc_name_is_refused(self, bank, tmp_path):
        for name in ("C:/Windows/evil.wav", "//server/share/evil.wav"):
            with pytest.raises(StandardizeError):
                write_derivative(tmp_path / "tier", name, _clip(), [bank])

    def test_a_control_character_is_refused(self, bank, tmp_path):
        for name in ("ok\nevil.wav", "ok\revil.wav", "ok\x00.wav"):
            with pytest.raises(StandardizeError, match="not a usable clip name"):
                write_derivative(tmp_path / "tier", name, _clip(), [bank])

    def test_an_empty_or_dot_name_is_refused(self, bank, tmp_path):
        for name in ("", ".", ".."):
            with pytest.raises(StandardizeError, match="not a usable clip name"):
                write_derivative(tmp_path / "tier", name, _clip(), [bank])

    def test_an_ordinary_name_still_writes(self, bank, tmp_path):
        written = write_derivative(tmp_path / "tier", "paska_1.wav", _clip(), [bank])
        assert written.is_file()
        assert (tmp_path / "tier").resolve() in written.resolve().parents
