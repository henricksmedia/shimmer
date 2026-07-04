"""
probe.py — Artifact analysis and visualization.

Isolates shimmer artifacts from a time region and generates
spectrograms and residual heatmaps for inspection. Useful for:
  - Diagnosing which frequencies are problematic
  - Validating processing results
  - Choosing the right preset / parameters
"""

from __future__ import annotations

import _winfix  # noqa: F401  # must precede scipy import on Windows

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
#
# The scorer evaluates each artifact-shape preset directly using a feature
# vector that probes for that artifact's signature:
#
#   density        : fraction of bins above local-median in a band
#   tonality       : spectral flatness (high = noise-like, low = peaky)
#   persistent     : fraction of bins flagged that hold for a long run
#   periodicity    : time-axis autocorrelation of band energy (rattle)
#   freq_comb      : freq-axis autocorr peak (deconv-grid signature)
#   top_conc       : energy ratio of the >12 kHz "air" band vs 4-12 kHz
#   sib_burst      : 6-10 kHz bursts that lack matching mid-band onsets
#   tail_flutter   : shimmer density measured only in decay frames
#   vocal_glaze    : shimmer glaze on vocal harmonics (2-8 kHz vs fundamentals)
#   echo_sheen     : signal-correlated shimmer shadowing musical content
#   presence_wash  : broadband noise wash in 3-8 kHz correlated w/ content
#   metallic_wash  : ringy wash in 4-10 kHz (broadband + embedded peaks)
#   harsh_grit     : persistent gritty texture across 4-12 kHz
# ---------------------------------------------------------------------------


def _band_density(mag_log: np.ndarray, freqs: np.ndarray,
                  lo_hz: float, hi_hz: float,
                  freq_med_bins: int = 9,
                  thr_db: float = 6.0) -> float:
    """Fraction of (time, freq) bins above local-median by `thr_db` within
    [lo_hz, hi_hz]. Proxy for 'how much shimmer lives here'."""
    band = np.where((freqs >= lo_hz) & (freqs <= hi_hz))[0]
    if band.size < 8:
        return 0.0
    L = mag_log[band, :]
    k = freq_med_bins if freq_med_bins % 2 else freq_med_bins + 1
    L_med = median_filter(L, size=(k, 1), mode="nearest")
    residual_db = (L - L_med) * (20.0 / np.log(10.0))
    return float(np.mean(residual_db > thr_db))


# Back-compat alias: external callers (CLI, tests) may still reference this.
_shimmer_density = _band_density


def _tonality_band(mag_log: np.ndarray, freqs: np.ndarray,
                   lo_hz: float, hi_hz: float) -> float:
    """Mean spectral flatness across [lo_hz, hi_hz]. Returns 0..1.
    High = noise-like (tonality LOW), low = peaky (tonality HIGH).
    Use `1 - tonality_band(...)` if you want a 'tonalness' score."""
    band = np.where((freqs >= lo_hz) & (freqs <= hi_hz))[0]
    if band.size < 8:
        return 0.0
    L = mag_log[band, :]
    geo_mean = np.exp(np.mean(L, axis=0))            # geomean of magnitude
    arith_mean = np.mean(np.exp(L), axis=0) + 1e-12
    flat = geo_mean / arith_mean                     # 0..1
    return float(np.clip(np.mean(flat), 0.0, 1.0))


def _persistent_tone_score(mag_log: np.ndarray, freqs: np.ndarray,
                           lo_hz: float, hi_hz: float,
                           freq_med_bins: int = 15,
                           thr_db: float = 4.0,
                           persist_frames: int = 20) -> float:
    """Score for narrow peaks that stay above local median for many
    consecutive frames. High when a hi-hat-like tone never decays."""
    band = np.where((freqs >= lo_hz) & (freqs <= hi_hz))[0]
    if band.size < 8:
        return 0.0
    L = mag_log[band, :]
    k = freq_med_bins if freq_med_bins % 2 else freq_med_bins + 1
    L_med = median_filter(L, size=(k, 1), mode="nearest")
    R = (L - L_med) * (20.0 / np.log(10.0))
    mask = (R > thr_db).astype(np.float32)
    if mask.shape[1] < persist_frames:
        return float(mask.mean())
    # Smooth along time so only long runs survive.
    pf = persist_frames if persist_frames % 2 else persist_frames + 1
    smoothed = median_filter(mask, size=(1, pf), mode="nearest")
    return float(smoothed.mean())


def _time_periodicity_score(mag_log: np.ndarray, freqs: np.ndarray,
                            lo_hz: float, hi_hz: float,
                            sr: int, hop: int,
                            lag_ms_range=(30.0, 200.0)) -> float:
    """Time-axis autocorrelation of band energy at lags in `lag_ms_range`.
    High = repetitive chatter (the ta-ta-ta rattle)."""
    band = np.where((freqs >= lo_hz) & (freqs <= hi_hz))[0]
    if band.size < 8:
        return 0.0
    energy = np.exp(mag_log[band, :]).sum(axis=0).astype(np.float64)
    energy = energy - energy.mean()
    norm = float(np.sum(energy * energy)) + 1e-12
    frame_dt_s = hop / float(sr)
    min_lag = max(1, int(round((lag_ms_range[0] / 1000.0) / frame_dt_s)))
    max_lag = max(min_lag + 1, int(round((lag_ms_range[1] / 1000.0) / frame_dt_s)))
    n = energy.shape[0]
    max_lag = min(max_lag, n - 1)
    if max_lag <= min_lag:
        return 0.0
    best = 0.0
    for lag in range(min_lag, max_lag + 1):
        s = float(np.sum(energy[:n - lag] * energy[lag:]) / norm)
        if s > best:
            best = s
    return float(np.clip(best, 0.0, 1.0))


def _freq_comb_score(mag_log: np.ndarray, freqs: np.ndarray,
                     lo_hz: float = 3000.0, hi_hz: float = 14000.0,
                     min_spacing_hz: float = 80.0,
                     max_spacing_hz: float = 600.0) -> float:
    """Average autocorrelation peak along the frequency axis, in the
    deconv-grid spacing range. High = checkerboard-like comb pattern."""
    band = np.where((freqs >= lo_hz) & (freqs <= hi_hz))[0]
    if band.size < 32:
        return 0.0
    bin_hz = float(freqs[1] - freqs[0])
    min_lag = max(2, int(round(min_spacing_hz / bin_hz)))
    max_lag = max(min_lag + 1, int(round(max_spacing_hz / bin_hz)))
    L = mag_log[band, :]
    L_med = median_filter(L, size=(7, 1), mode="nearest")
    R = np.maximum(L - L_med, 0.0)
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
    return float(np.clip(np.mean(best_per_frame), 0.0, 1.0))


# Back-compat alias used elsewhere in the codebase.
_checkerboard_score = _freq_comb_score


def _top_band_concentration(mag_log: np.ndarray, freqs: np.ndarray) -> float:
    """Energy ratio of >12 kHz vs 4-12 kHz. High when the artifact lives
    almost entirely in the air band (and the rest of the mix is clean)."""
    top = np.where((freqs >= 12000.0) & (freqs <= 18000.0))[0]
    mid = np.where((freqs >= 4000.0) & (freqs <= 12000.0))[0]
    if top.size < 4 or mid.size < 4:
        return 0.0
    e_top = float(np.mean(np.exp(mag_log[top, :])))
    e_mid = float(np.mean(np.exp(mag_log[mid, :])))
    if e_mid <= 0.0:
        return 0.0
    return float(e_top / e_mid)


def _sibilance_burst_score(mag_log: np.ndarray, freqs: np.ndarray) -> float:
    """Fraction of frames where 6-10 kHz energy spikes well above its
    median, conditioned on the same frame having mid-band activity (so
    pure cymbals don't trigger). Targets the harsh 'sss/tss' signature."""
    sib = np.where((freqs >= 6000.0) & (freqs <= 10000.0))[0]
    mid = np.where((freqs >= 1000.0) & (freqs <= 4000.0))[0]
    if sib.size < 4 or mid.size < 4:
        return 0.0
    e_sib = np.exp(mag_log[sib, :]).sum(axis=0)
    e_mid = np.exp(mag_log[mid, :]).sum(axis=0)
    ratio = e_sib / (e_mid + 1e-12)
    if ratio.size == 0:
        return 0.0
    med_ratio = float(np.median(ratio))
    if med_ratio <= 0.0:
        return 0.0
    # Frames with anomalously bright sibilance AND non-trivial mid energy
    # (so we are looking at a vocal-like frame, not silence).
    mid_active = e_mid > (0.3 * float(np.median(e_mid)) + 1e-12)
    bursts = (ratio > 1.8 * med_ratio) & mid_active
    return float(np.mean(bursts))


def _tail_flutter_score(mag_log: np.ndarray, freqs: np.ndarray) -> float:
    """Shimmer density restricted to decay frames (frames where total
    broadband energy is decreasing). Targets the 'reverb tail flutter'
    signature: artifacts that show up while the music is dying away."""
    band = np.where((freqs >= 8000.0) & (freqs <= 16000.0))[0]
    if band.size < 8:
        return 0.0
    full_energy = np.exp(mag_log).sum(axis=0)
    if full_energy.size < 4:
        return 0.0
    flux = np.diff(full_energy, prepend=full_energy[0])
    tail_mask = flux <= 0.0
    if not np.any(tail_mask):
        return 0.0
    L_tail = mag_log[band, :][:, tail_mask]
    if L_tail.shape[1] < 8:
        return 0.0
    L_med = median_filter(L_tail, size=(9, 1), mode="nearest")
    R = (L_tail - L_med) * (20.0 / np.log(10.0))
    return float(np.clip(np.mean(R > 6.0), 0.0, 1.0))


def _vocal_glaze_score(mag_log: np.ndarray, freqs: np.ndarray) -> float:
    """Shimmer glaze on vocal harmonics: excess 2-8 kHz brightness
    relative to the vocal fundamental (300-1500 Hz), only on frames
    where vocal-like content is present.

    Vocal frames are identified by: mid-band energy (300-1500 Hz)
    above its median AND relatively low full-band energy dispersion
    (vocals are narrower than drums/full-band events). On those
    frames, the ratio of 2-8 kHz to 300-1500 Hz energy indicates
    how "glazed" the overtones are.
    """
    overtone = np.where((freqs >= 2000.0) & (freqs <= 8000.0))[0]
    fundamental = np.where((freqs >= 300.0) & (freqs <= 1500.0))[0]
    if overtone.size < 8 or fundamental.size < 4:
        return 0.0

    e_ot = np.exp(mag_log[overtone, :]).mean(axis=0)
    e_fund = np.exp(mag_log[fundamental, :]).mean(axis=0) + 1e-12
    e_full = np.exp(mag_log).sum(axis=0)
    if e_full.size < 16:
        return 0.0

    # Vocal-likely frames: fundamental region is active (mid-energy
    # above half-median) AND the 2-8 kHz band has noisy character
    # (flatness > 0.2 — real vocal harmonics are peaky, shimmer is
    # flatter).
    fund_active = e_fund > (0.5 * float(np.median(e_fund)) + 1e-12)

    L_ot = mag_log[overtone, :]
    geo = np.exp(np.mean(L_ot, axis=0))
    arith = np.mean(np.exp(L_ot), axis=0) + 1e-12
    flatness = geo / arith

    vocal_frames = fund_active & (flatness > 0.20)
    if not np.any(vocal_frames):
        return 0.0

    ratio = e_ot / e_fund
    med_ratio = float(np.median(ratio[vocal_frames]))
    if med_ratio <= 0.0:
        return 0.0

    # Glazed frames: overtone ratio elevated above its own median
    # on vocal frames (the shimmer makes them brighter than they
    # should be) AND flatness is high (noise-like, not clean harmonics).
    glazed = (ratio > 1.25 * med_ratio) & vocal_frames & (flatness > 0.25)
    # 2.5x scale: ~40% of frames must be glazed to saturate at 1.0.
    # (Was 4x / 25%, which let most AI vocals hit 1.0 trivially.)
    return float(np.clip(np.mean(glazed) * 2.5, 0.0, 1.0))


def _echo_sheen_score(mag_log: np.ndarray, freqs: np.ndarray) -> float:
    """Signal-correlated shimmer in 3-10 kHz that shadows musical content.

    Measures per-frame correlation between the presence-band energy
    envelope (3-10 kHz) and the body-band energy envelope (100-3000 Hz).
    In clean audio these bands are somewhat correlated (vocals have
    harmonics in both). In "echo sheen" audio the correlation is
    unusually HIGH because the artifact is literally amplitude-modulated
    by the signal — every note produces a proportional shimmer shadow.

    Additionally checks that the presence band has elevated broadband
    flatness on active frames (the shimmer is noise-like, not tonal).
    """
    pres = np.where((freqs >= 3000.0) & (freqs <= 10000.0))[0]
    body = np.where((freqs >= 100.0) & (freqs <= 3000.0))[0]
    if pres.size < 8 or body.size < 8:
        return 0.0

    e_pres = np.exp(mag_log[pres, :]).mean(axis=0).astype(np.float64)
    e_body = np.exp(mag_log[body, :]).mean(axis=0).astype(np.float64)
    if e_pres.size < 16:
        return 0.0

    # Frame-level Pearson correlation between the two band envelopes.
    e_pres_c = e_pres - e_pres.mean()
    e_body_c = e_body - e_body.mean()
    denom = (
        float(np.sqrt(np.sum(e_pres_c ** 2)))
        * float(np.sqrt(np.sum(e_body_c ** 2)))
    )
    if denom < 1e-12:
        return 0.0
    corr = float(np.sum(e_pres_c * e_body_c)) / denom

    # Flatness on active frames: the shimmer is noise-like.
    e_full = np.exp(mag_log).sum(axis=0)
    active = e_full > (0.5 * float(np.median(e_full)) + 1e-12)
    if not np.any(active):
        return 0.0

    L_pres = mag_log[pres, :][:, active]
    geo = np.exp(np.mean(L_pres, axis=0))
    arith = np.mean(np.exp(L_pres), axis=0) + 1e-12
    mean_flat = float(np.mean(geo / arith))

    # High correlation (>0.7 typical for echo sheen) AND noisy character.
    # Natural music sits around 0.4-0.6 correlation; echo sheen pushes
    # past 0.75 because the artifact is literally proportional to the
    # signal.
    corr_score = float(np.clip((corr - 0.55) / 0.35, 0.0, 1.0))
    flat_score = float(np.clip((mean_flat - 0.20) / 0.30, 0.0, 1.0))
    return float(np.clip(0.6 * corr_score + 0.4 * flat_score, 0.0, 1.0))


def _presence_wash_score(mag_log: np.ndarray, freqs: np.ndarray) -> float:
    """Broadband noise-like wash in 3-8 kHz correlated with musical content.

    Compares per-frame 3-8 kHz energy against full-band energy. In
    clean audio the presence band tracks the full-band envelope (vocals,
    drums naturally have energy there). In washy audio the presence band
    has *excess* broadband energy on active frames that isn't there
    during silence.

    Score: fraction of active frames where the 3-8 kHz flatness is high
    (noise-like) AND the 3-8 kHz level is elevated relative to the
    0-3 kHz body. Active frames are those where full-band energy
    exceeds half its median (i.e. music is playing).
    """
    pres = np.where((freqs >= 3000.0) & (freqs <= 8000.0))[0]
    body = np.where((freqs >= 100.0) & (freqs <= 3000.0))[0]
    if pres.size < 8 or body.size < 8:
        return 0.0

    e_full = np.exp(mag_log).sum(axis=0)
    if e_full.size < 8:
        return 0.0
    active = e_full > (0.5 * float(np.median(e_full)) + 1e-12)
    if not np.any(active):
        return 0.0

    e_pres = np.exp(mag_log[pres, :]).mean(axis=0)
    e_body = np.exp(mag_log[body, :]).mean(axis=0) + 1e-12
    ratio = e_pres / e_body

    L_pres = mag_log[pres, :]
    geo = np.exp(np.mean(L_pres, axis=0))
    arith = np.mean(np.exp(L_pres), axis=0) + 1e-12
    flatness = geo / arith

    # Washy frames: high flatness (>0.3 = noisy) AND elevated ratio vs
    # the median ratio (so natural vocal presence doesn't trigger).
    med_ratio = float(np.median(ratio[active]))
    if med_ratio <= 0.0:
        return 0.0
    washy = (flatness > 0.30) & (ratio > 1.3 * med_ratio) & active
    return float(np.clip(np.mean(washy) * 3.0, 0.0, 1.0))


def _metallic_wash_score(mag_log: np.ndarray, freqs: np.ndarray) -> float:
    """Metallic / ringy wash in 4-10 kHz: broadband with embedded peaks.

    A clean cymbal or vocal has either smooth broadband energy OR
    narrow peaks, not both. A metallic wash has BOTH: high overall
    flatness (broadband energy) AND narrow peaks that sit above the
    broadband floor. Score blends flatness with peak density, gated to
    active-music frames.
    """
    band = np.where((freqs >= 4000.0) & (freqs <= 10000.0))[0]
    if band.size < 8:
        return 0.0

    e_full = np.exp(mag_log).sum(axis=0)
    if e_full.size < 8:
        return 0.0
    active = e_full > (0.5 * float(np.median(e_full)) + 1e-12)
    if not np.any(active):
        return 0.0

    L = mag_log[band, :]
    geo = np.exp(np.mean(L, axis=0))
    arith = np.mean(np.exp(L), axis=0) + 1e-12
    flatness = geo / arith

    k = 11
    L_med = median_filter(L, size=(k, 1), mode="nearest")
    residual_db = (L - L_med) * (20.0 / np.log(10.0))
    peak_density = (residual_db > 4.0).astype(np.float32).mean(axis=0)

    # Metallic = simultaneously broadband (flat > 0.25) AND peaky
    metallic = (flatness > 0.25) & (peak_density > 0.03) & active
    return float(np.clip(np.mean(metallic) * 3.0, 0.0, 1.0))


def _harsh_grit_score(mag_log: np.ndarray, freqs: np.ndarray) -> float:
    """Persistent gritty texture across the upper-mids (4-12 kHz).

    Measures broadband energy excess in 4-12 kHz relative to 1-4 kHz
    on active frames, weighted by flatness. Grit is broadband (high
    flatness) and persistent (present on most active frames), but
    unlike pure fizz it extends down into the upper-mids where it
    sounds harsh rather than airy.
    """
    upper = np.where((freqs >= 4000.0) & (freqs <= 12000.0))[0]
    mid = np.where((freqs >= 1000.0) & (freqs <= 4000.0))[0]
    if upper.size < 8 or mid.size < 8:
        return 0.0

    e_full = np.exp(mag_log).sum(axis=0)
    if e_full.size < 8:
        return 0.0
    active = e_full > (0.5 * float(np.median(e_full)) + 1e-12)
    if not np.any(active):
        return 0.0

    e_upper = np.exp(mag_log[upper, :]).mean(axis=0)
    e_mid = np.exp(mag_log[mid, :]).mean(axis=0) + 1e-12
    ratio = e_upper / e_mid

    L_upper = mag_log[upper, :]
    geo = np.exp(np.mean(L_upper, axis=0))
    arith = np.mean(np.exp(L_upper), axis=0) + 1e-12
    flatness = geo / arith

    med_ratio = float(np.median(ratio[active]))
    if med_ratio <= 0.0:
        return 0.0
    gritty = (flatness > 0.25) & (ratio > 1.2 * med_ratio) & active
    return float(np.clip(np.mean(gritty) * 3.0, 0.0, 1.0))


def _intensity_timeline(mag_log: np.ndarray, freqs: np.ndarray,
                        sr: int, hop: int,
                        step_s: float = 1.0) -> dict:
    """Per-second shimmer-intensity values in [0, 1]. Computed as the
    mean above-median fraction in 8-16 kHz, scaled so typical shimmery
    seconds land near 1.0 and clean seconds near 0.0."""
    band = np.where((freqs >= 8000.0) & (freqs <= 16000.0))[0]
    if band.size < 8:
        return {"step_s": float(step_s), "intensity": []}
    L = mag_log[band, :]
    L_med = median_filter(L, size=(9, 1), mode="nearest")
    mask = ((L - L_med) * (20.0 / np.log(10.0)) > 6.0).astype(np.float32)
    frame_dt_s = hop / float(sr)
    if frame_dt_s <= 0.0:
        return {"step_s": float(step_s), "intensity": []}
    frames_per_step = max(1, int(round(step_s / frame_dt_s)))
    n = mask.shape[1]
    out = []
    for i in range(0, n, frames_per_step):
        chunk = mask[:, i:i + frames_per_step]
        if chunk.size == 0:
            continue
        # Scale so a fraction of ~0.2 maps to ~1.0 (typical shimmer density).
        v = float(np.clip(chunk.mean() * 5.0, 0.0, 1.0))
        out.append(round(v, 3))
    return {"step_s": float(step_s), "intensity": out}


# ---------------------------------------------------------------------------
# Per-artifact scoring
# ---------------------------------------------------------------------------

def _score_artifacts(mag_log: np.ndarray, freqs: np.ndarray,
                     sr: int, hop: int):
    """Return (scores, reasons): two dicts keyed by artifact preset name."""

    # Cache band-specific feature values once.
    dens_8_18  = _band_density(mag_log, freqs, 8000.0, 18000.0)
    dens_8_16  = _band_density(mag_log, freqs, 8000.0, 16000.0)
    dens_12_18 = _band_density(mag_log, freqs, 12000.0, 18000.0)
    dens_6_10  = _band_density(mag_log, freqs, 6000.0, 10000.0)
    dens_3_8   = _band_density(mag_log, freqs, 3000.0, 8000.0, thr_db=4.0)
    dens_4_12  = _band_density(mag_log, freqs, 4000.0, 12000.0, thr_db=4.0)

    persist_8_12  = _persistent_tone_score(mag_log, freqs, 8000.0, 12000.0)
    persist_10_15 = _persistent_tone_score(mag_log, freqs, 10000.0, 15000.0)

    flat_8_12  = _tonality_band(mag_log, freqs, 8000.0, 12000.0)
    flat_8_18  = _tonality_band(mag_log, freqs, 8000.0, 18000.0)
    flat_10_15 = _tonality_band(mag_log, freqs, 10000.0, 15000.0)
    flat_3_8   = _tonality_band(mag_log, freqs, 3000.0, 8000.0)

    period_8_16 = _time_periodicity_score(
        mag_log, freqs, 8000.0, 16000.0, sr, hop, lag_ms_range=(30.0, 200.0))
    comb        = _freq_comb_score(mag_log, freqs)
    top_conc    = _top_band_concentration(mag_log, freqs)
    sib_burst   = _sibilance_burst_score(mag_log, freqs)
    tail        = _tail_flutter_score(mag_log, freqs)

    vocal_glaze = _vocal_glaze_score(mag_log, freqs)
    echo_sheen  = _echo_sheen_score(mag_log, freqs)
    pres_wash   = _presence_wash_score(mag_log, freqs)
    metal_wash  = _metallic_wash_score(mag_log, freqs)
    harsh_grit  = _harsh_grit_score(mag_log, freqs)

    # `tonalness` = inverse of flatness (peaky => 1, noisy => 0).
    tonalness_8_12  = max(0.0, 1.0 - flat_8_12)
    tonalness_10_15 = max(0.0, 1.0 - flat_10_15)
    # top_conc is unbounded; squash it into roughly 0..1.
    # 2x scale so typical AI tracks (~0.15-0.3) land at 0.3-0.6 instead
    # of saturating at 1.0.  The old 5x made the AND gate in
    # vocal_glaze_plus pass unconditionally.
    top_conc_n = float(np.clip(top_conc * 2.0, 0.0, 1.0))

    scores = {
        "cymbal_sheen":      0.7 * persist_8_12 + 0.3 * tonalness_8_12,
        "laser_whistle":     max(0.0,
                                 0.6 * persist_10_15
                                 + 0.4 * tonalness_10_15
                                 - 0.2 * dens_8_18),
        "air_brittle":       0.6 * dens_12_18 + 0.4 * top_conc_n,
        "sibilance_rattle":  0.7 * sib_burst + 0.3 * dens_6_10,
        "cymbal_chatter":    0.5 * period_8_16 + 0.3 * dens_8_16 + 0.2 * comb,
        "broadband_fizz":    0.6 * dens_8_18 + 0.4 * flat_8_18,
        "checkerboard_grid": 0.7 * comb + 0.3 * dens_8_16,
        "reverb_flutter":    0.6 * tail + 0.4 * dens_8_16,
        "vocal_glaze":       0.7 * vocal_glaze + 0.2 * sib_burst + 0.1 * dens_6_10,
        # Combo: scores high only when BOTH the vocal-glaze signature AND
        # a brilliance-band signature are genuinely present.  Geometric
        # mean naturally requires both inputs to be high — if either is
        # near zero the score collapses.  No self-boost multiplier; the
        # old formula was quadratic in vocal_glaze and always won.
        "vocal_glaze_plus":  float(np.sqrt(
                                 vocal_glaze
                                 * max(dens_8_18, persist_8_12, top_conc_n))),
        "echo_sheen":        0.7 * echo_sheen + 0.2 * pres_wash + 0.1 * flat_3_8,
        "presence_haze":     0.6 * pres_wash + 0.3 * flat_3_8 + 0.1 * dens_3_8,
        "phantom_cymbal":    0.5 * metal_wash + 0.3 * pres_wash + 0.2 * dens_6_10,
        "harsh_veil":        0.5 * harsh_grit + 0.3 * dens_4_12 + 0.2 * flat_3_8,
        "deep_scrub":        max(0.0,
                                 0.4 * max(vocal_glaze, echo_sheen,
                                           pres_wash, metal_wash, harsh_grit)
                                 + 0.3 * dens_8_18
                                 + 0.3 * dens_4_12
                                 - 0.3),
    }
    scores = {k: float(np.clip(v, 0.0, 1.0)) for k, v in scores.items()}

    reasons = {
        "cymbal_sheen":
            f"Sustained tonal peak in 8-12 kHz "
            f"(persistence {persist_8_12:.2f}, tonalness {tonalness_8_12:.2f}).",
        "laser_whistle":
            f"Narrow tonal chirps in 10-15 kHz "
            f"(persistence {persist_10_15:.2f}, tonalness {tonalness_10_15:.2f}).",
        "air_brittle":
            f"Energy concentrated above 12 kHz "
            f"(top/mid ratio {top_conc:.2f}, density {dens_12_18:.2f}).",
        "sibilance_rattle":
            f"Sibilance bursts in 6-10 kHz over vocal frames "
            f"(burst rate {sib_burst:.2f}).",
        "cymbal_chatter":
            f"Periodic high-band chatter "
            f"(time-periodicity {period_8_16:.2f}, comb {comb:.2f}).",
        "broadband_fizz":
            f"Noise-like haze across 8-18 kHz "
            f"(density {dens_8_18:.2f}, flatness {flat_8_18:.2f}).",
        "checkerboard_grid":
            f"Comb-spaced ringing in the high band "
            f"(autocorr {comb:.2f}, density {dens_8_16:.2f}).",
        "reverb_flutter":
            f"Shimmer concentrated in decay regions "
            f"(tail density {tail:.2f}).",
        "vocal_glaze":
            f"Shimmery glaze on vocal harmonics in 2-8 kHz "
            f"(glaze {vocal_glaze:.2f}, sibilance {sib_burst:.2f}).",
        "vocal_glaze_plus":
            f"Vocal glaze AND brilliance-band wash both present "
            f"(glaze {vocal_glaze:.2f}, "
            f"top density {dens_8_18:.2f}, persistence {persist_8_12:.2f}, "
            f"top conc {top_conc_n:.2f}).",
        "echo_sheen":
            f"Signal-correlated shimmer shadowing musical content "
            f"(correlation {echo_sheen:.2f}, wash {pres_wash:.2f}).",
        "presence_haze":
            f"Broadband noise-like wash in 3-8 kHz presence band "
            f"(wash {pres_wash:.2f}, flatness {flat_3_8:.2f}).",
        "phantom_cymbal":
            f"Metallic cymbal-like wash in 4-10 kHz "
            f"(metallic {metal_wash:.2f}, wash {pres_wash:.2f}).",
        "harsh_veil":
            f"Gritty texture across 4-12 kHz upper-mids "
            f"(grit {harsh_grit:.2f}, density {dens_4_12:.2f}).",
        "deep_scrub":
            f"Multiple artifact types across wide band "
            f"(wash {max(vocal_glaze, echo_sheen, pres_wash, metal_wash, harsh_grit):.2f}, "
            f"high density {dens_8_18:.2f}).",
    }
    return scores, reasons


def suggest_preset(input_path: str,
                   max_duration_s: float = 30.0,
                   n_fft: int = 4096,
                   hop: int = 1024) -> dict:
    """Analyse the first `max_duration_s` seconds of `input_path` and return
    a ranked list of artifact-shape presets that match what the audio
    sounds like.

    Returns a dict:

        {
          "preset": "cymbal_chatter",                  # top pick
          "ranked": [
            {"name", "label", "score", "confidence", "reason"},
            ...up to 3 entries...
          ],
          "timeline": {"step_s": 1.0, "intensity": [...]},
          "scores": { ...all artifact scores... },
          "checkerboard_score": 0.12,                  # back-compat
          "metrics": {"sample_rate": ..., "analyzed_seconds": ...}
        }
    """
    # Local import: avoid forcing scipy onto the import path of presets.py.
    from presets import label_for

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
    mag_log = np.log(np.abs(Z) + 1e-12)

    scores, reasons = _score_artifacts(mag_log, f, sr, hop)
    sorted_items = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_name, best_score = sorted_items[0]
    second_score = sorted_items[1][1] if len(sorted_items) > 1 else 0.0
    cb_score = _freq_comb_score(mag_log, f)

    # Below this floor everything looks clean -> bail to generic.
    _MIN_ACTIONABLE_SCORE = 0.05

    if best_score < _MIN_ACTIONABLE_SCORE:
        ranked = [{
            "name": "generic",
            "label": label_for("generic"),
            "score": 0.0,
            "confidence": 0.0,
            "reason": ("Nothing notable in the brilliance band; "
                       "safe defaults will do."),
        }]
        best_name = "generic"
        timeline = _intensity_timeline(mag_log, f, sr, hop, step_s=1.0)
    else:
        # Confidence: blend absolute score with margin over the runner-up.
        margin = 0.0
        if best_score > 1e-6:
            margin = max(0.0, 1.0 - second_score / best_score)
        confidence_top = float(np.clip(
            best_score * (0.4 + 0.6 * margin) * 2.0, 0.0, 1.0))

        ranked = []
        for i, (name, score) in enumerate(sorted_items[:3]):
            if score <= 0.0:
                continue
            if i == 0:
                conf = confidence_top
            else:
                conf = float(np.clip(score / best_score, 0.0, 1.0))
            ranked.append({
                "name":       name,
                "label":      label_for(name),
                "score":      round(float(score), 3),
                "confidence": round(float(conf), 3),
                "reason":     reasons.get(name, ""),
            })
        timeline = _intensity_timeline(mag_log, f, sr, hop, step_s=1.0)

    return {
        "preset": best_name,
        "ranked": ranked,
        "timeline": timeline,
        "scores": {k: round(float(v), 3) for k, v in scores.items()},
        "checkerboard_score": round(float(cb_score), 3),
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
