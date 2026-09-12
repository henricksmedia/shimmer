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


CARDS: Tuple[Card, ...] = (
    Card("shimmer", "Shimmer", "Fizzy, flickering hiss up top",
         "A flickering, fizzy texture in the top end, riding on cymbals and vocals.",
         "auto_awesome", "artifacts", None, (5000.0, 12000.0)),
    Card("tones", "Fixed tones", "A whistle or whine that never changes",
         "Steady tones the generator leaves at one pitch for the whole song.",
         "sports", "artifacts", "notch", None),
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


# Lossy ceilings leave room for the decoder's overshoot. -1.5 is the
# starting point; each codec's overshoot is measured and its ceiling set
# from that, so the decoded file stays at or under -1.0 dBTP (ARCHITECTURE
# §19.1 item 12: OGG written at -1.5 decoded at -0.48).
FORMATS: Tuple[Format, ...] = (
    Format("wav", ".wav", "WAV 24-bit", "PCM_24", None, 24, False, -1.0, None),
    Format("wav16", ".wav", "WAV 16-bit 44.1 kHz", "PCM_16", 44100, 16, False, -1.0, None),
    Format("flac", ".flac", "FLAC", "PCM_24", None, 24, False, -1.0, None),
    Format("mp3", ".mp3", "MP3 320 kbps", None, None, None, True, -1.5, "320k"),
    Format("ogg", ".ogg", "OGG Vorbis", None, None, None, True, -1.5, None),
    Format("m4a", ".m4a", "M4A (AAC)", None, None, None, True, -1.5, "256k"),
)

DEFAULT_FORMAT = "wav"


def output_format(key: str) -> Format:
    k = str(key or "").strip().lower().lstrip(".")
    for f in FORMATS:
        if f.key == k:
            return f
    raise KeyError(key)


# ── User EQ ─────────────────────────────────────────────────────────────

EQ_LIMITS = {"max_bands": 12, "gain_limit_db": 18.0,
             "freq_min_hz": 20.0, "freq_max_hz": 20000.0, "q_min": 0.1, "q_max": 18.0}
EQ_TYPES = ("bell", "low_shelf", "high_shelf", "highpass", "lowpass", "notch")
