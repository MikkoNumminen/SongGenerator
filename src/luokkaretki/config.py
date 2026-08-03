"""The tuning constants block.

Every tunable value in the tool lives here. Nothing that you would want to
twiddle while listening to a result should be hardcoded anywhere else -- if you
find yourself editing a number in another module, it belongs in this file.

Grouped by pipeline stage, in the order the stages run.
"""

# ---------------------------------------------------------------------------
# AUDIO / IO
# ---------------------------------------------------------------------------

# Working sample rate for the whole pipeline. Demucs is trained at 44100 and
# every stem, clip and mixdown is resampled to this before anything else.
SAMPLE_RATE = 44100

# Output mp3 encode settings (passed to ffmpeg).
MP3_BITRATE = "320k"

# Where intermediate artifacts (stems, analysis.json) are cached, relative to
# the repo root. Re-running on the same song reuses these instead of paying for
# separation again.
WORK_DIR = "work"


# ---------------------------------------------------------------------------
# STAGE 1 -- SOURCE SEPARATION
# ---------------------------------------------------------------------------

# Which separator backend to use: "demucs" or "roformer".
#
# "demucs"   - demucs 4.1.0, htdemucs_ft. The default. Installed by default.
# "roformer" - Mel-Band Roformer via the audio-separator package. Scores
#              noticeably higher on vocals (SDR ~11.4 vs ~9.0), which matters
#              because both the melody extraction AND the cleanliness of the
#              instrumental bed depend on this one step. Not installed by
#              default; see README.
SEPARATOR = "demucs"

# Demucs model name. htdemucs_ft is the fine-tuned bag-of-4 -- about 4x slower
# than plain htdemucs but the best quality the default install offers.
DEMUCS_MODEL = "htdemucs_ft"

# Segment length in seconds that demucs processes at a time. Lower this if the
# GPU runs out of memory. None = the model's own default (7.8s for htdemucs),
# which peaks around 7 GB and fits a 12 GB card comfortably.
DEMUCS_SEGMENT = None

# Number of random shifts to average over. 1 = off. Higher is slightly cleaner
# and linearly slower; not worth it for a meme generator.
DEMUCS_SHIFTS = 1

# Model name for the roformer backend, when SEPARATOR = "roformer".
ROFORMER_MODEL = "model_mel_band_roformer_ep_3005_sdr_11.4360.ckpt"

# "cuda" or "cpu". None = autodetect, preferring cuda.
DEVICE = None


# ---------------------------------------------------------------------------
# STAGE 1b -- MODE DETECTION (does this song have vocals at all?)
# ---------------------------------------------------------------------------
# Two independent tests, both of which must pass for the song to be treated as
# Mode A. They catch different failure shapes: the loudness test catches a
# near-silent vocal stem, the voiced test catches a stem that is loud but full
# of tonal bleed (lead guitar, synth lead) rather than actual singing.

# How loud the vocal stem must be RELATIVE to the full mix, in LU. Relative
# rather than absolute so that quiet masters and loud masters behave the same.
VOCAL_PRESENT_REL_LU = -25.0

# Absolute floor, as a backstop against pathological mixes. Integrated LUFS.
VOCAL_PRESENT_ABS_LUFS = -50.0

# Fraction of frames in the vocal stem that must read as confidently voiced.
# A real lead vocal sits well above this even in sparse songs; separation bleed
# from an instrumental does not.
VOCAL_PRESENT_VOICED_FRAC = 0.05

# Per-frame periodicity above which a frame counts as "voiced" for the test
# above. torchcrepe's periodicity output, 0..1.
VOICED_PERIODICITY_MIN = 0.50

# Model size used for the detection pass only ("tiny" or "full"). Detection
# does not need precision, just a voiced/unvoiced verdict, so it runs tiny.
# The real melody extraction in stage 2 uses F0_MODEL below.
DETECT_F0_MODEL = "tiny"
DETECT_HOP_S = 0.02


# ---------------------------------------------------------------------------
# STAGE 2 -- MELODY AND TIMING EXTRACTION      (built in commit 2)
# ---------------------------------------------------------------------------

# Pitch tracker: "crepe" (torchcrepe, default), "rmvpe", "fcpe" or "pyin".
# rmvpe is the most robust on separated vocals; crepe is the default because
# torch is already present and it hands back a usable voicing confidence.
F0_METHOD = "crepe"
F0_MODEL = "full"
F0_HOP_S = 0.01

# Search range for sung pitch, in Hz. Generous enough for both a bass and a
# soprano; narrowing it reduces octave errors if a particular song misbehaves.
F0_MIN_HZ = 65.0
F0_MAX_HZ = 1100.0

# Median filter width applied to the semitone contour before note segmentation,
# in seconds. Smooths vibrato and tracker jitter so they do not each become a
# note boundary.
F0_MEDIAN_S = 0.08

# A sustained pitch move of at least this many semitones starts a new note.
NOTE_SPLIT_SEMITONES = 0.7

# Onset detection contributes the OTHER kind of slot boundary: a new syllable
# sung at the same pitch, which the pitch contour alone cannot see.
ONSET_BACKTRACK = True
ONSET_DELTA = 0.07

# Two boundaries closer together than this are treated as one.
BOUNDARY_MERGE_S = 0.05


# ---------------------------------------------------------------------------
# STAGE 3 -- SLOT CLEANUP AND WORD MAPPING     (built in commit 3)
# ---------------------------------------------------------------------------

# A gap longer than this between one note ending and the next starting breaks
# the melody into a new phrase. Words never straddle a phrase boundary.
PHRASE_GAP_S = 0.35

# Slots shorter than this are extractor blips: merged into whichever neighbour
# is closer in pitch rather than being given a syllable of their own.
MIN_SYLLABLE_S = 0.09

# Slots longer than this are held notes. They get SPLIT into several syllables
# of roughly TARGET_SYLLABLE_S each rather than having one syllable stretched
# absurdly across the whole thing.
MAX_SYLLABLE_S = 0.80
TARGET_SYLLABLE_S = 0.30
MAX_SLOT_SPLIT = 4

# What to do with the leftover slot when a phrase has an odd number of slots.
# Note that every word in the bank has an even syllable count (paska/perse/
# pillu = 2, pornolehti/paviaani = 4), so the remainder is always exactly 0 or
# 1 -- there is no other case to handle.
#
# "merge_last" - the last word's final syllable is held across the last two
#                slots, gliding to the second slot's pitch. Reads as a slur.
#                The default: least jarring of the three.
# "truncate"   - place one more 2-syllable word and hard-cut the overflow.
# "drop"       - leave the odd slot silent.
ODD_SLOT_POLICY = "merge_last"

# A clip syllable is time-stretched to fit its slot only when the required
# factor falls inside this range. Outside it, the syllable is placed at its
# natural length and either allowed to ring into the gap (slot longer) or cut
# with a short fade (slot shorter).
TIME_STRETCH_RANGE = (0.5, 2.0)

# Fade applied at a hard cut, in seconds. Short enough not to be heard as a
# fade, long enough to avoid a click.
EDGE_FADE_S = 0.015

# Word order. The bank is walked as a deterministic rotation from this seed;
# WORD_SEQUENCE overrides it entirely when set (also settable via --words).
WORD_ROTATION_SEED = 1987
WORD_SEQUENCE = None

# Optional: snap placed word onsets to the beat grid from stage 2. Off by
# default because in Mode A the original vocal's timing is already musical and
# quantising it only makes the result stiffer. BEAT_SUBDIVISION is the grid
# used when it IS on: 4 = sixteenth notes in 4/4.
SNAP_TO_BEAT = False
BEAT_SUBDIVISION = 4


# ---------------------------------------------------------------------------
# STAGE 4 -- PITCH SHIFTING                    (built in commit 4)
# ---------------------------------------------------------------------------

# Shift engine: "world" (pyworld) or "rubberband" (pylibrb).
#
# "world"      - WORLD vocoder. Formant correction is exact rather than
#                approximate: the spectral envelope is simply left alone while
#                F0 is replaced. Also lets one word follow a changing melody
#                across several notes in a single pass. Default.
# "rubberband" - Rubber Band R3 with formant preservation. Holds up better on
#                large shifts, where WORLD starts to sound vocoded.
SHIFT_ENGINE = "world"

# Formant handling. 1.0 = formants held exactly where they were, which is what
# keeps a shifted clip sounding like the same singer rather than a chipmunk.
# Values above 1.0 deliberately brighten; below 1.0 darken.
FORMANT_SCALE = 1.0

# Hard cap on how far a clip may be shifted, in semitones. Beyond this the
# shift is folded by whole octaves toward the target instead -- the word lands
# in a different octave from the original melody but keeps its own character,
# which sounds far better than a 14-semitone stretch.
SHIFT_CAP_SEMITONES = 7.0

# Chooses which clip to start from when a word has several recorded pitches:
# always the one whose original pitch is closest to the target, so the shift
# distance is as small as possible.
PREFER_NEAREST_SOURCE_PITCH = True


# ---------------------------------------------------------------------------
# STAGE 5 -- MIXING
# ---------------------------------------------------------------------------

# Target integrated loudness for each bus before summing, in LUFS. The word bus
# sits slightly hotter than the instrumental so the words stay intelligible
# over a full band.
WORD_BUS_LUFS = -14.0
INSTRUMENTAL_LUFS = -16.0

# Final limiter ceiling in dBFS, applied to the sum.
OUTPUT_PEAK_CEILING_DB = -1.0
