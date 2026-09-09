"""
host_census.py — Which finished masters can serve as clean hosts for the
hash work (harness rows, training pairs)?

Walks the catalogue for the service's MediumNeutral masters (one per song,
deduplicated by song stem), scans each with the detector and records the
flicker excess on its hot window. A host is usable when that reads below
budget.EXCESS_FLOOR_DB — with the caveat, measured under checklist item 15,
that the flicker feature is blind on drum-driven material, so "reads clean"
is a necessary check, not a guarantee.

Writes docs/host-census.json: path, song, flicker excess, duration.

Usage: python scripts/host_census.py
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from shimmer.audio_io import load_audio          # noqa: E402
from shimmer.budget import EXCESS_FLOOR_DB        # noqa: E402
from shimmer.detect import evidence_scan          # noqa: E402
from tilt_gap import collect                      # noqa: E402


def main(argv):
    refs, _ = collect()
    rows = []
    for key, (path, song) in sorted(refs.items()):
        try:
            x, sr = load_audio(path)
        except Exception as e:  # noqa: BLE001
            print(f"skip {song}: {e}")
            continue
        ev = evidence_scan(x, sr).evidence
        rows.append({"song": song, "path": path, "seconds": round(x.shape[0] / sr, 1),
                     "sr": sr, "flicker_excess_db": round(float(ev.flicker_excess_db), 2),
                     "usable": bool(ev.flicker_excess_db < EXCESS_FLOOR_DB)})
        print(f"{song[:44]:44s} {ev.flicker_excess_db:+6.2f} {'usable' if rows[-1]['usable'] else ''}", flush=True)
    out = os.path.join(ROOT, "docs", "host-census.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"floor_db": EXCESS_FLOOR_DB, "rows": rows}, f, indent=1)
    n_ok = sum(r["usable"] for r in rows)
    print(f"\n{len(rows)} MediumNeutral masters, {n_ok} read below {EXCESS_FLOOR_DB} dB; wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
