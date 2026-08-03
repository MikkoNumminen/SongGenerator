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
# WORD BANK EXTRACTION -- cutting clips out of a source scene
# ---------------------------------------------------------------------------
# Used by `python -m luokkaretki.extract_words`, not by the main pipeline.

# A region counts as sung while its envelope stays within this many dB of the
# loudest point in the scene. Lower (more negative) catches quiet tails and
# breath; higher cuts tighter and risks clipping word endings.
WORD_SILENCE_DB = -24.0

# Silences shorter than this do not split a word. Finnish double consonants
# (the "kk" in a sung paska, the "ll" in pillu) contain a real stop, so this
# has to exceed a plosive gap or single words get cut in half.
#
# Swept against the source scene: no value cleanly separates words there,
# because the delivery is close to legato. These defaults aim for slightly
# finer-than-phrase regions that are easy to adjust by hand, rather than
# pretending a threshold can find word boundaries that are not acoustically
# present. Override per run with --silence-db / --gap / --min-dur.
WORD_GAP_S = 0.06

# Regions shorter than this are noise, not words.
WORD_MIN_S = 0.15

# Breathing room kept around each cut, plus the fade applied at the edges so
# nothing clicks.
WORD_PAD_S = 0.04
WORD_FADE_S = 0.012

# Syllable nuclei are counted as peaks in the smoothed envelope. Two nuclei
# closer than this are one syllable; a peak shallower than the prominence is
# not a nucleus at all.
SYLLABLE_MIN_SEP_S = 0.09
SYLLABLE_PROMINENCE_DB = 3.0
SYLLABLE_SMOOTH_S = 0.04

# The bank, and how many syllables each word has. Used to guess which word a
# candidate might be, and by stage 3's mapping rule.
WORD_SYLLABLES = {
    "paska": 2,
    "perse": 2,
    "pillu": 2,
    "pornolehti": 4,
    "paviaani": 4,
    # A sustained shouted vowel, as in the "eee" that leads into paviaani. One
    # syllable, and the only odd-length unit in the bank -- which makes it the
    # natural filler for the single leftover slot an odd phrase produces, where
    # ODD_SLOT_POLICY previously had to fudge.
    "eee": 1,
    # Any other human shout, yell or non-verbal noise worth keeping. Counted as
    # one syllable because it occupies one slot however long it rings.
    "huuto": 1,
}

# Units that are shouts rather than words. Kept separate so the mapper can be
# told to use them for punctuation rather than treating them as vocabulary.
SHOUT_WORDS = ("eee", "huuto")

# How each word breaks into syllables.
#
# A melody slot holds exactly one syllable and a syllable clip fills exactly
# one slot, so a bank of syllables maps onto a tune 1:1 -- no counting, no
# leftover slot to fudge. It also means any word can be spelled from parts:
# paviaani needs no intact recording, only pa + vi + aa + ni.
#
# Whole-word and multi-word clips are still preferred wherever they exist,
# because they carry the singer's own transitions between syllables, and a
# transition cannot be rebuilt by butting two recordings together. Spelling is
# the fallback that makes a small bank go a very long way.
WORD_SPELLING = {
    "paska": ("pas", "ka"),
    "perse": ("per", "se"),
    "pillu": ("pil", "lu"),
    "pornolehti": ("por", "no", "leh", "ti"),
    "paviaani": ("pa", "vi", "aa", "ni"),
}

# How many spellings to build per word when several takes of a syllable exist.
# Every combination would be thousands of units for no musical gain.
COMPOSE_MAX_PER_WORD = 6

# Crossfade at a syllable join. Short enough not to smear the consonant,
# long enough to avoid a click where two recordings meet.
COMPOSE_CROSSFADE_S = 0.02

# A candidate with a single syllable nucleus lasting at least this long is
# probably a held shout rather than a clipped word, and gets flagged as such.
SHOUT_MIN_S = 0.35


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

# Unvoiced stretches shorter than this INSIDE a sung region are bridged rather
# than treated as note boundaries. Pitch trackers drop out briefly on
# consonants, breath and rough phonation; on the source scene 64 of 96 detected
# notes were the start of their own voiced run, i.e. sustained notes were being
# shredded by dropouts rather than genuinely re-attacked.
VOICED_GAP_FILL_S = 0.08

# A sustained pitch move of at least this many semitones starts a new note.
# Compared against the running median of the note so far, NOT against a
# quantised semitone grid: the source scene sits around MIDI 53.5, exactly
# between F3 and F#3, where any rounding scheme flips back and forth on tracker
# noise and invents a note boundary every few frames.
NOTE_SPLIT_SEMITONES = 0.7

# How long a deviation must persist before it counts as a new note rather than
# a blip, a scoop into pitch, or vibrato overshoot.
NOTE_SPLIT_SUSTAIN_S = 0.05

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

# How much of the track sings along, from 0.0 to 1.0.
#
#   0.0  every unit at its own recorded pitch. Clashes with the song, which is
#        exactly why it is funny -- the words obviously do not belong.
#   1.0  every unit on the melody. Sounds genuinely sung, and the absurdity
#        drains out of it precisely because it fits.
#
# The joke lives in the tension between those, so the interesting settings are
# in between: enough units land on the melody for it to read as singing, while
# enough stay put to keep it obviously wrong.
#
# 0.35 chosen by ear, from an A/B across 0.0 / 0.35 / 0.55 / 0.8 / 1.0: the
# leanest of them that still reads as singing. Note that the right number is
# partly a property of the song -- a melody sitting near the bank's own register
# needs less shifting to sound fitted, so it will feel more sung at the same
# setting than one that ranges far above it.
SHIFT_MIX = 0.35

# How closely the words should track the original singing, 0.0 to 1.0.
#
# This is the dial worth reaching for, because SHIFT_MIX alone does not mean the
# same thing from one song to the next. SHIFT_MIX counts how many units get
# shifted; MIMICRY measures how much of the original melody actually survives in
# the result, which is what you hear.
#
# The difference is octave folding. A song whose melody ranges far above the
# bank's register has most of its syllables folded, so they land on the right
# note NAME in the wrong octave -- recognisably the tune, still audibly wrong.
# That song sounds unfitted even when every single unit has been shifted. A song
# sitting near the bank's own register folds almost nothing, so the same
# SHIFT_MIX comes out sounding properly sung.
#
# Set MIMICRY and the tool solves for whatever SHIFT_MIX that particular song
# needs to get there. Set MIMICRY to None to drive SHIFT_MIX directly instead.
MIMICRY = 0.45

# Rendered on every run unless a single --mimicry is asked for. Resynthesis is
# done once and shared across all of them, so the whole set costs barely more
# than one, and picking by ear beats guessing a number up front. The right
# value varies by song anyway.
MIMICRY_VARIANTS = (0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 1.0)

# What a folded syllable is worth against one that landed exactly. It carries
# the right note name and the melody's shape, but in the wrong octave, so it
# mimics the original in part rather than fully.
FOLDED_FIT = 0.45

# Which units keep their own pitch when SHIFT_MIX is below 1.0:
#
# "furthest" - the ones whose target is furthest from their recorded pitch.
#              Those are the most absurd when left alone, and are also the ones
#              that shifting damages most, so the choice pays twice.
# "random"   - a seeded coin flip per unit, for an evenly scattered mix.
SHIFT_MIX_MODE = "furthest"


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
