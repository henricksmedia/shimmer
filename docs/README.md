# Shimmer — technical overview

Offline, local, deterministic removal of AI-generation artifacts, followed by
a mastering chain. Built for tracks from Suno and similar diffusion-based
music models.

For the user-facing introduction, see the [root README](../README.md).
For the exhaustive parameter and API reference, see [FEATURES.md](FEATURES.md).
For remote access / hosting options (and why Cloudflare Pages isn't a fit),
see [DEPLOYMENT.md](DEPLOYMENT.md). For a research-backed review of every
preset against the causes of AI-music artifacts, see
[PRESET_REVIEW.md](PRESET_REVIEW.md), for the presets / stems /
signal-chain roadmap that follows from it, see [PLAN.md](PLAN.md), and
for the stems-engine model shortlist with licences, see
[STEMS_MODELS.md](STEMS_MODELS.md).

## Architecture

```
Input → [trim] → de-click → static repair (fixed-line notches)
      → [tone curve] → linear-phase crossover @ 4.5 kHz (preset-dependent)
                              ├── low band ─────────────── (bypassed)
                              └── high band → M/S split
                                     ├── mid  (0.2× strength)
                                     └── side (1.0× strength)
                                            ├── fine pass 1024/256
                                            │   (flicker tamer, spectral de-esser)
                                            └── 9-stage STFT engine 4096/1024
        → side-width compensation → recombine → wet/dry mix
        → post filters → user EQ → mastering → export
```

**Deterministic repairs** (`repair.py`) run first, before anything
adaptive: a high-band de-clicker (linear-prediction detection, isolated
short runs only, AR re-synthesis) and static zero-phase notches on the
generator's fixed tonal lines and comb teeth found by a whole-file scan
(`detect.scan_fixed_lines`). The notches apply to L and R at full depth:
a fixed 17.7 kHz line gets none of the Mid protection the engine gives
vocals. The source's bandwidth cutoff is measured too; shelves and the
tone curve never boost above it.

**Cleaning engine** (`engine.py`, STFT domain, 4096-pt FFT / 1024 hop). Nine
stages run in registry order: Expander → Denoise → De-resonator → Shimmer
suppressor → De-harsh → Flicker tamer → De-checker → Narrow-tone kill →
Noise resynth. Two shared gates ride alongside every stage: a
spectral-flatness gate and a transient-hold gate (~70 ms hold).

**Mastering chain** (`mastering.py`): high-pass at 25 Hz → single static LUFS
gain → cubic soft clip → 4× oversampled true-peak limiter. Loudness targets
are −14 / −11 / −9 LUFS; export ceilings are −1.0 dBTP for lossless and
−1.5 dBTP for lossy formats. The corrective tone curve is computed from the
raw file and applied *before* cleaning, bounded to +2.0 / −3.0 dB with
5–12 kHz boosts capped at +0.5 dB.

No machine learning in the cleanup path — the same inputs always produce the
same output.

## Presets

19 visible artifact-shape presets (`presets.py`), each targeting a distinct
artifact signature rather than a model version:

`generic` · `suno_hash` · `cymbal_sheen` · `laser_whistle` · `air_brittle` ·
`sibilance_rattle` · `cymbal_chatter` · `broadband_fizz` ·
`checkerboard_grid` · `reverb_flutter` · `vocal_glaze` · `vocal_glaze_plus` ·
`echo_sheen` · `presence_haze` · `phantom_cymbal` · `harsh_veil` ·
`deep_scrub` · `muddy_boxy` · `dark_mix_rescue`

Legacy model-version keys (`suno_v3`, `suno_v4.5`, …) still resolve as hidden
aliases so saved settings keep working, but they are not shown in the UI.

`preset_strength` (0–200%) rescales amount-style keys only — band edges,
time constants, and detection thresholds are never scaled. The whitelist in
`params.apply_preset_strength` is mirrored in the frontend so visible sliders
track the hidden keys.

## Features

- **Auto-detect** (`detect.py`, `probe.suggest_preset`) — scans the whole
  file for calibrated artifact evidence, then *verifies* every artifact
  preset by running it through the real cleaning pipeline on the hottest
  window and measuring what it removed (artifact-like vs. protected
  material). Returns up to 6 ranked matches, each with a recommended
  preset strength, an optional second-pass suggestion, and a per-second
  intensity timeline used to anchor the preview loop.
- **Live preview** — loops a 5–20 s window, re-rendered server-side on every
  parameter change with an LRU cache; A/B is gapless via Web Audio gain
  crossfades. Slices are mastered with the whole-file static gain so the
  loop sits at the level the export will have.
- **Parametric EQ** (`eq.py`) — up to 12 bands, RBJ biquads, applied
  zero-phase (`sosfiltfilt`) after cleaning and before mastering.
- **Remix** (`stems.py`, `stem_effects.py`) — Demucs `htdemucs` 4-stem
  separation in an isolated side venv, GPU-accelerated when CUDA is
  available, cached by SHA-1 content hash. Per-stem formant shift,
  saturation, doubler, and reverb. Projects autosave per track.
- **Batch** — folder in / folder out, fixed preset or per-file auto-detect,
  streamed progress over SSE.
- **Multi-format I/O** — WAV, FLAC, OGG natively; MP3 / M4A / AAC via ffmpeg.
  Input and output formats are independent.
- **Settings persistence** — last-used preset, sliders, mastering, and EQ
  restore on launch when "Remember settings" is enabled.
- **Signal Chain** (`chain.py`, `POST /api/chain`) — the chain view is
  generated from the same Params / MasterParams / options a run would
  use, in pipeline order, with live badges and active/inactive state per
  module, so it cannot drift from the sound path.

## Running

Windows: double-click `start.bat`. macOS/Linux: `./start.sh`. Both bootstrap
[uv](https://docs.astral.sh/uv/) (prompting first), create a local venv,
install dependencies, and open <http://localhost:7860> once the server
responds to an HTTP poll — not on a fixed delay.

Manual:

```bash
pip install -r requirements.txt
python -m uvicorn shimmer.server:app --host 127.0.0.1 --port 7860
```

### Platform notes

Pure Python, so it runs on Windows, macOS, and Linux. Platform-specific
details:

- `_winfix.py` patches a Windows-only WMI hang in `platform.uname()` and is a
  no-op elsewhere. It must be imported before scipy/numpy.
- Settings and projects live in `%APPDATA%/Shimmer` on Windows and
  `~/.config/shimmer` elsewhere (`settings_store._settings_dir`).
- Stem separation resolves its side-venv interpreter through
  `stems._venv_python` (`Scripts/python.exe` on Windows, `bin/python` on
  POSIX). GPU offload is CUDA-only — Apple Silicon (MPS) falls back to CPU.
- The Batch folder picker uses tkinter and degrades to manual path entry when
  Tk is unavailable.

`start.bat` (Windows) and `start.sh` (macOS/Linux) are equivalent launchers.
`start.sh` targets bash 3.2 so it runs on stock macOS, and is tracked with
mode `100755` so the executable bit survives cloning.

## Command line

```bash
python -m shimmer input.wav output.wav
python -m shimmer input.wav output.wav --preset cymbal_chatter
python -m shimmer --list-presets
python -m shimmer --suggest input.mp3
```

Every processing parameter can be overridden; run `python -m shimmer --help`
for the full list.

## MP3 / M4A support

Compressed formats require **ffmpeg** on your PATH:

- Windows: `winget install ffmpeg`
- macOS: `brew install ffmpeg`
- Linux: `apt install ffmpeg`

Without ffmpeg, WAV / FLAC / OGG still work.

## Tests

```bash
python -m pytest tests/
```

CI runs byte-compilation, an import smoke test, and the full suite on Python
3.11 and 3.12.

## Project layout

```
start.bat           Windows launcher (uv bootstrap + server)
start.sh            macOS / Linux launcher (same flow)
shimmer/            The Python package (all application code)
  cli.py            CLI entry point — `python -m shimmer`
  server.py         FastAPI backend (routes, SSE, job orchestration)
  pipeline.py       clean_and_master — band split, M/S, recombine
  engine.py         STFT loop and the nine Stage implementations
  mastering.py      Loudness analysis, tone curve, limiter
  params.py         Params / MasterParams dataclasses (source of truth)
  presets.py        Artifact-shape preset factories
  detect.py         Auto-detect: evidence scan + pipeline verification
  chain.py          Signal Chain description generated from Params
  repair.py         Deterministic repairs: de-click, static notches, cutoff
  finepass.py       Fine-grid pass (1024/256): flicker tamer, spectral de-esser
  probe.py          Region diagnostics, suggest_preset wrapper
  eq.py             Parametric EQ (RBJ biquads, zero-phase)
  bands.py          Linear-phase crossover
  dsp.py            Primitive DSP helpers
  trim_silence.py   Export-time silence trimming
  edges.py          Head/tail render-glitch scan (reported, never applied)
  audio_io.py       File I/O, measurement, format dispatch
  stems.py          Demucs separation + cache
  stem_effects.py   Per-stem effect chain
  jobs.py           In-process job store
  preview_store.py  Resident decoded sessions for live preview
  projects_store.py Per-track remix projects (SHA-1 keyed)
  settings_store.py UI settings persistence
  _winfix.py        Windows WMI hang workaround (imported by __init__)
static/             Frontend: HTML, split CSS, ES-module JS
scripts/            Launcher helpers (browser open-when-ready)
tests/              pytest suite
```

## License

GNU Affero General Public License v3 — see [LICENSE](../LICENSE).

Shimmer invokes Demucs as a subprocess in an isolated virtual environment
rather than importing or bundling it, so there is no linkage between the two
codebases. Contributions are accepted under AGPL-3.0 with an additional grant
allowing Henricks Media to include them in a commercially licensed build; see
the Contributing section of the [root README](../README.md#contributing).
