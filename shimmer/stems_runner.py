"""
stems_runner.py — The separation worker. Runs inside the separation venv
(.venv-stems), never the app venv: torch and Demucs live only there.

stems.py launches this file as a subprocess with the side venv's Python
and reads JSON lines from stdout, one event per line:

    {"event": "status",   "message": "Loading the model…"}
    {"event": "progress", "fraction": 0.42}
    {"event": "done", "sources": ["drums", "bass", "other", "vocals"],
     "sr": 44100, "elapsed_s": 31.2, "device": "cuda", "passes": 4}
    {"event": "error", "message": "..."}

Commands:

    stems_runner.py check
        → {"ok": true, "torch": "2.5.1+cu121", "demucs": "4.0.1",
           "cuda": true, "gpu": "NVIDIA GeForce RTX 4070 SUPER"}

    stems_runner.py separate --model htdemucs_ft --shifts 1 --device auto
                             --out <dir> <input audio>

Output: one 32-bit float WAV per source in <dir>, at the model's own
sample rate (44.1 kHz), written exactly as the model produced them. No
clipping, no rescaling, no 16-bit truncation — the stems sum back to
the mixture up to the model's own error, which is what the residual
stem and the null test in stems.py measure.

Progress comes from Demucs' own segment loop: demucs.apply wraps the
per-segment futures in tqdm when `progress=True`; this file swaps that
tqdm for a reporter, so the bar in the app moves with the real work
(models × shifts × segments) instead of sitting still for a minute.

This file must stay free of imports from the rest of the package: the
side venv does not have them, and it must import nothing heavy before
`check` has a chance to answer.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import types
from pathlib import Path


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def status(message: str) -> None:
    emit({"event": "status", "message": message})


# ── check ────────────────────────────────────────────────────────────────

def cmd_check() -> int:
    out: dict = {"ok": False, "roformer": False}
    try:
        import torch  # noqa: WPS433
        import demucs  # noqa: WPS433
        cuda = bool(torch.cuda.is_available())
        out.update({
            "ok": True,
            "torch": torch.__version__,
            "demucs": getattr(demucs, "__version__", "?"),
            "cuda": cuda,
            "gpu": torch.cuda.get_device_name(0) if cuda else "",
        })
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    try:
        import audio_separator  # noqa: F401,WPS433
        out["roformer"] = True
    except Exception:  # noqa: BLE001
        out["roformer"] = False
    emit(out)
    return 0 if out["ok"] else 1


# ── separate ─────────────────────────────────────────────────────────────

class _Progress:
    """Stands in for `tqdm.tqdm` inside demucs.apply.

    apply_model recurses bag → shifts → split; only the split level
    iterates segments through tqdm. One tqdm call is therefore one pass
    over the track, and the run has models × shifts passes in total.
    `base` and `span` map this stage into the run's overall progress
    (the hybrid engine spends its first part on the vocal model).
    """

    def __init__(self, passes: int, base: float = 0.0, span: float = 1.0) -> None:
        self.passes = max(1, int(passes))
        self.started = 0
        self._last = -1.0
        self.base = float(base)
        self.span = float(span)

    def report(self, frac: float) -> None:
        frac = max(0.0, min(1.0, float(frac)))
        # Throttle: the segment loop is fast on a GPU.
        if frac - self._last < 0.005 and frac < 1.0:
            return
        self._last = frac
        emit({"event": "progress", "fraction": self.base + self.span * frac})

    def __call__(self, iterable, **_kw):  # tqdm.tqdm(iterable, ...) shape
        items = list(iterable)
        idx = self.started
        self.started += 1
        n = max(1, len(items))

        def gen():
            for i, item in enumerate(items):
                self.report((idx + i / n) / self.passes)
                yield item
            self.report((idx + 1) / self.passes)
        return gen()


def _load_audio(path: str, want_sr: int, want_ch: int):
    """Read any soundfile-readable file → float32 torch (channels, n) at
    the model's sample rate and channel count."""
    import numpy as np
    import soundfile as sf
    import torch

    x, sr = sf.read(path, dtype="float32", always_2d=True)   # (n, ch)
    x = np.ascontiguousarray(x.T)                             # (ch, n)
    if x.shape[0] == 1 and want_ch == 2:
        x = np.concatenate([x, x], axis=0)
    elif x.shape[0] > want_ch:
        x = x[:want_ch]
    wav = torch.from_numpy(x)
    if sr != want_sr:
        import julius
        wav = julius.resample_frac(wav, sr, want_sr)
    return wav, sr


def _load_models(names, get_model, BagOfModels):
    """One model, or an ensemble of several averaged per stem.

    An ensemble is one flat BagOfModels: a named model that is itself a
    bag (htdemucs_ft) contributes its leaf models with their own rows,
    so each stem still comes from that bag's specialist. The first name
    is the strongest model and counts double against every later one.
    """
    loaded = [get_model(n) for n in names]
    if len(loaded) == 1:
        return loaded[0]
    models, weights = [], []
    for i, m in enumerate(loaded):
        scale = 1.0 if i == 0 else 0.5
        if isinstance(m, BagOfModels):
            for sub, w in zip(m.models, m.weights):
                models.append(sub)
                weights.append([scale * float(x) for x in w])
        else:
            models.append(m)
            weights.append([scale] * len(m.sources))
    return BagOfModels(models, weights=weights)


def _roformer_vocals(input_path: str, model_name: str, models_dir: str,
                     work_dir: str):
    """Vocals through audio-separator's RoFormer runner (Mel-Band /
    BS-RoFormer checkpoints). Returns (vocals, instrumental, sr) as
    (n, ch) float32 at the runner's 44.1 kHz.

    Normalisation and amplification are off, so instrumental stays
    exactly mix − vocals and the lanes still add back up to the track.
    """
    import logging

    import numpy as np
    import soundfile as sf
    from audio_separator.separator import Separator

    sep = Separator(
        log_level=logging.WARNING,
        model_file_dir=models_dir,
        output_dir=work_dir,
        output_format="WAV",
        normalization_threshold=1.0,
        amplification_threshold=0.0,
        use_soundfile=True,
        sample_rate=44100,
    )
    sep.load_model(model_filename=model_name)
    # Vocal models name their second stem Instrumental or Other depending
    # on the checkpoint; either way it is mix − vocals.
    names = {"Vocals": "rf_vocals", "Instrumental": "rf_instrumental",
             "Other": "rf_instrumental"}
    files = sep.separate(input_path, custom_output_names=names)
    found = {}
    for f in files or []:
        p = f if Path(f).is_absolute() else str(Path(work_dir) / f)
        low = Path(p).name.lower()
        if "rf_vocals" in low:
            found["vocals"] = p
        elif "rf_instrumental" in low:
            found["instrumental"] = p
    if "vocals" not in found:
        raise RuntimeError(f"the vocal model wrote no vocal stem ({files})")
    voc, sr = sf.read(found["vocals"], dtype="float32", always_2d=True)
    if "instrumental" in found:
        inst, sr2 = sf.read(found["instrumental"], dtype="float32", always_2d=True)
    else:
        mix, sr2 = sf.read(input_path, dtype="float32", always_2d=True)
        if sr2 != sr:
            raise RuntimeError("the vocal model's rate differs from the mix and no instrumental was written")
        n = min(len(mix), len(voc))
        inst = (mix[:n] - voc[:n]).astype(np.float32)
    n = min(len(voc), len(inst))
    for p in found.values():
        try:
            Path(p).unlink()
        except OSError:
            pass
    return voc[:n], inst[:n], int(sr)


def _separate_once(model, wav, device: str, shifts: int, segment,
                   passes: int, overlap: float = 0.25,
                   base: float = 0.0, span: float = 1.0):
    import demucs.apply as apply_mod
    from demucs.apply import apply_model

    reporter = _Progress(passes, base, span)
    # Rebind only demucs.apply's own `tqdm` name: nothing else in the
    # process (torch.hub's download bar, for one) sees the swap.
    real_tqdm = apply_mod.tqdm
    apply_mod.tqdm = types.SimpleNamespace(tqdm=reporter)
    try:
        return apply_model(model, wav[None], device=device, shifts=shifts,
                           split=True, overlap=overlap, progress=True,
                           segment=segment)[0]
    finally:
        apply_mod.tqdm = real_tqdm


def cmd_separate(args: argparse.Namespace) -> int:
    t0 = time.time()
    try:
        import numpy as np
        import soundfile as sf
        import torch
        from demucs.apply import BagOfModels
        from demucs.pretrained import get_model
    except Exception as e:  # noqa: BLE001
        emit({"event": "error",
              "message": f"Separation engine import failed: {type(e).__name__}: {e}"})
        return 2

    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        status("CUDA not available in this environment — using the CPU")
        device = "cpu"

    names = [n.strip() for n in str(args.model).split("+") if n.strip()]
    status(f"Loading the {' + '.join(names)} model{'s' if len(names) > 1 else ''}…")
    try:
        model = _load_models(names, get_model, BagOfModels)
    except Exception as e:  # noqa: BLE001
        emit({"event": "error", "message": f"Could not load model '{args.model}': {e}"})
        return 3
    model.eval()
    n_models = len(model.models) if isinstance(model, BagOfModels) else 1
    shifts = max(0, int(args.shifts))
    passes = n_models * max(1, shifts)
    overlap = min(0.9, max(0.05, float(args.overlap)))

    hybrid = args.engine == "hybrid"
    rf_vocals = None
    rf_sr = 0
    vocal_s = 0.0
    if hybrid:
        # Stage one: the vocal specialist takes the vocals out; Demucs then
        # splits only what is left, so its own vocal output is just bleed.
        status(f"Separating the vocals ({args.vocal_model})…")
        emit({"event": "progress", "fraction": 0.03})
        t_voc = time.time()
        try:
            rf_vocals, instrumental, rf_sr = _roformer_vocals(
                args.input, args.vocal_model, args.models_dir, args.out)
        except Exception as e:  # noqa: BLE001
            emit({"event": "error", "message": f"Vocal model failed: {type(e).__name__}: {e}"})
            return 6
        vocal_s = round(time.time() - t_voc, 2)
        emit({"event": "progress", "fraction": 0.45})
        status("Splitting the rest into drums, bass and other…")
        wav = torch.from_numpy(np.ascontiguousarray(instrumental.T))
        if wav.shape[0] == 1 and model.audio_channels == 2:
            wav = wav.repeat(2, 1)
        in_sr = rf_sr
        if rf_sr != model.samplerate:
            import julius
            wav = julius.resample_frac(wav, rf_sr, model.samplerate)
    else:
        status("Reading the track…")
        try:
            wav, in_sr = _load_audio(args.input, model.samplerate, model.audio_channels)
        except Exception as e:  # noqa: BLE001
            emit({"event": "error", "message": f"Could not read '{args.input}': {e}"})
            return 4

    # Demucs' own normalisation (see demucs.separate): the model expects a
    # standardised mixture and the sources are scaled back afterwards.
    ref = wav.mean(0)
    mean, std = float(ref.mean()), float(ref.std())
    if std < 1e-8:
        std = 1.0
    wav = (wav - mean) / std

    status(f"Separating on {'the GPU' if device == 'cuda' else 'the CPU'}…")
    sources = None
    attempts = [(device, None)]
    if device == "cuda":
        # Out of VRAM: shorter segments halve the footprint; then the CPU.
        attempts += [("cuda", 4.0), ("cpu", None)]
    last_err: Exception | None = None
    base, span = (0.45, 0.55) if hybrid else (0.0, 1.0)
    for dev, seg in attempts:
        try:
            sources = _separate_once(model, wav, dev, shifts, seg, passes, overlap,
                                     base, span)
            device = dev
            break
        except RuntimeError as e:
            msg = str(e).lower()
            oom = ("out of memory" in msg) or ("cuda" in msg and "alloc" in msg)
            if not oom or dev == "cpu":
                last_err = e
                break
            last_err = e
            if hasattr(torch, "cuda"):
                torch.cuda.empty_cache()
            status("GPU memory ran out — retrying with smaller segments"
                   if seg is None else "Still out of GPU memory — falling back to the CPU")
    if sources is None:
        emit({"event": "error", "message": f"Separation failed: {last_err}"})
        return 5

    sources = sources * std + mean
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    status("Writing the stems…")
    stem_names = list(model.sources)
    for src, name in zip(sources, stem_names):
        arr = np.ascontiguousarray(src.cpu().numpy().T).astype(np.float32)  # (n, ch)
        if hybrid and name == "vocals" and rf_vocals is not None:
            # The specialist's vocal plus whatever bleed Demucs still
            # heard in the instrumental, so the four lanes sum to the mix.
            if rf_sr != model.samplerate:
                import julius
                rf_t = julius.resample_frac(
                    torch.from_numpy(np.ascontiguousarray(rf_vocals.T)), rf_sr, model.samplerate)
                rf = np.ascontiguousarray(rf_t.numpy().T)
            else:
                rf = rf_vocals
            n = min(len(rf), len(arr))
            arr = (rf[:n] + arr[:n]).astype(np.float32)
        sf.write(str(out_dir / f"{name}.wav"), arr, model.samplerate, subtype="FLOAT")
    names = stem_names

    done = {"event": "done", "sources": names, "sr": int(model.samplerate),
            "input_sr": int(in_sr), "elapsed_s": round(time.time() - t0, 2),
            "device": device, "passes": passes, "shifts": shifts,
            "overlap": overlap, "model": args.model, "engine": args.engine}
    if hybrid:
        done["vocal_model"] = args.vocal_model
        done["vocal_s"] = vocal_s
    emit(done)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Shimmer stem-separation worker")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="report torch/demucs/CUDA availability as JSON")
    s = sub.add_parser("separate", help="separate one file into stems")
    s.add_argument("input")
    s.add_argument("--model", default="htdemucs",
                   help="a Demucs model name, or several joined with '+' for an ensemble")
    s.add_argument("--shifts", type=int, default=1)
    s.add_argument("--overlap", type=float, default=0.25,
                   help="segment overlap 0.05–0.9; more = fewer seams, slower")
    s.add_argument("--engine", default="demucs", choices=("demucs", "hybrid"),
                   help="demucs: the named model(s) on the mix; hybrid: a RoFormer "
                        "vocal model first, then Demucs on the instrumental")
    s.add_argument("--vocal-model", default="vocals_mel_band_roformer.ckpt",
                   help="audio-separator checkpoint for the hybrid engine's vocal stage")
    s.add_argument("--models-dir", default="",
                   help="where audio-separator keeps its checkpoints")
    s.add_argument("--device", default="auto", choices=("auto", "cuda", "cpu"))
    s.add_argument("--out", required=True)
    args = p.parse_args(argv)
    if args.cmd == "check":
        return cmd_check()
    return cmd_separate(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 — anything unexpected still reaches the app
        emit({"event": "error", "message": f"{type(e).__name__}: {e}"})
        sys.exit(1)
