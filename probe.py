"""
probe.py — Artifact analysis and visualization.

Isolates shimmer artifacts from a time region and generates
spectrograms and residual heatmaps for inspection. Useful for:
  - Diagnosing which frequencies are problematic
  - Validating processing results
  - Choosing the right preset / parameters
"""

from __future__ import annotations

import os
from typing import Optional

import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import median_filter

from dsp import band_from_center, lin_to_db
from audio_io import load_audio


def analyze_region(
    input_path: str,
    output_dir: str,
    t0: float = 0.0,
    duration: float = 4.0,
    start_hz: float = 5100.0,
    end_hz: float = 7200.0,
    center_hz: Optional[float] = None,
    width_cents: Optional[float] = None,
    n_fft: int = 4096,
    hop: int = 1024,
    freq_med_bins: int = 9,
    thr_db: float = 8.0,
    artifact_filename: str = "artifact.wav",
) -> dict:
    """
    Analyze a time region for shimmer artifacts.

    Produces:
      - artifact.wav: isolated artifact audio (only flagged bins)
      - roi_band_spectrogram.png: magnitude spectrogram of the target band
      - roi_residual_map.png: residual-above-median heatmap

    Args:
        input_path: Path to input audio file.
        output_dir: Directory to write outputs into.
        t0: Start time in seconds.
        duration: Duration in seconds.
        start_hz / end_hz: Frequency band to analyze.
        center_hz / width_cents: Alternative band spec (overrides start/end).
        n_fft: FFT size (larger = finer frequency resolution).
        hop: Hop size in samples.
        freq_med_bins: Median filter width for local baseline.
        thr_db: Threshold above baseline to flag as artifact.
        artifact_filename: Name for the artifact WAV file.

    Returns:
        Dict with analysis metadata.
    """
    os.makedirs(output_dir, exist_ok=True)

    if center_hz is not None and width_cents is not None:
        start_hz, end_hz = band_from_center(center_hz, width_cents)

    x, sr = sf.read(input_path, always_2d=True)
    x = x.astype(np.float32, copy=False)

    s0 = max(0, min(int(t0 * sr), x.shape[0]))
    s1 = max(0, min(int((t0 + duration) * sr), x.shape[0]))
    seg = x[s0:s1, :]

    if seg.shape[0] < n_fft:
        raise ValueError(f"Region too short ({seg.shape[0]} samples) for n_fft={n_fft}")

    noverlap = n_fft - hop

    # STFT per channel
    stfts = []
    for ch in range(seg.shape[1]):
        f, t, Z = signal.stft(
            seg[:, ch], fs=sr, window="hann",
            nperseg=n_fft, noverlap=noverlap, nfft=n_fft,
            boundary=None, padded=False,
        )
        stfts.append(Z)
    Zs = np.stack(stfts, axis=-1)  # (freq, time, ch)

    band = np.where((f >= start_hz) & (f <= end_hz))[0]
    if band.size < 8:
        raise ValueError("Band too narrow for this FFT size; increase n_fft or widen band.")

    mag = np.mean(np.abs(Zs[band, :, :]), axis=2)  # (band_f, time)
    L = np.log(np.maximum(mag, 1e-12))

    k = int(max(3, freq_med_bins))
    if k % 2 == 0:
        k += 1

    L_med = median_filter(L, size=(k, 1), mode="nearest")
    residual_db = (L - L_med) * (20.0 / np.log(10.0))

    mask = residual_db > float(thr_db)

    # Artifact-only STFT
    Z_art = np.zeros_like(Zs)
    for ch in range(Zs.shape[2]):
        Z_art[band, :, ch] = Zs[band, :, ch] * mask

    # ISTFT per channel
    channels = []
    for ch in range(Z_art.shape[2]):
        _, y = signal.istft(
            Z_art[:, :, ch], fs=sr, window="hann",
            nperseg=n_fft, noverlap=noverlap, nfft=n_fft,
            input_onesided=True, boundary=False,
        )
        channels.append(y.astype(np.float32))
    y_art = np.stack(channels, axis=1)

    n = seg.shape[0]
    if y_art.shape[0] > n:
        y_art = y_art[:n, :]
    elif y_art.shape[0] < n:
        y_art = np.pad(y_art, ((0, n - y_art.shape[0]), (0, 0)))

    out_wav = os.path.join(output_dir, artifact_filename)
    sf.write(out_wav, y_art, sr)

    # Metrics
    flagged_frac = float(np.mean(mask))
    peak_residual = float(np.max(residual_db))
    mean_residual = float(np.mean(residual_db[mask])) if np.any(mask) else 0.0

    # --- Plots ---
    _plot_analysis(
        output_dir, mag, residual_db, t, f, band, t0, thr_db)

    return {
        "artifact_wav": out_wav,
        "region_start_s": t0,
        "region_duration_s": duration,
        "band_hz": (float(start_hz), float(end_hz)),
        "flagged_fraction": flagged_frac,
        "peak_residual_db": peak_residual,
        "mean_residual_db": mean_residual,
        "sr": sr,
    }


def _plot_analysis(output_dir, mag, residual_db, t, f, band, t0, thr_db):
    """Generate spectrogram and residual heatmap PNGs."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return

    mag_db = lin_to_db(mag)
    extent = [t[0] + t0, t[-1] + t0, f[band[0]], f[band[-1]]]

    fig, ax = plt.subplots(figsize=(12, 4))
    im = ax.imshow(mag_db, origin="lower", aspect="auto", extent=extent)
    ax.set_title("ROI band magnitude (dB)")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Frequency (Hz)")
    fig.colorbar(im, ax=ax, label="dB")
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "roi_band_spectrogram.png"), dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 4))
    im = ax.imshow(residual_db, origin="lower", aspect="auto", extent=extent)
    ax.set_title(f"Residual above local median (dB), thr={thr_db:.1f} dB")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Frequency (Hz)")
    fig.colorbar(im, ax=ax, label="dB")
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "roi_residual_map.png"), dpi=160)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Preset suggestion (auto-detect)
# ---------------------------------------------------------------------------

_SUGGEST_CANDIDATES = [
    # (preset_name, (band_lo_hz, band_hi_hz))
    ("suno_v3",     (5100.0, 7200.0)),
    ("suno_v3.5",   (4800.0, 7500.0)),
    ("suno_v4",     (4500.0, 8000.0)),
    ("suno_v4.5",   (3500.0, 4500.0)),
    ("suno_v5",     (5000.0, 9000.0)),
    ("suno_v5.5",   (3500.0, 14000.0)),
    ("suno_v5_pro", (6000.0, 12000.0)),
    ("suno_cymbal", (8000.0, 14000.0)),
]


def _shimmer_density(mag_log: np.ndarray, freqs: np.ndarray,
                     lo_hz: float, hi_hz: float,
                     freq_med_bins: int = 9,
                     thr_db: float = 6.0) -> float:
    """Fraction of (time, freq) bins flagged as above-median outliers
    within [lo_hz, hi_hz].  Proxy for 'how much shimmer lives here'."""
    band = np.where((freqs >= lo_hz) & (freqs <= hi_hz))[0]
    if band.size < 8:
        return 0.0
    L = mag_log[band, :]
    k = freq_med_bins if freq_med_bins % 2 else freq_med_bins + 1
    L_med = median_filter(L, size=(k, 1), mode="nearest")
    residual_db = (L - L_med) * (20.0 / np.log(10.0))
    return float(np.mean(residual_db > thr_db))


def _checkerboard_score(mag_log: np.ndarray, freqs: np.ndarray,
                        lo_hz: float = 3000.0, hi_hz: float = 14000.0,
                        min_spacing_hz: float = 80.0,
                        max_spacing_hz: float = 600.0) -> float:
    """Average autocorrelation peak of (mag - local median) along the
    frequency axis, within the deconv-grid spacing range.  Higher = more
    checkerboard-like."""
    band = np.where((freqs >= lo_hz) & (freqs <= hi_hz))[0]
    if band.size < 32:
        return 0.0
    bin_hz = float(freqs[1] - freqs[0])
    min_lag = max(2, int(round(min_spacing_hz / bin_hz)))
    max_lag = max(min_lag + 1, int(round(max_spacing_hz / bin_hz)))
    L = mag_log[band, :]
    L_med = median_filter(L, size=(7, 1), mode="nearest")
    R = L - L_med
    R = np.maximum(R, 0.0)
    if R.size == 0:
        return 0.0
    n = R.shape[0]
    R = R - R.mean(axis=0, keepdims=True)
    norm = np.sum(R * R, axis=0) + 1e-12
    best_per_frame = np.zeros(R.shape[1], dtype=np.float32)
    max_lag = min(max_lag, n - 1)
    for lag in range(min_lag, max_lag + 1):
        s = np.sum(R[:n - lag, :] * R[lag:, :], axis=0) / norm
        best_per_frame = np.maximum(best_per_frame, s)
    return float(np.mean(best_per_frame))


def suggest_preset(input_path: str,
                   max_duration_s: float = 30.0,
                   n_fft: int = 4096,
                   hop: int = 1024) -> dict:
    """Analyse the first `max_duration_s` seconds of `input_path` and suggest
    the best-matching preset.

    Returns a dict:
        {
            "preset": "suno_v5.5",
            "scores": { "suno_v3": 0.02, ... },
            "checkerboard_score": 0.12,
            "metrics": { ... },
        }
    """
    x, sr = load_audio(input_path)
    if x.ndim > 1:
        x_mono = np.mean(x, axis=1)
    else:
        x_mono = x
    max_samples = int(max_duration_s * sr)
    if x_mono.shape[0] > max_samples:
        x_mono = x_mono[:max_samples]
    if x_mono.shape[0] < n_fft:
        raise ValueError(
            f"Clip too short ({x_mono.shape[0]} samples) for n_fft={n_fft}")

    noverlap = n_fft - hop
    f, _, Z = signal.stft(
        x_mono, fs=sr, window="hann",
        nperseg=n_fft, noverlap=noverlap, nfft=n_fft,
        boundary=None, padded=False,
    )
    mag = np.abs(Z) + 1e-12
    mag_log = np.log(mag)

    scores = {
        name: _shimmer_density(mag_log, f, lo, hi)
        for name, (lo, hi) in _SUGGEST_CANDIDATES
    }
    cb_score = _checkerboard_score(mag_log, f)

    # Tie-break: if checkerboard is strong, lean toward v5.5 or v5.
    best_name = max(scores, key=lambda n: scores[n])
    if cb_score > 0.10:
        # Strong grid pattern → prefer v5.5 (de-checkerboard enabled) or v5.
        if scores.get("suno_v5.5", 0.0) >= 0.5 * scores[best_name]:
            best_name = "suno_v5.5"
        elif scores.get("suno_v5", 0.0) >= 0.5 * scores[best_name]:
            best_name = "suno_v5"

    # Fallback: if every density is tiny, recommend 'generic'.
    if scores[best_name] < 0.005:
        best_name = "generic"

    return {
        "preset": best_name,
        "scores": scores,
        "checkerboard_score": cb_score,
        "metrics": {
            "sample_rate": sr,
            "analyzed_seconds": float(x_mono.shape[0] / sr),
        },
    }


# ---------------------------------------------------------------------------
# CLI entry point for standalone use
# ---------------------------------------------------------------------------

def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="Analyze a time region for shimmer artifacts.")
    ap.add_argument("input", help="Input audio file")
    ap.add_argument("--outdir", default="probe_output",
                    help="Output directory for analysis results")
    ap.add_argument("--t0", type=float, default=0.0,
                    help="Region start time (seconds)")
    ap.add_argument("--dur", type=float, default=4.0,
                    help="Region duration (seconds)")
    ap.add_argument("--start-hz", type=float, default=5100.0)
    ap.add_argument("--end-hz", type=float, default=7200.0)
    ap.add_argument("--center-hz", type=float, default=None)
    ap.add_argument("--width-cents", type=float, default=None)
    ap.add_argument("--n-fft", type=int, default=4096)
    ap.add_argument("--hop", type=int, default=1024)
    ap.add_argument("--freq-med-bins", type=int, default=9)
    ap.add_argument("--thr-db", type=float, default=8.0)
    args = ap.parse_args()

    result = analyze_region(
        input_path=args.input,
        output_dir=args.outdir,
        t0=args.t0,
        duration=args.dur,
        start_hz=args.start_hz,
        end_hz=args.end_hz,
        center_hz=args.center_hz,
        width_cents=args.width_cents,
        n_fft=args.n_fft,
        hop=args.hop,
        freq_med_bins=args.freq_med_bins,
        thr_db=args.thr_db,
    )

    print(f"Artifact WAV:      {result['artifact_wav']}")
    print(f"Band:              {result['band_hz'][0]:.0f} – {result['band_hz'][1]:.0f} Hz")
    print(f"Flagged bins:      {result['flagged_fraction']:.1%}")
    print(f"Peak residual:     {result['peak_residual_db']:.1f} dB")
    print(f"Mean residual:     {result['mean_residual_db']:.1f} dB")


if __name__ == "__main__":
    main()
