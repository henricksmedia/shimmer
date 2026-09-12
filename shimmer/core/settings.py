"""One settings object for every tab, and migrate() for old saved settings.

The old app carried a preset name, a strength, fifteen sliders and a
mastering block, each read differently by six code paths. Now one Settings
value says everything render() needs, and old saved settings map onto it
(docs/ARCHITECTURE.md §19.3).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from . import catalog


@dataclass(frozen=True)
class EqBand:
    """One user EQ band, in the screens' terms."""
    type: str = "bell"          # catalog.EQ_TYPES
    freq_hz: float = 1000.0
    gain_db: float = 0.0
    q: float = 1.0
    enabled: bool = True


def _clamp(v: float, lo: float, hi: float) -> float:
    return float(min(hi, max(lo, v)))


def _band(raw: Any) -> Optional[EqBand]:
    if isinstance(raw, EqBand):
        raw = dataclasses.asdict(raw)
    if not isinstance(raw, Mapping):
        return None
    lim = catalog.EQ_LIMITS
    kind = str(raw.get("type", "bell")).lower()
    if kind not in catalog.EQ_TYPES:
        return None
    try:
        return EqBand(
            type=kind,
            freq_hz=_clamp(float(raw.get("freq_hz", 1000.0)), lim["freq_min_hz"], lim["freq_max_hz"]),
            gain_db=_clamp(float(raw.get("gain_db", 0.0)), -lim["gain_limit_db"], lim["gain_limit_db"]),
            q=_clamp(float(raw.get("q", 1.0)), lim["q_min"], lim["q_max"]),
            enabled=bool(raw.get("enabled", True)),
        )
    except (TypeError, ValueError):
        return None


@dataclass
class Settings:
    """Everything render() needs.

    fixes            {card key: amount 0-1}: the cards that are on
    auto             also turn on the fixes Analyze finds (Fixed tones today)
    mastering        loudness, tone and limiter on
    loudness_target  a catalog.LOUDNESS_TARGETS key
    format           a catalog.FORMATS key
    eq_enabled       the user EQ on
    eq_bands         the user EQ's bands, in order
    trim_silence     cut silence from the start and end
    preserve_volume  with mastering off, put the result back at the song's
                     own level
    """
    fixes: Dict[str, float] = field(default_factory=dict)
    auto: bool = True
    mastering: bool = True
    loudness_target: str = catalog.DEFAULT_LOUDNESS
    format: str = catalog.DEFAULT_FORMAT
    eq_enabled: bool = False
    eq_bands: Tuple[EqBand, ...] = ()
    trim_silence: bool = False
    preserve_volume: bool = True

    def __post_init__(self) -> None:
        # Unknown cards are dropped and amounts kept to 0-1, so a bad value
        # from a screen or an old file can never reach the engine.
        self.fixes = {k: _clamp(float(v), 0.0, 1.0)
                      for k, v in dict(self.fixes or {}).items() if k in catalog.CARD_KEYS}
        if self.loudness_target not in {t.key for t in catalog.LOUDNESS_TARGETS}:
            self.loudness_target = catalog.DEFAULT_LOUDNESS
        try:
            self.format = catalog.output_format(self.format).key
        except KeyError:
            self.format = catalog.DEFAULT_FORMAT
        bands = [b for b in (_band(r) for r in (self.eq_bands or ())) if b is not None]
        self.eq_bands = tuple(bands[:int(catalog.EQ_LIMITS["max_bands"])])
        self.auto, self.mastering = bool(self.auto), bool(self.mastering)
        self.eq_enabled, self.trim_silence = bool(self.eq_enabled), bool(self.trim_silence)
        self.preserve_volume = bool(self.preserve_volume)

    @classmethod
    def bypass(cls) -> "Settings":
        """Nothing on: render() returns the input unchanged."""
        return cls(fixes={}, auto=False, mastering=False, eq_enabled=False,
                   eq_bands=(), trim_silence=False)

    def replace(self, **changes: Any) -> "Settings":
        return dataclasses.replace(self, **changes)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fixes": dict(self.fixes),
            "auto": self.auto,
            "mastering": self.mastering,
            "loudness_target": self.loudness_target,
            "format": self.format,
            "eq": {"enabled": self.eq_enabled,
                   "bands": [dataclasses.asdict(b) for b in self.eq_bands]},
            "trim_silence": self.trim_silence,
            "preserve_volume": self.preserve_volume,
        }

    @classmethod
    def from_dict(cls, d: Optional[Mapping[str, Any]]) -> "Settings":
        d = d or {}
        eq = d.get("eq") if isinstance(d.get("eq"), Mapping) else {}
        default = cls()
        return cls(
            fixes=d.get("fixes") if isinstance(d.get("fixes"), Mapping) else {},
            auto=d.get("auto", default.auto),
            mastering=d.get("mastering", default.mastering),
            loudness_target=d.get("loudness_target", default.loudness_target),
            format=d.get("format", default.format),
            eq_enabled=eq.get("enabled", False),
            eq_bands=tuple(eq.get("bands") or ()),
            trim_silence=d.get("trim_silence", False),
            preserve_volume=d.get("preserve_volume", True),
        )


# ── Old saved settings ──────────────────────────────────────────────────

# Every 1.x preset and version-named alias, and the card it becomes
# (ARCHITECTURE §19.3). Written out here, not read from shimmer/presets.py,
# so the old module can be deleted.
LEGACY_PRESETS: Dict[str, Optional[str]] = {
    "generic": None,
    "cymbal_sheen": "tones", "laser_whistle": "tones", "air_brittle": "tones",
    "checkerboard_grid": "tones",
    "suno_hash": "shimmer", "broadband_fizz": "shimmer", "presence_haze": "shimmer",
    "echo_sheen": "shimmer", "cymbal_chatter": "shimmer", "phantom_cymbal": "shimmer",
    "vocal_glaze_plus": "shimmer", "deep_scrub": "shimmer",
    "sibilance_rattle": "sibilance", "vocal_glaze": "sibilance",
    "harsh_veil": "harshness",
    "muddy_boxy": "mud",
    "dark_mix_rescue": "air",
    "reverb_flutter": "phasiness",
}
LEGACY_ALIASES: Dict[str, str] = {
    "suno_v3": "laser_whistle", "suno_v3.5": "laser_whistle", "suno_v4": "cymbal_chatter",
    "suno_v4.5": "broadband_fizz", "suno_v5": "checkerboard_grid", "suno_v5_pro": "air_brittle",
    "suno_v5.5": "reverb_flutter", "suno_cymbal": "cymbal_sheen",
}


def card_for_preset(name: Any) -> Optional[str]:
    """The card an old preset becomes, or None (Generic, or unknown)."""
    key = str(name or "").strip().lower()
    key = LEGACY_ALIASES.get(key, key)
    return LEGACY_PRESETS.get(key)


def migrate(old: Optional[Mapping[str, Any]]) -> Settings:
    """Settings from anything saved by 1.x (settings.json, a Remix project's
    cleanup block, a route's old fields), or by this version.

    - The old preset turns on its card at that card's default amount. Old
      preset strength does not carry over: those presets applied their
      filters at twice their setting, so the old numbers mean nothing now.
    - The loudness choice, format, EQ, silence trim and preserve volume
      carry over as saved.
    """
    old = old if isinstance(old, Mapping) else {}
    if "fixes" in old or "loudness_target" in old:
        return Settings.from_dict(old)
    cleaning = old.get("cleaning") if isinstance(old.get("cleaning"), Mapping) else {}
    preset = old.get("preset", cleaning.get("preset"))
    card = card_for_preset(preset)
    master = old.get("mastering") if isinstance(old.get("mastering"), Mapping) else {}
    eq = old.get("eq") if isinstance(old.get("eq"), Mapping) else {}
    return Settings(
        fixes={card: catalog.card(card).default_amount} if card else {},
        auto=True,
        mastering=master.get("enabled", True),
        loudness_target=master.get("target", catalog.DEFAULT_LOUDNESS),
        format=old.get("output_format", catalog.DEFAULT_FORMAT),
        eq_enabled=eq.get("enabled", False),
        eq_bands=tuple(eq.get("bands") or ()),
        trim_silence=old.get("trim_silence", False),
        preserve_volume=old.get("preserve_volume", True),
    )
