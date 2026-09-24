# Shimmer — technical overview

Shimmer cleans and masters AI-generated music (Suno and similar tools). It
runs offline, on your own computer. Version 2.0.0 is a rebuild of 1.1.1:
the screens stayed, and the engine behind them is new.

For the user-facing introduction, see the [root README](../README.md).

## Docs index

| Doc | What it holds |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | How 1.x worked, why it was rebuilt, and the plan (§15), the file-by-file fates (§16), the new layout (§18.3), the review rules (§19) and the cards (§19.3) |
| [REBUILD-TRACKER.md](REBUILD-TRACKER.md) | Where each step of the rebuild stands, and what is still open |
| [SOUND-CHANGES.md](SOUND-CHANGES.md) | Every change that alters an export against 1.1.1, with numbers |
| [STEP6-FIXES.md](STEP6-FIXES.md) | How each card's fix was measured, and the numbers behind each Amount slider |
| [API.md](API.md) | Every HTTP route the screens call, what it sends and what it reads back |
| [FEATURES.md](FEATURES.md) | The full feature reference for 2.0: every tab, card, format and setting |
| [GETTING-STARTED.md](GETTING-STARTED.md) | A step-by-step guide for new users: install, a first master, Batch, Remix, settings, and fixes for common problems |
| [PROMO-ASSETS.md](PROMO-ASSETS.md) | One command that makes the screenshots, audio clips and short videos the marketing kit asks for, from the app itself |

Background and rules:

- [GOALS.md](GOALS.md) — what Shimmer is for, and the decision rule every fix
  must pass ("Never damage the music").
- [PITFALLS.md](PITFALLS.md) — wrong turns already taken, and the rule each
  one left behind.
- [STYLE.md](STYLE.md) — house rules for code and docs.
- [MASTERING-SOURCES.md](MASTERING-SOURCES.md) — the sources behind the
  mastering choices.
- [SHIMMER-RESEARCH.md](SHIMMER-RESEARCH.md) — research on the shimmer
  artifact and what could reduce it.
- [CHAIN-AUDIT.md](CHAIN-AUDIT.md) — every stage of the sound chain checked
  against user reports, pro mastering practice and measurement, with a
  ranked build plan.
- [STEMS_MODELS.md](STEMS_MODELS.md) — the stem-separation model shortlist,
  with licences.
- [DEPLOYMENT.md](DEPLOYMENT.md) — remote access and hosting options, and
  why Cloudflare Pages isn't a fit.

History (1.x, kept for the record): [PLAN.md](PLAN.md),
[PRESET_REVIEW.md](PRESET_REVIEW.md),
[HANDOFF-CHECKLIST.md](HANDOFF-CHECKLIST.md),
[BRIGHTNESS-ASSESSMENT.md](BRIGHTNESS-ASSESSMENT.md),
[IMPLEMENTATION.md](IMPLEMENTATION.md).

## The sound path

Every tab calls one function, `render(source, settings, window=None)` in
`shimmer/core/render.py`: the Master tab's preview and export, Batch, album
mode, the Remix export, and the command line. Every file is written by one
function, `export()` in `shimmer/core/export.py`.

```
Read → Trim → Sample rate → Fixes → Tone → EQ → Master → Export → Report

Fixes, in order:   de-click*  →  notch (Fixed tones)  →  spectral de-noise (Shimmer)
                   →  de-esser (Sibilance)  →  dynamic EQ (Harshness, Low-mid build-up)
Tone:              mastering on only; the built-in target or a reference track
Master:            25 Hz low-cut → one loudness gain (whole song) → peak shaper
                   → true-peak limiter (8× oversampled)
                   mastering off + Preserve volume: one gain back to the song's own level
Export:            16-bit TPDF dither → encode → lossy check → tags → release check

* built, but its card is not offered in the app yet (see "Cards and fixes")
```

These nine stages are `catalog.STAGES`. The progress window and the Signal
Chain view both read them.

**The preview is the export on a window.** A window renders only its span,
plus a 1.0 s lead-in and a 0.5 s tail, so the filters, notches and limiter
settle as they do in a full render. Everything that depends on the whole
song is worked out once and kept on the `Source`: the audio at other rates,
the fixed tones found, each fix's plan, the tone curve, and the loudness
before mastering. `tests/core/test_core_render_export.py` holds a window to
the same span of a full render: the difference must be at least 60 dB under
the signal, with no fixes and with all four fixes on at full.

**Rules the code keeps:**

- Each stage runs at its place in the chain. Analysis measures; it never
  changes sound.
- A bypass render (nothing on) returns the input bit for bit.
- No filter smears a hit: zero-phase only where its pre-echo stays inside
  20 ms, and a contract test holds every filter to −60 dB beyond 20 ms.
  Low-cuts and high-cuts run one way.
- `shimmer/core` never imports the web layer or the 1.x engine.
  `tests/api/test_api_contract.py` enforces this.

## Cards and fixes

`shimmer/core/catalog.py` holds the rules the screens show, stated once.
`GET /api/rules` serves it, and the screens read it instead of keeping their
own copies.

- `CARDS` — the nine "What do you hear?" cards: label, descriptor, icon,
  group, the tool that fixes it, its band, and where its Amount starts.
- `TOOL_LABELS` — the name each tool shows on screen.
- `TOOLS_READY` — the tools the screens offer. The notch, the tone target
  and the loudness target are proven. The de-esser, the dynamic EQ and the
  spectral de-noise are on to try, before their blind rounds. The de-click is
  not in the list: it misses moderate pops in dense music
  ([STEP6-FIXES.md](STEP6-FIXES.md)).
- `LOUDNESS_TARGETS` — Commercial −9 LUFS (the default), Balanced −11,
  Streaming standard −14. The keys (`cd`, `loud`, `streaming`) are 1.x's, so
  saved settings keep working.
- `FORMATS` — each export format and its true-peak ceiling: −1.0 dBTP for
  WAV and FLAC (24-bit, and the 16-bit 44.1 kHz release copies), −2.0 dBTP
  for MP3 320, OGG Vorbis and M4A.
- `EQ_LIMITS`, `EQ_TYPES`, `TONE_INTENSITIES`, `TONE_TILTS`, `MATCH_AMOUNT`.

Each fix is one module in `shimmer/core/repair/`. `render.py` lists them in
`_FIX_TOOLS`, in chain order. Each module has:

- `plan(audio, sr)` — worked out once from the whole song, and kept.
- `apply(x, sr, plan, amount, offset)` — returns `x` itself when it changes
  nothing, so a bypass stays bit-exact.
- `summary(plan, amount)` — for the report.

A module with `SLOW_PLAN = True` reports how far it has got under Fixes.
Today that is the spectral de-noise, which reads the whole song once (about
50 s for a 3-minute song). `prepare()` does that work ahead of a preview, as
its own cancellable job (`POST /api/prepare`). Its weights are
`shimmer/core/repair/hash_remover.npz`; without the file the tool does
nothing and says so.

Cards whose fix is part of mastering (Lack of air, Loudness) report "with
mastering" or "needs mastering". A card with no ready fix reports "not built
yet" and changes nothing.

**Analyze** (`core.findings`) reports only what it can measure well today:
the fixed tones (the whole-file scan the notch uses) and how far the song is
under the loudness target. `core.tone_plan()` plans the Suggested EQ, judged
after the fixes and the tone curve, the way the song will render.

**Old saved settings** migrate through `core.settings.migrate()`. The
`LEGACY_PRESETS` table maps each 1.x preset to the card it became;
`LEGACY_ALIASES` maps the version-named keys (`suno_v5_pro` and the rest).
`settings_store.migrate_saved()` uses the same tables for `settings.json`.

## Mastering

With mastering on, `render()` applies, in order: the tone curve (1.1.1's,
ported bit-exact, or `tone.match_curve` toward a reference track), the user
EQ, a 25 Hz low-cut, one static loudness gain worked out from the whole song,
the peak shaper, and the true-peak limiter. The limiter finds peaks at 8×,
ramps its gain across the 2 ms lookahead, and aims 0.17 dB under the
ceiling.

Reference-track matching takes 50 % of the difference by default, smoothed
over about an octave, at most ±3 dB, level-matched first.

`export()` adds TPDF dither to 16-bit files, never overwrites the source,
writes under a temporary name and renames into place, and measures the file
on disk. Each lossy file is decoded after encoding; if it is over −1.0 dBTP,
it is turned down by the excess and encoded again (`lossy_trim_db` in the
report).

**Album mode** measures each track just before mastering's gain
(`core.premaster_levels`), picks one gain for the record
(`master.loudness`), then renders each track again with
`render(..., gain_db=)`. The shaper and limiter still act per song.

## Running

Windows: double-click `start.bat`. macOS/Linux: `./start.sh`. Both bootstrap
[uv](https://docs.astral.sh/uv/) (prompting first), create a local venv,
install dependencies, and open <http://localhost:7860> once the server
responds to an HTTP poll — not on a fixed delay. `SHIMMER_PORT` changes the
port.

`start.bat` also reinstalls when `requirements.txt` changes: it keeps the
SHA-256 of the last installed file in `.venv\requirements.sha256`. `start.sh`
only reinstalls when an import probe fails.

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
- Settings and projects are kept in `%APPDATA%/Shimmer` on Windows and
  `~/.config/shimmer` elsewhere (`settings_store._settings_dir`).
- Stem separation resolves its side-venv interpreter through
  `stems._venv_python` (`Scripts/python.exe` on Windows, `bin/python` on
  POSIX). GPU offload is CUDA-only — Apple Silicon (MPS) falls back to CPU.
- The Batch folder picker uses tkinter and degrades to manual path entry when
  Tk is unavailable.
- The page loads its fonts, including the Material Symbols icon font, from
  Google Fonts. Offline, icons show as their names.

`start.bat` (Windows) and `start.sh` (macOS/Linux) are equivalent launchers.
`start.sh` targets bash 3.2 so it runs on stock macOS, and is tracked with
mode `100755` so the executable bit survives cloning.

## Command line

```bash
python -m shimmer input.wav output.wav --target cd
python -m shimmer input.wav output.wav --fix tones=0.5 --no-auto
python -m shimmer input.wav release.wav --master --release
python -m shimmer --suggest input.mp3
python -m shimmer --list
```

The command line runs the same render and export as the Master tab.
Mastering is off unless `--master` or `--target` asks for it. `--fix
CARD[=AMOUNT]` turns on a card; `--preset` turns on the card a 1.x preset
became. `--list` prints the cards (ready, built but not passed yet, or no
fix yet), the loudness targets, the formats with their ceilings, and the
preset-to-card table. 1.x's cleaning controls (`--denoise`, `--start-hz` and
the rest) are accepted and ignored, with a note. Run
`python -m shimmer --help` for every option.

## MP3 / M4A support

Compressed formats require **ffmpeg** on your PATH:

- Windows: `winget install ffmpeg`
- macOS: `brew install ffmpeg`
- Linux: `apt install ffmpeg`

Without ffmpeg, WAV / FLAC / OGG still work.

## Tests

```bash
python -m pytest tests/                   # everything
python -m pytest tests/core tests/api     # the new engine and its routes
python -m pytest tests/core/test_core_render_export.py   # preview = export
```

- `tests/core/` — contract tests for the engine. Their signals are synthetic
  and seeded (`tests/core/conftest.py`), so no test needs a file outside the
  repo.
- `tests/api/` — route tests, and the contract that `shimmer/api` talks to
  the engine only through `shimmer.core`.
- `tests/test_*.py` — the older suite: the 1.x modules still present, the
  pieces kept from 1.x, and the measuring tools.

Tests that need the spectral de-noise's weights skip when
`hash_remover.npz` is missing.

CI (`.github/workflows/ci.yml`) runs on every push to `main` and `rebuild`:

- Linux, Python 3.11 and 3.12, with ffmpeg: byte-compile, import the server
  and the CLI, then the full suite.
- Windows, Python 3.12, with ffmpeg: the full suite.
- Updating from 1.1.1: install 1.1.1's requirements, then this version's,
  then import the server and the CLI.

The fixes are measured with `scripts/efficacy_harness.py --cards <card>`,
which runs a card's fix through `render()` exactly as the Master tab does
([STEP6-FIXES.md](STEP6-FIXES.md)).

## Project layout

```
start.bat              Windows launcher (uv bootstrap + server)
start.sh               macOS / Linux launcher (same flow)
shimmer/               The Python package
  __init__.py          version; imports _winfix first
  __main__.py          `python -m shimmer` runs cli.main
  cli.py               The command line, a thin layer over shimmer.core
  server.py            FastAPI app: mounts shimmer/api, serves the page and
                       the routes not yet moved (Remix, stems, batch, settings)
  core/                The engine: everything that changes or measures sound
    __init__.py        The public names the web layer may use
    render.py          render(): the one sound path; prepare(), premaster_levels()
    export.py          export(): the one way a file is written
    catalog.py         Cards, tool labels, loudness targets, formats, stages, EQ limits
    settings.py        One Settings object; migrate() for 1.x settings
    chain.py           What each stage does for a set of settings (Signal Chain view)
    tags.py            Read and write tags, per format
    progress.py        Stage reports and cancel
    audio/             io.py (load, save, resample), filters.py, eq.py (user EQ),
                       meters.py (LUFS, per-channel true peak), trim.py (silence trim)
    analyze/           Measures only: findings.py (Analyze), tones.py (fixed tones,
                       cutoff), tone_plan.py (Suggested EQ), track.py, edges.py,
                       percussion.py, report.py
    repair/            One module per fix: notch.py, declick.py, deesser.py,
                       dynamic_eq.py, hash_remover.py (+ hash_remover.npz weights)
    master/            loudness.py (gain, album gain), tone.py (tone curve, reference
                       match), limiter.py (peak shaper, true-peak limiter),
                       release.py (release check)
  api/                 The web layer; calls shimmer.core only
    render.py          /api/process, progress, cancel, metrics, result, preview,
                       prepare, size, reference/view, chain
    sessions.py        /api/upload, envelope, reference
    rules.py           GET /api/rules (the catalog)
    jobs.py            One job runner: progress stream and cancel
  stems.py             Remix: Demucs separation, quality tiers, cache
  stems_runner.py      The separation worker (runs in the side venv)
  stem_effects.py      Remix: per-stem effects and the stem sum
  projects_store.py    Remix projects, keyed by the file's SHA-1
  settings_store.py    UI settings on disk; migrate_saved() for 1.x files
  _winfix.py           Windows WMI hang workaround (imported by __init__)
static/                Frontend: HTML, split CSS, ES-module JS (no build step)
  js/fault-picker.js   The "What do you hear?" cards (reads /api/rules)
  js/reference-match.js  Tone target: built-in or a reference track
  js/chain.js          The Signal Chain view
  js/report.js         "What changed" spectrum card
scripts/               Launcher helper (open-when-ready.ps1) and measurement scripts
tests/                 pytest suite (core/, api/, and the older tests)
```

### 1.x modules still present

These are still in `shimmer/` until Step 7 deletes them
([REBUILD-TRACKER.md](REBUILD-TRACKER.md)). Nothing in `shimmer/core`
imports them. `shimmer/chain.py` and `shimmer/probe.py` are already gone.

- **The 1.x engine, retiring:** `engine.py`, `pipeline.py`, `finepass.py`,
  `bands.py`, `dsp.py`, `params.py`, `presets.py`, `detect.py`, `repair.py`,
  `mastering.py`, `eq.py`, `audio_io.py`, `edges.py`, `trim_silence.py`,
  `report.py`, `release.py`. Still used by the Remix loop's quick preview
  (1.x `master()`), the preset list (`/api/presets`), the preset menus on the
  Remix and Batch tabs, and the settings screens.
- **Names that now point at the new code:** `autoeq.py`
  (→ `core/analyze/tone_plan.py`), `jobs.py` (→ `api/jobs.py`),
  `preview_store.py` (→ `api/sessions.py`), `tags.py` (→ `core/tags.py`).
- **Measuring tools, kept outside the engine:** `artifacts.py` (the fault
  models), `perceptual.py` (the hearing model), `side_effects.py`,
  `budget.py`, `abtest.py` (the listening bench), `references.py` (the tone
  reference builder).

## License

GNU Affero General Public License v3 — see [LICENSE](../LICENSE).

Shimmer invokes Demucs as a subprocess in an isolated virtual environment
rather than importing or bundling it, so there is no linkage between the two
codebases. Contributions are accepted under AGPL-3.0 with an additional grant
allowing Henricks Media to include them in a commercially licensed build; see
the Contributing section of the [root README](../README.md#contributing).
