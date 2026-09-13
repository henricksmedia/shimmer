"""The rules the screens show, stated once.

The old browser kept its own copies of at least twelve engine rules
(docs/ARCHITECTURE.md §7): loudness choices in three places, format
ceilings, EQ limits, stage lists. Now GET /api/rules serves this module, and
the screens read it instead of copying it.

- CARDS: the "What do you hear?" choices, in the author-approved wording
  (the mockup; ARCHITECTURE §19.3). A card with tool=None has no fix that
  has passed its tests yet, and the screen says so plainly (§19.2 D3).
- LOUDNESS_TARGETS: Commercial is the default (§19.2 D1). The keys stay as
  they were, so saved settings keep working.
- FORMATS: what each export writes, and its true-peak ceiling.
- EQ_LIMITS: the user EQ's limits.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

# ── The "What do you hear?" cards ───────────────────────────────────────

TOOLS = ("notch", "declick", "deesser", "dynamic_eq", "tone_target", "loudness_target")

# The name each tool shows on screen, and which tools are built. A card whose
# tool is not built yet says so plainly, rather than seem to do something
# (docs/ARCHITECTURE.md §19.2 D3).
TOOL_LABELS = {"notch": "Notch filter", "declick": "De-click", "deesser": "De-esser",
               "dynamic_eq": "Dynamic EQ", "tone_target": "Tone target",
               "loudness_target": "Loudness target"}
TOOLS_READY = ("notch", "tone_target", "loudness_target")


@dataclass(frozen=True)
class Card:
    key: str
    label: str
    descriptor: str            # the short line under the label
    tip: str                   # the longer help text
    icon: str                  # Material Symbols name
    group: str                 # "artifacts" or "tone_level"
    tool: Optional[str]        # a key in TOOLS, or None: no fix yet
    band_hz: Optional[Tuple[float, Optional[float]]]   # (low, high); high None = "and up"
    # Where the Amount slider starts when the card is turned on. Fixed tones
    # starts at full depth: the notch is the one tool proven safe and
    # effective (96 %), and 1.1.1 applied it at full depth.
    default_amount: float = 0.5


CARDS: Tuple[Card, ...] = (
    Card("shimmer", "Shimmer", "Fizzy, flickering hiss up top",
         "A flickering, fizzy texture in the top end, riding on cymbals and vocals.",
         "auto_awesome", "artifacts", None, (5000.0, 12000.0)),
    Card("tones", "Fixed tones", "A whistle or whine that never changes",
         "Steady tones the generator leaves at one pitch for the whole song.",
         "sports", "artifacts", "notch", None, default_amount=1.0),
    Card("sibilance", "Sibilance", "Harsh, spitty “s” and “sh”",
         "Sharp consonants on vocals that turn into hiss or distortion.",
         "record_voice_over", "artifacts", "deesser", (4000.0, 10000.0)),
    Card("clicks", "Clicks and crackle", "Short pops, ticks or static",
         "Brief clicks, pops or crackle, often on consonants and drum hits.",
         "bolt", "artifacts", "declick", (2000.0, None)),
    Card("harshness", "Harshness", "Piercing, painful upper mids",
         "Resonances around 2–4 kHz that come and go with the music.",
         "graphic_eq", "artifacts", "dynamic_eq", (2000.0, 4000.0)),
    Card("phasiness", "Phasiness", "Grainy or watery reverb tails",
         "Reverb and echoes that sound grainy, watery or warbly.",
         "grain", "artifacts", None, (3000.0, 12000.0)),
    Card("mud", "Low-mid build-up", "Muddy, boxy, words hard to hear",
         "Too much energy around 200–500 Hz, so the mix sounds thick and cloudy.",
         "foggy", "tone_level", "dynamic_eq", (200.0, 500.0)),
    Card("air", "Lack of air", "Dull, no sparkle",
         "Not enough top end, like a blanket over the speakers.",
         "brightness_low", "tone_level", "tone_target", (8000.0, 16000.0)),
    Card("loudness", "Loudness", "Quieter than released music",
         "Plays quieter than released songs when a player does not match levels.",
         "volume_down", "tone_level", "loudness_target", None),
)

CARD_KEYS = tuple(c.key for c in CARDS)
DEFAULT_AMOUNT = 0.5           # a card turned on starts halfway


def card(key: str) -> Card:
    for c in CARDS:
        if c.key == key:
            return c
    raise KeyError(key)


# ── Loudness choices ────────────────────────────────────────────────────

@dataclass(frozen=True)
class LoudnessTarget:
    key: str
    lufs: float
    label: str
    sublabel: str
    default: bool


LOUDNESS_TARGETS: Tuple[LoudnessTarget, ...] = (
    LoudnessTarget("cd", -9.0, "Commercial", "As loud as most released songs", True),
    LoudnessTarget("loud", -11.0, "Balanced", "A little quieter, with more punch left in", False),
    LoudnessTarget("streaming", -14.0, "Streaming standard",
                   "The level streaming apps play songs at; sounds quiet in other players",
                   False),
)

DEFAULT_LOUDNESS = next(t.key for t in LOUDNESS_TARGETS if t.default)


def loudness_target(key: str) -> LoudnessTarget:
    for t in LOUDNESS_TARGETS:
        if t.key == key:
            return t
    raise KeyError(key)


# ── Export formats ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class Format:
    key: str
    ext: str
    label: str
    subtype: Optional[str]     # WAV/FLAC sample format; None for lossy
    sr: Optional[int]          # fixed output rate, or None: the source's
    bits: Optional[int]        # 16 means TPDF dither is applied
    lossy: bool
    ceiling_dbtp: float
    bitrate: Optional[str]
    quality: Optional[float] = None   # OGG Vorbis quality, 0-1; None = libsndfile's default


# Lossy ceilings leave room for the codec's overshoot, set from measurement
# (ARCHITECTURE §19.1 item 12; testing/scripts/lossy_ceilings.py,
# 2026-09-12, both test mixes at -9 LUFS). export() also checks every lossy
# file after encoding and corrects it, so these only need to be close.
#   OGG at libsndfile's default quality overshot by up to +2.2 dB (decoded
#   +0.26 dBTP); at quality 0.8 by +0.17 to +0.98, so -2.0 decodes at
#   -1.29 to -1.91.
#   MP3 320k overshot by +0.58 to +1.24, mid-song (VBR V0 was no better on
#   both mixes).
#   M4A, ffmpeg's built-in AAC encoder, overshot by up to +2.9 dB, mid-song on
#   sharp hits; 320k and VBR were worse (testing/scripts/codec_probe.py). On
#   drum-heavy songs export() turns an M4A down by up to ~2.5 dB to keep it
#   from clipping, and says so in its report.
FORMATS: Tuple[Format, ...] = (
    Format("wav", ".wav", "WAV 24-bit", "PCM_24", None, 24, False, -1.0, None),
    Format("wav16", ".wav", "WAV 16-bit 44.1 kHz", "PCM_16", 44100, 16, False, -1.0, None),
    Format("flac", ".flac", "FLAC", "PCM_24", None, 24, False, -1.0, None),
    Format("mp3", ".mp3", "MP3 320 kbps", None, None, None, True, -2.0, "320k"),
    Format("ogg", ".ogg", "OGG Vorbis", None, None, None, True, -2.0, None, quality=0.8),
    Format("m4a", ".m4a", "M4A (AAC)", None, None, None, True, -2.0, "256k"),
)

DEFAULT_FORMAT = "wav"


def output_format(key: str) -> Format:
    k = str(key or "").strip().lower().lstrip(".")
    for f in FORMATS:
        if f.key == k:
            return f
    raise KeyError(key)


# ── The stages a render and export report, in signal order ──────────────
# The progress window lights these by key as the server reports them
# (shimmer.core.render, shimmer.api.render).

STAGES = (
    ("load", "Read"), ("edit", "Trim"), ("rate", "Sample rate"), ("fixes", "Fixes"),
    ("tone", "Tone"), ("eq", "EQ"), ("master", "Master"), ("export", "Export"),
    ("report", "Report"),
)


# ── Mastering tone (1.1.1's controls, kept) ─────────────────────────────

TONE_INTENSITIES = ("low", "med", "high")
TONE_TILTS = ("warmer", "warm", "neutral", "bright", "brightest")


# ── User EQ ─────────────────────────────────────────────────────────────

EQ_LIMITS = {"max_bands": 12, "gain_limit_db": 18.0,
             "freq_min_hz": 20.0, "freq_max_hz": 20000.0, "q_min": 0.1, "q_max": 18.0}
EQ_TYPES = ("bell", "low_shelf", "high_shelf", "highpass", "lowpass", "notch")
