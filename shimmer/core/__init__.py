"""shimmer.core — the engine.

Everything that changes or measures sound lives here, built once:

    audio/     reading and writing files, filters, meters, silence trim
    analyze/   findings: what the song has (measures, never alters)
    repair/    one module per card that fixes something
    master/    loudness, tone and the limiter
    catalog    the rules the screens show (cards, loudness choices, formats)
    settings   one settings object, and migrate() for old saved settings
    render     render(source, settings, window=None): the one sound path
    export     the one way a file is written
    tags       reading and writing tags

The web layer (shimmer/api) talks to the engine only through the names
below. Nothing here imports the web layer or the old engine
(docs/ARCHITECTURE.md §18.3, tests/api/test_api_contract.py).
"""
from . import catalog, tags
from .analyze.edges import apply_trim, detect_edge_artifacts
from .analyze.findings import Finding, findings
from .analyze.report import plr_db, spectra_report, stereo_correlation
from .analyze.tones import estimate_cutoff_hz, scan_fixed_lines
from .analyze.track import activity_timeline, analyze_track, loudness_range
from .audio import meters
from .audio.io import AudioIOError, file_digest, wav_bytes
from .audio.io import load as load_audio
from .audio.trim import trim_silence
from .export import export
from .master.release import add_check, release_check, tags_check
from .progress import Cancelled, Progress
from .render import Rendered, Source, render
from .repair.notch import Notch, NotchPlan, plan_from_lines
from .settings import EqBand, Settings, migrate

__all__ = ["catalog", "tags", "export", "render", "Rendered", "Source",
           "Settings", "EqBand", "migrate", "Progress", "Cancelled",
           "analyze_track", "detect_edge_artifacts", "apply_trim", "findings", "Finding",
           "scan_fixed_lines", "estimate_cutoff_hz", "plan_from_lines", "Notch", "NotchPlan",
           "spectra_report", "stereo_correlation", "plr_db",
           "release_check", "add_check", "tags_check",
           "meters", "loudness_range", "trim_silence", "activity_timeline",
           "load_audio", "wav_bytes", "file_digest", "AudioIOError"]
