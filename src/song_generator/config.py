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

# Ceiling on any single ffmpeg call, in seconds. ffmpeg decodes or encodes a
# full song in a few seconds, so this fires only when a malformed input or a
# stalled process has hung, which used to freeze a whole batch run forever
# with no output. Ten minutes is deliberately generous: far above any real
# call on this material, so a slow disk or a long mix never trips it, while a
# genuinely hung process still surfaces within the run instead of outliving it.
FFMPEG_TIMEOUT_S = 600.0

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
# Used by `python -m song_generator.extract_words`, not by the main pipeline.

# A region counts as sung while its envelope stays within this many dB of the
# loudest point in the scene. Lower (more negative) catches quiet tails and
# breath; higher cuts tighter and risks clipping word endings.
WORD_SILENCE_DB = -24.0

# Silences shorter than this do not split a word. Finnish double consonants
# (the "kk" in a sung bravo, the "ll" in delta) contain a real stop, so this
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
    "bravo": 2,
    "tango": 2,
    "delta": 2,
    "kilometer": 4,
    "calculator": 4,
    # The held shout, as in the "aah" that leads into calculator. It is THE
    # shout -- there is no separate generic yell. One syllable, and the only
    # odd-length unit in the bank, which makes it the natural filler for the
    # single leftover slot an odd phrase produces.
    "aah": 1,
}

# Units that are shouts rather than words. Kept separate so the mapper can be
# told to use them for punctuation rather than treating them as vocabulary.
SHOUT_WORDS = ("aah",)

# Whether a lone syllable may be sung on its own.
#
# Off. The point is to hear bravo, tango, delta, kilometer and aah calculator --
# actual words. A bank full of single syllables will happily fill every slot
# with "pas", "per", "ka", which fits the melody perfectly and says nothing.
#
# Syllable clips still earn their place: compose_words spells whole words out of
# them, reaching words that were never recorded intact. They just do that job
# instead of being sung bare.
PLACE_BARE_SYLLABLES = False

# ---------------------------------------------------------------------------
# DENSITY -- how much of the song gets words at all
# ---------------------------------------------------------------------------
# A smooth song wants space. Filling every slot the melody offers makes the
# words relentless and buries the joke; the original that worked best was much
# sparser than a full fill.

# Fraction of phrases that get words. The rest are left instrumental, so the
# track breathes and the words land as events rather than as a texture.
#
# The playfulness levels each set their own; this is what 'off' uses and
# what the levels were tuned against. Changing it moves nothing on an
# ordinary run. See PLAY_LEVELS.
PHRASE_FILL = 0.78

# Cap on how much of the track may be bare shouts. "aah" on its own is
# punctuation: excellent once a verse, wearing every few seconds. Without a cap
# it wins constantly, being the only unit that fits a single leftover slot.
#
# Raised from 0.12: at that level bravo, delta and kilometer dominated while
# aah barely registered, because a shout could only ever land in a leftover slot
# and most phrases had none.
#
# The playfulness levels each set their own; this is what 'off' uses and
# what the levels were tuned against. Changing it moves nothing on an
# ordinary run. See PLAY_LEVELS.
SHOUT_MAX_SHARE = 0.28

# Chance that a unit is introduced by a shout in the slot before it.
#
# This is where a shout stops being filler and becomes a gesture. In this genre
# it is *expected* before calculator -- that pairing is the whole joke -- so a
# recorded aah+calculator clip is always preferred when one fits, since it carries
# the real transition into the word.
#
# But a lead-in that only ever precedes one word is a rule rather than a joke.
# Letting it occasionally announce bravo or kilometer instead produces the
# unexpected combination, which is funnier precisely because the ear was set up
# for something else.
SHOUT_LEAD_IN_CHANCE = 0.30

# How much more likely a lead-in is when the thing it introduces is the payoff.
# Above 1.0 the expected pairing stays the common case and the surprises stay
# surprises.
SHOUT_LEAD_IN_CLIMAX_BIAS = 2.5

# Leave shouts alone: no pitch shift, no time stretch, no resynthesis.
#
# A shout is not a sung note. Its character is the rawness -- the crack, the
# strain, the hard attack -- and all of that is exactly what a vocoder smooths
# away. Run through WORLD it comes out as a smeared, melted vowel: technically
# on the right pitch, and no longer a shout at all.
#
# So a shout is dropped in as recorded. Inside a mixed unit like aah+calculator
# only the shout syllable is spared; the word after it still follows the melody.
SHOUT_KEEP_RAW = True


# ---------------------------------------------------------------------------
# CLIMAXES -- where aah and calculator are allowed to happen
# ---------------------------------------------------------------------------
# These two are not ordinary vocabulary. They belong together, and they land
# only when they are rare: a payoff saved for the peaks of the song, while
# bravo, tango, delta and kilometer carry everything else. Used freely they
# stop being a payoff and become the texture.

# Words reserved for the song's peaks. A unit containing any of these is
# refused everywhere else, whatever else it also contains -- so "aah+calculator"
# is climax-only while "bravo+tango+kilometer" is not.
#
# Only calculator. A bare "aah" is already rationed by SHOUT_MAX_SHARE, and
# listing it here made it compete for the same budget: being one syllable it
# fitted anywhere, so it took the climax slot and the calculator it was supposed
# to introduce never arrived.
CLIMAX_WORDS = ("calculator",)

# Fraction of phrases that count as peaks. Small on purpose: the point is
# scarcity, and a climax that recurs every few seconds is not a climax.
#
# The playfulness levels each set their own; this is what 'off' uses and
# what the levels were tuned against. Changing it moves nothing on an
# ordinary run. See PLAY_LEVELS.
CLIMAX_PHRASE_SHARE = 0.18

# Floor, because a share collapses on a short song. A 41-second track with six
# phrases got 14% of 6 = one peak, then a 25% chance of skipping even that, and
# duly produced no calculator at all. A proportion is the wrong tool when the
# count is small.
CLIMAX_MIN_PEAKS = 2

# Even within a peak, not every phrase takes one. Kept high: skipping is only
# interesting when there are several opportunities, and gambling away a scarce
# one just loses the payoff.
CLIMAX_USE_CHANCE = 0.9

# Chance that an ordinary phrase gets one anyway, purely as a joke. Rare on
# purpose: an unexpected one is funny, a predictable one is a pattern.
#
# The playfulness levels each set their own; this is what 'off' uses and
# what the levels were tuned against. Changing it moves nothing on an
# ordinary run. See PLAY_LEVELS.
CLIMAX_WILDCARD_CHANCE = 0.05

# How a peak is recognised. Climaxes tend to be both higher and louder than the
# rest, so phrases are ranked on both and the top few taken.
CLIMAX_PITCH_WEIGHT = 1.0
CLIMAX_LOUDNESS_WEIGHT = 0.7

# How strongly to prefer longer units over short ones when both fit.
# 0 = pick purely on how naturally the clip fills the time, which favours
# short units and makes the track busy. Higher = fewer, longer placements.
#
# Kept mild. At 1.4 the bonus overwhelmed the time-fit entirely and the longest
# clip in the bank won almost every slot, so the track became one phrase on
# repeat -- sparse, but monotonous, which is its own kind of wrong.
PREFER_LONGER_UNITS = 0.45

# How each word breaks into syllables.
#
# A melody slot holds exactly one syllable and a syllable clip fills exactly
# one slot, so a bank of syllables maps onto a tune 1:1 -- no counting, no
# leftover slot to fudge. It also means any word can be spelled from parts:
# calculator needs no intact recording, only pa + vi + aa + ni.
#
# Whole-word and multi-word clips are still preferred wherever they exist,
# because they carry the singer's own transitions between syllables, and a
# transition cannot be rebuilt by butting two recordings together. Spelling is
# the fallback that makes a small bank go a very long way.
WORD_SPELLING = {
    "bravo": ("bra", "vo"),
    "tango": ("tan", "go"),
    "delta": ("del", "ta"),
    "kilometer": ("ki", "lo", "me", "ter"),
    "calculator": ("cal", "cu", "la", "tor"),
}

# Extra syllable fragments a clip name may use, beyond the ones that appear in
# WORD_SPELLING. Somebody naming by ear writes what they hear, and a sung
# stutter ("pi pillu", "pe perse") is a real thing in the recordings that no
# canonical spelling contains. Listing them here lets those names parse instead
# of being refused, which is the difference between a clip being usable and
# sitting on disk. They are fragments, never sung alone.
EXTRA_SYLLABLES: tuple[str, ...] = ()

# Letters a held shout may be spelled with. A shout has no canonical spelling:
# someone naming clips by ear writes what they heard, so aah, aaah, ahh and
# aaahh all have to read as the same gesture. Any run of these letters does.
#
# No bank word begins with one of them, which is what keeps the rule from
# eating the start of a real word.
SHOUT_CHARS = "ah"

# Stripped from the front of a source folder name when shortening it for a
# clip filename. Source files often share a common prefix, which carries no
# information and makes every candidate name longer. Empty means strip nothing.
SOURCE_NAME_PREFIX = ""

# How many spellings to build per word when several takes of a syllable exist.
# Every combination would be thousands of units for no musical gain.
COMPOSE_MAX_PER_WORD = 6

# Crossfade at a syllable join. Short enough not to smear the consonant,
# long enough to avoid a click where two recordings meet.
COMPOSE_CROSSFADE_S = 0.02

# A candidate with a single syllable nucleus lasting at least this long is
# probably a held shout rather than a clipped word, and gets flagged as such.
SHOUT_MIN_S = 0.35

# How recogniser output is scored against a bank word. Two stages score the
# same clips with the one function in util.py: label_words against a
# transcript of the whole vocal, precheck against per-clip guesses. The
# numbers live here so retuning one stage cannot leave the other behind.
#
# A clean prefix of a target word scores at least MATCH_PREFIX_SCORE. A long
# word heard as its own first syllables ("kilo" for "kilometer") does poorly
# on whole-word ratio yet is very likely that word. 0.75 clears the accept
# threshold in label_words (0.55), so the hit is kept as a hint, and stays
# below its confident-rename bar (0.85), so a prefix alone can never rename a
# clip to a bank name without someone listening to it first.
MATCH_PREFIX_SCORE = 0.75

# The prefix reward needs at least this many letters heard. Two or three
# letters are the start of half the recogniser's noise; four is the shortest
# run that is plausibly the beginning of the word rather than a coincidence.
MATCH_PREFIX_MIN_LEN = 4


# ---------------------------------------------------------------------------
# BANK STANDARDISATION -- assembling clips that sit together
# ---------------------------------------------------------------------------
# A one-time pass over a finished bank, producing a DERIVATIVE tier beside it.
# Edges and levels only: what a word sounds like is the whole point of the bank
# and is never touched. No denoise, no EQ, no compression, no resynthesis.
#
# Used by `python -m song_generator.standardize`, not by the main pipeline.

# Suffix appended to a bank directory to name its standardised tier, so
# words_hq becomes words_hq.std. A sibling rather than a subdirectory, because
# the result is a complete bank in its own right: --words-dir points at it and
# every existing tool reads it with no special case.
STD_SUFFIX = ".std"

# The manifest filename inside a standardised tier. Its presence is also what
# tells the runtime these clips are already levelled, so it must not skip
# level_clip over them a second time.
STD_MANIFEST = "standardized.json"

# How far below a clip's own peak counts as dead air. Much deeper than
# WORD_SILENCE_DB, which finds sung regions inside a scene; this only has to
# find the silence a cut left at each end, and going deeper is the conservative
# direction -- it finds less, and trims less.
STD_DEAD_AIR_DB = -45.0

# Silence deliberately left in front of the first sound and after the last.
# Measured on the bank: heads carry 35 ms of silence on average and never more
# than 58 ms, so a 25 ms guard removes about 10 ms from a typical clip. That is
# the intent. A soft word start misjudged by a few milliseconds is audible and
# unrecoverable, a hair of leading silence is neither.
STD_HEAD_GUARD_S = 0.025
STD_TAIL_GUARD_S = 0.040

# Hard ceiling on the head trim, whatever the envelope claims. Nothing in the
# current bank comes close; it exists so that a future clip opening on a quiet
# breath cannot have that breath removed by a detector that read it as silence.
STD_HEAD_CAP_S = 0.120

# Edge fades, applied after trimming, purely to stop a click at the cut.
# Asymmetric on purpose: a long fade-in is what softens an attack, and the
# attack is the character of a shout, so the head gets the shortest fade that
# still removes the click. The tail can afford more and nobody hears it.
STD_FADE_IN_S = 0.004
STD_FADE_OUT_S = 0.012

# Target loudness for a sung word, LUFS. Gated integrated loudness rather than
# peak or RMS, because it matches how the ear ranks two clips against each
# other. Every clip in the bank is longer than the 400 ms gating window, so
# this measures properly rather than falling back to something cruder.
#
# Set near the RMS target the runtime used before, so the balance against the
# instrumental bed does not move when a bank is standardised.
CLIP_TARGET_LUFS = -20.0

# How the shout is levelled. It is not ordinary vocabulary: SHOUT_KEEP_RAW
# already exempts it from resynthesis on the grounds that its rawness IS the
# sound, and level is part of how it was recorded.
#
# "offset"      - shouts get their own target, CLIP_TARGET_LUFS minus
#                 SHOUT_LUFS_OFFSET. Evens out shout against shout without
#                 flattening the shout-to-word relationship the bank has.
# "as_recorded" - shouts are not levelled at all. Trimmed and faded like
#                 everything else, otherwise exactly as recorded.
SHOUT_LEVEL_MODE = "offset"

# How far below the word target a shout sits, in dB, when SHOUT_LEVEL_MODE is
# "offset". Measured rather than chosen: across the bank, bare shouts read
# 2.7 dB below sung words over their loudest 400 ms. Rounded to 3.
SHOUT_LUFS_OFFSET = 3.0


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

# A phrase may not run longer than this. A gap alone does not find phrase ends
# in continuous delivery: a rapped verse never stops for 0.35s, so a whole
# 25-second section came out as ONE phrase on a test song. That matters because
# density is decided per phrase, so dropping one such phrase silenced a quarter
# of the song and the words did not start until 25s in while the original
# started at 4s.
#
# A phrase over the cap is split at its widest internal gap, which is the most
# phrase-like boundary available even when it is not a real pause.
PHRASE_MAX_S = 6.0

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
# Note that every word in the bank has an even syllable count (bravo/tango/
# delta = 2, kilometer/calculator = 4), so the remainder is always exactly 0 or
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

# Prebuilt banks, switchable per run with --bank. Both are built ahead of time
# and the song's stems are cached, so switching costs only a re-render.
#
# "curated" - clips named by ear. The words are actually words, which is the
#             whole point, so this is the default.
# "chaos"   - every candidate clip taken as raw material, names ignored. The
#             mapper only needs each clip's syllable count and pitch, so this
#             still sings; it just stops saying anything.
BANKS = {
    # Cut from Mel-Band Roformer stems. Around 47% of each clip's content in
    # the older bank turned out to be instrumental Demucs had left behind,
    # audible as a synthesiser tone under some words. Cleaner separation also
    # lets pitch detection read the sung note more accurately, so clips match
    # their targets better and fold less often.
    "curated": "words_hq",
    # The original Demucs-cut bank, kept for comparison.
    "demucs": "words",
    "chaos": "words_chaos",
}
DEFAULT_BANK = "curated"

# Optional: snap placed word onsets to the beat grid from stage 2. Off by
# default because in Mode A the original vocal's timing is already musical and
# quantising it only makes the result stiffer. BEAT_SUBDIVISION is the grid
# used when it IS on: 4 = sixteenth notes in 4/4.
SNAP_TO_BEAT = False
BEAT_SUBDIVISION = 4


# ---------------------------------------------------------------------------
# PLAYFULNESS -- how the automation plays with the words
# ---------------------------------------------------------------------------
# The bank is recorded phrases, not words, so left alone the tool can only
# repeat sequences somebody once sang. arrange.py cuts the words back out of
# those phrases using the boundaries build_bank already measured, which lets
# the automation ask for orders that were never recorded.
#
# One level is chosen per run. It produces ONE arrangement, and that single
# arrangement is then rendered across the mimicry ladder exactly as before.
# Playfulness and mimicry are different questions and do not multiply.

# Words that must appear somewhere in every song. None means every word in
# WORD_SYLLABLES. A bank with a word that is deliberately occasional should
# name the required ones in vocabulary_local.py instead of changing this.
PLAY_REQUIRED_WORDS: tuple[str, ...] | None = None

# The words a song is mostly made of. None means every short word that is
# neither the shout nor the payoff. A bank whose core is narrower than that
# should name it in vocabulary_local.py.
PLAY_CORE_WORDS: tuple[str, ...] | None = None

# How many times to redraw an arrangement that failed the coverage rule before
# repairing it by hand. Each retry is a fresh seed derived from the first, so
# the run stays reproducible from the seed it reports.
PLAY_COVERAGE_TRIES = 12

PLAY_DEFAULT_LEVEL = "conservative"

# Levels rendered when no single one is asked for. Both, always: which is
# funnier is decided by ear, and a run that produced one and offered the other
# had not finished. Each is its own arrangement with its own seed and its own
# log, so either can be brought back alone.
PLAY_BOTH_LEVELS = ("conservative", "wild")

# The two levels, as parameter sets.
#
#   invent_combos    how many word orders to build that were never recorded.
#                    They compete with the real clips on fit and mostly lose,
#                    which is intended: a recorded phrase carries the singer's
#                    own transition and a crossfade does not.
#   slice_words      whether single words cut out of phrases may be sung alone.
#   repeat_penalty   cost added for reusing the label just used. The bank is
#                    small and without this one clip wins a whole song.
#   unused_bonus     bonus for a label not yet heard in this song, which is
#                    what spreads the vocabulary out.
#   tie_band         how far below the best a candidate may score and still be
#                    drawn at random. The one knob that really trades fit for
#                    surprise.
#   bare_shout       chance that a placed shout is left with nothing after it.
#                    Rare on purpose. The joke is that the ear is set up for
#                    a word and does not get one, and it dies if it recurs.
#                    Only the next unit is dropped, never the whole phrase.
#   detach_pairing   chance the shout and the payoff are allowed to go their
#                    separate ways at a peak. They travel together by default,
#                    because the recording of them together is the one clip
#                    the whole bank is built around.
#   phrase_fill      how many phrases get words at all. Lower leaves more of
#                    the song instrumental, so the words land as events.
#   max_gap_s        longest stretch a run may leave wordless by thinning.
#                    phrase_fill alone is a proportion of PHRASES, which stopped
#                    meaning a proportion of TIME once phrases were capped in
#                    length, so the holes have to be bounded directly.
#   shout_share      how much of the song may be shouts. The base setting keeps
#                    the shout as punctuation; these levels want it as a voice.
#   climax_share     how many phrases count as peaks, and so how often the
#                    payoff is allowed to land.
#   climax_wildcard  chance an ordinary phrase takes the payoff anyway.
#   chant_chance     chance that whatever was just sung gets said again, and
#                    again. Repetition is funny when it is obviously on
#                    purpose, which is why it is a decision here rather than
#                    something repeat_penalty is simply relaxed into. That knob
#                    still stops the other kind of repetition, where one clip
#                    quietly wins every slot because it fits best.
#   chant_max        how many extra times, at most.
#   core_bonus       how strongly the words that carry the song are preferred.
#                    Without this the shout wins on fit alone, being a third of
#                    the recordings and short enough for any slot, and the
#                    result is a song of shouting with words in the gaps.
#   crown_cost       what including a long word costs. It is rarer than the
#                    core on purpose and finishes a combination rather than
#                    carrying one.
#   shout_cost       what including the shout costs, on top of its budget.
#   slice_cost       what using a word cut out of a clip costs, against a clip
#                    the singer actually sang whole.
#   joined_cost      what an order nobody sang costs. Real words, but the
#                    movement between them is a crossfade.
#   spelled_cost     what a word assembled from syllable fragments costs.
#                    Charged hardest: whole words almost every time, and a
#                    spelling only when nothing recorded will do.
#   extra_cost       what a word that is none of the above costs. A bank
#                    accumulates words the song is not really about, and
#                    unused_bonus rewards them for sounding new. Charged
#                    heavily: these are a garnish that should surprise when it
#                    turns up, not part of the regular vocabulary.
PLAY_LEVELS = {
    # Recognisable and tidy. Keeps close to what was recorded, and mostly
    # varies which take of a phrase is used rather than inventing orders.
    "conservative": {
        "slice_cost": 0.20,
        "joined_cost": 0.55,
        "spelled_cost": 1.10,
        "extra_cost": 1.60,
        "core_bonus": 0.9,
        "crown_cost": 0.22,
        "shout_cost": 0.55,
        "invent_combos": 10,
        "slice_words": True,
        "repeat_penalty": 0.85,
        "unused_bonus": 0.25,
        "tie_band": 0.35,
        "bare_shout": 0.05,
        "detach_pairing": 0.15,
        "phrase_fill": 0.88,
        "max_gap_s": 3.0,
        "shout_share": 0.22,
        "climax_share": 0.18,
        "climax_wildcard": 0.06,
        "chant_chance": 0.14,
        "chant_max": 2,
    },
    # Less predictable. Invents more orders, spreads the vocabulary harder,
    # chooses from a wider band so fit steers less, and leaves more air.
    # Less predictable, NOT emptier. An earlier pass thinned the song as well
    # as scrambling it and the result had almost no words in it, which is a
    # different thing from being unpredictable.
    "wild": {
        "slice_cost": 0.10,
        "joined_cost": 0.32,
        "spelled_cost": 0.80,
        "extra_cost": 1.25,
        "core_bonus": 0.8,
        "crown_cost": 0.2,
        "shout_cost": 0.3,
        "invent_combos": 34,
        "slice_words": True,
        "repeat_penalty": 0.60,
        "unused_bonus": 0.70,
        "tie_band": 0.50,
        "bare_shout": 0.07,
        "detach_pairing": 0.45,
        "phrase_fill": 0.85,
        "max_gap_s": 3.5,
        "shout_share": 0.34,
        "climax_share": 0.30,
        "climax_wildcard": 0.12,
        "chant_chance": 0.30,
        "chant_max": 4,
    },
    # Today's behaviour, for comparing against.
    "off": {
        "slice_cost": 0.0,
        "joined_cost": 0.0,
        "spelled_cost": 0.0,
        "extra_cost": 0.0,
        "core_bonus": 0.0,
        "crown_cost": 0.0,
        "shout_cost": 0.0,
        "invent_combos": 0,
        "slice_words": False,
        "repeat_penalty": 0.0,
        "unused_bonus": 0.0,
        "tie_band": 0.35,
        "bare_shout": 0.0,
        "detach_pairing": 1.0,
        "phrase_fill": PHRASE_FILL,
        "max_gap_s": 0.0,
        "shout_share": SHOUT_MAX_SHARE,
        "climax_share": CLIMAX_PHRASE_SHARE,
        "climax_wildcard": CLIMAX_WILDCARD_CHANCE,
        "chant_chance": 0.0,
        "chant_max": 0,
    },
}

# Where arrangements are written, under the song's work directory. Appended to,
# never overwritten, so an older arrangement stays reproducible.
PLAY_LOG_DIR = "arrangements"


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

# Formant handling for the rubberband engine. WORLD does not use this: it
# preserves the envelope by construction, leaving it untouched while F0 is
# replaced.
#
# 1.0 = formants held exactly where they were, which is what keeps a shifted
# clip sounding like the same singer rather than a chipmunk. Values above 1.0
# deliberately brighten; below 1.0 darken.
#
# Note this is the TOOL's convention, not Rubber Band's, which reads 1.0 as
# "do not scale the envelope" and so produces exactly the chipmunk 1.0 is meant
# to avoid. pitchshift translates.
FORMANT_SCALE = 1.0

# Hard cap on how far a clip may be shifted, in semitones. Beyond this the
# shift is folded by whole octaves toward the target instead: the word lands in
# a different octave from the original melody but keeps its own character.
#
# Was 7.0, on the assumption that a bigger stretch would sound worse than
# landing an octave out. Measured and then listened to, and the assumption was
# wrong on this material.
#
# Sweeping the engine from 0 to 16 semitones against each clip's own unshifted
# self: formants never drift by more than 4%, so the chipmunk this cap was
# protecting against does not happen at any distance the tool would ask for.
# What does change past 9 is harmonicity, +3.3 dB at 12 against +0.8 at 7, and
# the loudness envelope, drifting twice as far. Read as a cost, that suggested
# 9 as the free option and 12 as a trade.
#
# It is not a trade. At 12 both test songs sound better, judged by ear on whole
# renders at mimicry 1.00, which is where a bad shift has nowhere to hide. What
# the numbers called smoothing reads as the words being sung rather than
# approximated, and it is swamped by what folding stops costing: on cardib_up
# the median shift goes from 2.1 to 7.6 semitones, so most of the song lands on
# the note the singer actually hit, and its ceiling goes from 0.68 to 0.96.
#
# Ceilings at 12 against 7: cardib_up 0.96 from 0.68, musichyva 0.86 from 0.75,
# rocketman 0.99 from 0.87, musickorea 0.60 from 0.51.
#
# Beyond 12 is untested by ear. 15 measures worse again and buys little.
SHIFT_CAP_SEMITONES = 12.0

# How long a word takes to slide from one of its syllables' pitches to the
# next, in milliseconds. 0 disables it and the pitch steps on the frame
# boundary, which is what this did before.
#
# The step is what makes a word read as a run of syllables rather than as one
# word carrying a tune. A sung voice arrives at a note through its approach,
# and the ear hears the approach as much as the note.
#
# Applies inside a word only, and never across silence: the gap between two
# words is where the pitch is allowed to change outright. WORLD only, because
# Rubber Band transposes by a fixed amount per pass and cannot follow a contour
# within one; that engine still steps.
#
# 60ms is roughly a fast singer's portamento. Long enough to be heard as a
# slide rather than a smeared edge, short enough that a syllable of ordinary
# length still spends most of itself on its own pitch.
GLIDE_MS = 60.0

# Prefer the take whose recorded pitch is nearest the note it has to land on,
# so it is shifted as little as possible.
#
# This matters more than it sounds. A word moved a couple of semitones still
# sounds like the singer; one moved past SHIFT_CAP_SEMITONES has to be folded by
# whole octaves and lands in the wrong register, carrying the tune only in part.
# Choosing the nearest take avoids most of that for free, because the bank
# usually holds the same word at several pitches.
PREFER_NEAREST_SOURCE_PITCH = True

# How strongly pitch competes with the other two selection criteria (how
# naturally a clip fills the time, and the preference for longer units).
#
# Measured rather than guessed: at 0 -- which is what the code did before this
# was wired up at all -- 43% of syllables on the test song had to be octave
# folded, against 1% if takes were chosen by pitch alone. Too high and the
# tightest-pitched clip wins every slot and the track loses its variety, which
# is the same failure PREFER_LONGER_UNITS had at 1.4.
PITCH_FIT_WEIGHT = 0.9

# Extra cost for a candidate that cannot be reached without octave folding.
# Folding is not merely a bigger shift -- it changes the register, so the
# melody survives only in part. Worth avoiding even at some cost elsewhere.
FOLD_PENALTY = 0.6

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

# Every bank clip is levelled to this before anything else, in dBFS RMS.
#
# The clips come from dozens of sources at wildly different levels: a shouted
# aah and a muttered syllable are not remotely the same loudness, and matching
# only the finished word bus leaves that unevenness intact inside it. RMS rather
# than LUFS because most clips are far shorter than the 400 ms LUFS gating
# window and would simply fail to measure.
CLIP_TARGET_RMS_DB = -20.0

# Ceiling for a levelled clip, so raising a quiet one cannot clip it.
CLIP_PEAK_CEILING = 0.95

# Final limiter ceiling in dBFS, applied to the sum.
OUTPUT_PEAK_CEILING_DB = -1.0


# ---------------------------------------------------------------------------
# LOCAL OVERRIDES
# ---------------------------------------------------------------------------
# The vocabulary above is an example, not a fixture. Any set of short sung
# clips works, so the words a particular bank uses are a local matter.
#
# Dropping a vocabulary_local.py beside this file lets it replace any setting
# here, so a private word bank does not require editing a published file and a
# clone does not inherit somebody else's vocabulary. The file is gitignored.
#
#     # src/song_generator/vocabulary_local.py
#     WORD_SYLLABLES = {"foo": 2, "barbaz": 4, "ooh": 1}
#     WORD_SPELLING = {"foo": ("f", "oo"), "barbaz": ("bar", "b", "a", "z")}
#     SHOUT_WORDS = ("ooh",)
#     CLIMAX_WORDS = ("barbaz",)
#     SHOUT_CHARS = "oh"
# SONG_GENERATOR_NO_LOCAL_VOCAB disables the override. The test suite sets it,
# so tests exercise the shipped example vocabulary and pass or fail the same way
# on every machine, rather than depending on whichever words happen to be
# installed locally.
import os as _os

if not _os.environ.get("SONG_GENERATOR_NO_LOCAL_VOCAB"):
    try:  # pragma: no cover - presence depends on the machine, not the code
        from .vocabulary_local import *
    except ImportError:
        pass


def validate_vocabulary() -> list[str]:
    """Problems with the active vocabulary, as readable sentences.

    Every one of these fails silently rather than loudly. A spelling naming a
    word that no longer exists simply stops composing; a shout letter at the
    start of a real word quietly eats it during parsing. The result is a bank
    that builds, runs, and is wrong.

    Worth running after any change to the vocabulary, and especially after
    writing a local override, where it is easy to redefine one table and forget
    the one that depends on it.
    """
    problems: list[str] = []

    orphans = sorted(set(WORD_SPELLING) - set(WORD_SYLLABLES))
    if orphans:
        problems.append(
            f"WORD_SPELLING spells {orphans}, which are not in WORD_SYLLABLES. "
            "Those words cannot be composed from syllables."
        )

    for word, parts in WORD_SPELLING.items():
        expected = WORD_SYLLABLES.get(word)
        if expected is not None and len(parts) != expected:
            problems.append(
                f"{word!r} is {expected} syllables in WORD_SYLLABLES but "
                f"{len(parts)} in WORD_SPELLING: {list(parts)}"
            )

    for name, group in (("SHOUT_WORDS", SHOUT_WORDS), ("CLIMAX_WORDS", CLIMAX_WORDS)):
        missing = sorted(set(group) - set(WORD_SYLLABLES))
        if missing:
            problems.append(f"{name} names {missing}, which are not in WORD_SYLLABLES.")

    words = sorted(WORD_SYLLABLES)
    for short in words:
        for long in words:
            if short != long and long.startswith(short):
                problems.append(
                    f"{short!r} is a prefix of {long!r}. Filename parsing takes the "
                    "longest match, so the shorter word can never be named on its own."
                )

    # The one that is easiest to get wrong and hardest to notice.
    for word in WORD_SYLLABLES:
        if word not in SHOUT_WORDS and word and word[0] in SHOUT_CHARS:
            problems.append(
                f"{word!r} starts with {word[0]!r}, which is in SHOUT_CHARS. "
                "A run of shout letters would be read as a shout instead."
            )
    for word, parts in WORD_SPELLING.items():
        for part in parts:
            if part and part[0] in SHOUT_CHARS:
                problems.append(
                    f"syllable {part!r} of {word!r} starts with a shout letter."
                )

    return problems
