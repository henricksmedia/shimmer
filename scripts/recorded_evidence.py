"""Rebuild a detect.Evidence from the evidence dict the harnesses record,
so priors can be recomputed from cached measurements. Fields the harness
does not record are filled with neutral values; the priors that depend on
them (upper_db for broadband_fizz, click_rate for sibilance_rattle) are
therefore lower bounds here."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shimmer.detect import Evidence, Tone, priors_from_evidence  # noqa: E402


def evidence_from_recorded(ev: dict) -> Evidence:
    def tone(k):
        v = ev.get(k)
        return Tone(v["hz"], v["excess_db"], v["duty"]) if isinstance(v, dict) else Tone(0.0, 0.0, 0.0)
    t = Tone(0.0, 0.0, 0.0)
    return Evidence(
        tones=[], tone_4_8=t, tone_8_12=tone("tone_8_12"),
        tone_9_15=tone("tone_9_15"), tone_12_20=tone("tone_12_20"),
        top_tilt_db=ev.get("top_tilt_db", 0.0), presence_db=ev.get("presence_db", 0.0),
        upper_db=ev.get("upper_db", 0.0), umid_db=ev.get("umid_db", 0.0),
        mud_db=0.0, dull_db=0.0, flicker_hi_db=0.0, flicker_body_db=0.0,
        flicker_excess_db=ev.get("flicker_excess_db", 0.0),
        comb=ev.get("comb", 0.0), sib_burst=ev.get("sib_burst", 0.0),
        period_hi=0.0, period_body=0.0, period_excess=ev.get("period_excess", 0.0),
        tail_contrast=ev.get("tail_contrast", 0.0), ring_4_10=ev.get("ring_4_10", 0.0),
        echo_corr=ev.get("echo_corr", 0.0), flat_3_8=ev.get("flat_3_8", 0.0),
        flat_4_12=ev.get("flat_4_12", 0.0), flat_8_18=ev.get("flat_8_18", 0.0),
        cutoff_hz=0.0, click_rate=ev.get("click_rate", 0.0))


def priors_from_recorded(ev: dict) -> dict:
    return priors_from_evidence(evidence_from_recorded(ev))
