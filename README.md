# Shimmer by The Treq

A desktop tool for removing *shimmer* — the high-frequency metallic fizz,
narrow-band birdies, and periodic "checkerboard" artifacts produced by
AI music generators like Suno.  Offline, local, deterministic.

## Highlights

- **Stage-list DSP engine.** Expander → Denoise → De-resonator → Shimmer
  → **De-harsh** → **De-checkerboard** → Noise-resynth — all STFT-domain.
- **Multi-format I/O.** WAV, FLAC, OGG (native), MP3 / M4A / AAC (via
  ffmpeg).  Input and output formats are independent.
- **Per-model presets.** `generic`, `suno_v3`, `suno_v3.5`, `suno_v4`,
  `suno_v4.5`, `suno_v5`, `suno_v5_pro`, `suno_v5.5`.
- **Auto-detect.** Analyses your file and picks the best preset.
- **FastAPI + native HTML UI.** Three native `<audio>` elements share a
  single playhead for instant A/B/C comparison: click any card to hear
  it at the current time; the others pause and stay seeked in sync.
  No Gradio.
- **Batch tab.** Point at a folder and walk the whole thing.
- **Settings persistence.** Last-used preset / sliders restore on launch.

## Running the app

On Windows, double-click `Shimmer.bat`.  The first launch installs
dependencies from `requirements.txt`.  The browser opens automatically
at <http://localhost:7860>.

Manual launch:

```bash
pip install -r requirements.txt
python -m uvicorn server:app --host 127.0.0.1 --port 7860
```

## Command-line usage

```bash
python shimmer.py input.wav output.wav --preset suno_v5.5
python shimmer.py --list-presets
python shimmer.py --suggest input.mp3
```

All processing parameters can be overridden on the CLI; run
`python shimmer.py --help` for the full list.

## MP3 / M4A support

MP3, M4A, and AAC files require **ffmpeg** on your system PATH because
`pydub` delegates the actual decode/encode to ffmpeg.

- Windows: `winget install ffmpeg` (or download from
  <https://ffmpeg.org/download.html>)
- macOS:   `brew install ffmpeg`
- Linux:   `apt install ffmpeg` (or your distro's equivalent)

If ffmpeg isn't present, WAV / FLAC / OGG still work; only compressed
formats are affected.

## Project layout

```
engine.py           STFT loop and Stage implementations
params.py           Params dataclass (single source of truth)
presets.py          Per-model preset factories
audio_io.py         File I/O, measurements, format dispatch
probe.py            Spectrograms, residuals, suggest_preset()
dsp.py              Primitive DSP helpers
server.py           FastAPI backend
jobs.py             Job store for async processing
settings_store.py   Persistence of UI settings
shimmer.py          CLI entry point
static/             Frontend: HTML, split CSS, ES-module JS
```

## License

MIT.
