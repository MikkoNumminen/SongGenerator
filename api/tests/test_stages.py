"""Stage detection, against output the pipeline actually printed.

The transcripts below are copied from real runs, not written by hand, because
the whole risk in this module is that the strings drift from what the pipeline
says. A test built from invented lines would keep passing while the feature
silently reported every run as stuck at separation.
"""

from __future__ import annotations

from app.stages import Progress, Stage, final_stage, read

# A cached-stems run, so separation is skipped. This is the common case: the
# stems are cached after the first run of a song.
CACHED_RUN = """\
  song      ellinoora_-_nartut_lyric_video.mp4  (3:08)
  device    cuda
  separator demucs
  stems     cached -> work\\ellinoora_-_nartut_lyric_video

  vocal presence
    stem loudness      -14.1 LUFS
    relative            -6.7 LU     (needs >= -25.0)
    voiced frames       53.5 %      (needs >= 5.0, via torchcrepe)
    verdict           MODE A -- vocals present

  melody + timing extraction
    tempo             90.7 BPM, 264 beats
    notes found       931 in 18 phrases
  bank      curated (words_hq4.std, standardised)
  play      conservative, seed 984547
  words     work\\ellinoora\\arrangements\\984547-conservative.arr
  wrote 14 versions to D:\\output\\ellinoora\\curated
""".splitlines()

# A first run of a song, where the separator does the work and reports it.
FRESH_RUN = """\
  song      takatalvi.mp3  (2:43)
  device    cuda
  separator roformer
  0%|          | 0/40 [00:00<?, ?it/s]
 32%|###2      | 13/40 [00:08<00:15,  1.69it/s]
100%|##########| 40/40 [00:23<00:00,  1.67it/s]
  stems     31.7s -> work\\mokoma_-_takatalvi
    verdict           MODE A -- vocals present
  bank      muslimbank (words_muslim.std, standardised)
  play      conservative, seed 157290
  wrote 7 versions to D:\\output\\takatalvi\\muslimbank
""".splitlines()

REFUSED_RUN = """\
  song      music45.mp4  (0:30)
  separator roformer
  stems     18.2s -> work\\music45
  vocal presence
    voiced frames        0.9 %      (needs >= 5.0, via torchcrepe)
    verdict           MODE B -- no vocals
""".splitlines()


def test_a_finished_run_reads_as_done():
    assert read(CACHED_RUN).stage is Stage.DONE


def test_every_stage_is_reached_in_order():
    """Folded one line at a time, the run visits each stage once and never
    goes back. A status that flickered backwards would read as stuck."""
    seen: list[Stage] = []
    progress = Progress()
    for line in CACHED_RUN:
        progress = progress.advance(line)
        if not seen or seen[-1] is not progress.stage:
            seen.append(progress.stage)

    assert seen == [Stage.QUEUED, Stage.SEPARATING, Stage.ANALYSING,
                    Stage.ARRANGING, Stage.RENDERING, Stage.DONE]


def test_cached_stems_still_pass_through_separating():
    """The header prints before the pipeline knows the stems are cached, so
    the stage is entered and left immediately. The UI should say separation was
    skipped rather than pretend it ran, which the timing makes obvious."""
    progress = Progress()
    for line in CACHED_RUN[:4]:
        progress = progress.advance(line)
    assert progress.stage is Stage.ANALYSING
    assert progress.percent is None


def test_separation_reports_a_real_percentage():
    """The only within-stage number in the whole run that is not invented."""
    progress = Progress()
    for line in FRESH_RUN[:5]:
        progress = progress.advance(line)

    assert progress.stage is Stage.SEPARATING
    assert progress.percent == 32


def test_no_stage_but_separation_ever_reports_a_percentage():
    """Nothing else in the pipeline reports progress within a stage. A bar
    anywhere else would be invented, and worst exactly where runs are slowest."""
    progress = Progress()
    for line in CACHED_RUN:
        progress = progress.advance(line)
        if progress.stage is not Stage.SEPARATING:
            assert progress.percent is None, progress


def test_a_percentage_in_the_analysis_report_is_not_read_as_progress():
    """`voiced frames 53.5 %` sits in the analysis block. Read as separation
    progress it would show a run going backwards to 53%."""
    progress = read(CACHED_RUN[:9])
    assert progress.stage is Stage.ANALYSING
    assert progress.percent is None


def test_a_song_with_no_vocal_is_refused_not_failed():
    """Mode B is a normal outcome for a song the tool cannot work from, and
    needs its own answer in the UI rather than an error."""
    assert read(REFUSED_RUN).stage is Stage.REFUSED


def test_the_bank_warning_line_is_not_mistaken_for_the_bank_stage():
    """The pipeline also prints `  BANK      holds no clip saying: ...`, which
    differs from the stage line only in case."""
    progress = Progress(Stage.ANALYSING)
    after = progress.advance("  BANK      holds no clip saying: paviaani")
    assert after.stage is Stage.ANALYSING


def test_the_exit_code_decides_the_ending_not_the_last_line():
    """A run killed mid-render prints nothing to say so."""
    assert final_stage(0, Stage.DONE) is Stage.DONE
    assert final_stage(3, Stage.ANALYSING) is Stage.REFUSED
    assert final_stage(2, Stage.RENDERING) is Stage.FAILED
    assert final_stage(-9, Stage.RENDERING) is Stage.FAILED


def test_a_refusal_survives_a_zero_exit():
    """Whatever the code, a run that said mode B did not make a song."""
    assert final_stage(0, Stage.REFUSED) is Stage.REFUSED


def test_an_unrecognised_line_changes_nothing():
    progress = Progress(Stage.RENDERING, percent=None, detail="x")
    assert progress.advance("    tempo   90.7 BPM") == progress
