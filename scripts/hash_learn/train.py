"""
hash_learn/train.py — Train the mask network on the generated pairs, without
taking the machine down.

The first run of this script saturated the GPU and crashed the computer. So
this version treats the card as shared with the desktop and refuses to own
it:

  * memory cap        torch.cuda.set_per_process_memory_fraction(--gpu-mem,
                      default 0.35 of the card, ~4 GB on a 12 GB 4070 Super)
  * small batches     --batch 4 with gradient accumulation to --accum 4, so
                      the effective batch is 16 but activations are a quarter
  * mixed precision   autocast fp16 halves activation memory again
  * duty cycle        after every step, sleep so the GPU is busy at most
                      --duty (default 0.6) of wall time; the desktop keeps
                      its share
  * temperature       every 20 steps read nvidia-smi; above --max-temp
                      (default 80 C) sleep until it drops below it
  * priority          the process runs below normal; torch uses 2 CPU threads
  * checkpoint        every epoch to --out; --resume continues from it
  * wall clock        --max-minutes (default 45) stops the run cleanly
  * GPU lease         on a machine with the GPU lease library
                      (shimmer/gpu_lease_hook.py) it holds the lease while it
                      trains, and gives it back every LEASE_MINUTES so other
                      tools get a turn; nothing changes anywhere else

Loss: L1 between the masked mixture log-magnitude and the clean
log-magnitude over the hash band, plus a penalty on over-suppression. Each
example is normalised by its own mean log-magnitude so level does not
matter.

Usage (under .venv-stems):
    python scripts/hash_learn/train.py --data hash_data
        [--epochs 30] [--out scripts/hash_learn/masknet.pt] [--resume]
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from model import MaskNet   # noqa: E402


def lower_priority():
    try:
        import ctypes
        BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),
                                                BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:  # noqa: BLE001
        try:
            os.nice(10)
        except Exception:  # noqa: BLE001
            pass


LEASE_MINUTES = 25   # give the GPU lease back at least this often (the agreement: 30)


def _lease_hook():
    """shimmer/gpu_lease_hook.py, loaded by its path: this script runs in the
    stems environment, without the shimmer package's dependencies."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.dirname(HERE)), "shimmer", "gpu_lease_hook.py")
    spec = importlib.util.spec_from_file_location("shimmer_gpu_lease_hook", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GpuTurn:
    """The machine-wide GPU lease while training on the GPU; nothing on the
    CPU or without the lease library. Every LEASE_MINUTES it moves the
    network and the optimizer's state off the GPU, gives the lease back so
    other tools get a turn, waits for it again and carries on."""

    def __init__(self, dev: str, vram_gb: float):
        hook = _lease_hook() if dev == "cuda" else None
        self.hook = hook if hook is not None and hook.available() else None
        self.vram_gb, self.lease, self.since = vram_gb, None, 0.0

    def take(self):
        if self.hook is None:
            return
        self.lease = self.hook.gpu_lease("training the hash mask network", self.vram_gb,
                                         on_wait=lambda m: print("  " + m, flush=True))
        self.lease.__enter__()
        self.since = time.time()

    def give_back(self, net=None):
        if self.lease is None:
            return
        if net is not None:
            net.to("cpu")
        torch.cuda.empty_cache()
        lease, self.lease = self.lease, None
        lease.__exit__(None, None, None)

    def due(self) -> bool:
        return self.lease is not None and time.time() - self.since > LEASE_MINUTES * 60

    def pause(self, net, opt):
        """Off the GPU, lease back, wait for a turn, back on the GPU."""
        print("  giving the GPU lease back for a turn", flush=True)
        moved = []
        for st in opt.state.values():
            for k, v in st.items():
                if torch.is_tensor(v) and v.is_cuda:
                    st[k] = v.to("cpu")
                    moved.append((st, k))
        self.give_back(net)
        self.take()
        net.to("cuda")
        for st, k in moved:
            st[k] = st[k].to("cuda")


def gpu_temp() -> float:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=5)
        return float(out.stdout.strip().splitlines()[0])
    except Exception:  # noqa: BLE001
        return 0.0


def main(argv):
    def opt(k, d=None):
        return argv[argv.index(k) + 1] if k in argv else d
    data = opt("--data")
    epochs = int(opt("--epochs", 30))
    batch = int(opt("--batch", 4))
    accum = int(opt("--accum", 4))
    duty = float(opt("--duty", 0.6))
    max_temp = float(opt("--max-temp", 80.0))
    gpu_mem = float(opt("--gpu-mem", 0.35))
    max_minutes = float(opt("--max-minutes", 45))
    out = opt("--out", os.path.join(HERE, "masknet.pt"))
    resume = "--resume" in argv

    lower_priority()
    torch.set_num_threads(2)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    if dev == "cuda":
        torch.cuda.set_per_process_memory_fraction(gpu_mem, 0)
        torch.backends.cudnn.benchmark = False
    total_gb = torch.cuda.get_device_properties(0).total_memory / 1e9 if dev == "cuda" else 0.0
    turn = GpuTurn(dev, round(gpu_mem * total_gb, 1))
    turn.take()
    try:
        return _train(dev, turn, data, epochs, batch, accum, duty, max_temp, gpu_mem,
                      max_minutes, out, resume)
    finally:
        turn.give_back(_NET[0] if _NET else None)


_NET: list = []   # the network, so a failed run still moves it off the GPU


def _train(dev, turn, data, epochs, batch, accum, duty, max_temp, gpu_mem, max_minutes, out, resume):

    z = np.load(os.path.join(data, "shard_0.npz"))
    X, Y, band = z["X"], z["Y"], z["band"]
    ctx_hz = z["ctx_hz"] if "ctx_hz" in z.files else np.array([2000.0, 16000.0])
    band_hz = z["band_hz"] if "band_hz" in z.files else np.array([4500.0, 12000.0])
    n = X.shape[0]
    idx = np.random.default_rng(1).permutation(n)
    n_val = max(1, n // 10)
    val, tr = idx[:n_val], idx[n_val:]
    Xt = torch.from_numpy(X); Yt = torch.from_numpy(Y)
    bandt = torch.from_numpy(band.astype(np.float32)).to(dev)[None, None, :, None]

    net = MaskNet().to(dev)
    _NET.append(net)
    opt_ = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt_, T_max=epochs)
    scaler = torch.amp.GradScaler("cuda", enabled=(dev == "cuda"))
    start_ep = 0
    if resume and os.path.exists(out):
        ck = torch.load(out, map_location="cpu")
        net.load_state_dict(ck["state"])
        if "opt" in ck:
            opt_.load_state_dict(ck["opt"]); sched.load_state_dict(ck["sched"])
            start_ep = int(ck.get("epoch", 0))
        print(f"resumed from epoch {start_ep}")
    print(f"{n} pairs ({len(tr)} train / {n_val} val), {sum(p.numel() for p in net.parameters())} params, "
          f"{dev}, batch {batch} x accum {accum}, gpu mem cap {gpu_mem:.2f}, duty {duty:.2f}, "
          f"max temp {max_temp:.0f} C, max {max_minutes:.0f} min", flush=True)

    def losses(ix):
        x = Xt[ix].to(dev).float()[:, None]; y = Yt[ix].to(dev).float()[:, None]
        mu = x.mean(dim=(2, 3), keepdim=True)
        with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=(dev == "cuda")):
            g = net(x - mu)
        g = g.float() * bandt + (1.0 - bandt)
        yhat = x + torch.log(g + 1e-6)
        loss_band = ((yhat - y).abs() * bandt).sum() / (bandt.sum() * x.shape[0] * x.shape[3])
        over = torch.relu(y - yhat) * bandt
        return loss_band + 0.5 * over.mean()

    t_start = time.time()
    step_n = 0
    for ep in range(start_ep, epochs):
        net.train(); t0 = time.time(); tl = []
        perm = np.random.default_rng(ep).permutation(tr)
        opt_.zero_grad(set_to_none=True)
        for i in range(0, len(perm), batch):
            ts = time.time()
            loss = losses(perm[i:i + batch]) / accum
            scaler.scale(loss).backward()
            tl.append(float(loss) * accum)
            if ((i // batch) + 1) % accum == 0:
                scaler.step(opt_); scaler.update(); opt_.zero_grad(set_to_none=True)
                if turn.due():
                    turn.pause(net, opt_)
            if dev == "cuda":
                torch.cuda.synchronize()
            busy = time.time() - ts
            time.sleep(max(0.0, busy * (1.0 - duty) / max(duty, 0.05)))   # duty cycle
            step_n += 1
            if step_n % 50 == 0:
                print(f"  step {step_n} loss {np.mean(tl[-50:]):.4f} {time.strftime('%H:%M:%S')}", flush=True)
            if step_n % 20 == 0:
                while (t := gpu_temp()) > max_temp:
                    print(f"  gpu {t:.0f} C > {max_temp:.0f}: cooling", flush=True)
                    time.sleep(5.0)
            if (time.time() - t_start) / 60.0 > max_minutes:
                print("wall-clock limit reached; stopping after this epoch's checkpoint", flush=True)
                break
        net.eval(); vl = []
        with torch.no_grad():
            for i in range(0, len(val), batch):
                vl.append(float(losses(val[i:i + batch])))
        sched.step()
        peak = torch.cuda.max_memory_allocated() / 1e9 if dev == "cuda" else 0.0
        print(f"epoch {ep + 1:3d} train {np.mean(tl):.4f} val {np.mean(vl):.4f} "
              f"{time.time() - t0:.0f}s peak gpu {peak:.2f} GB temp {gpu_temp():.0f} C", flush=True)
        torch.save({"state": net.state_dict(), "band": band, "ctx_hz": ctx_hz, "band_hz": band_hz,
                    "opt": opt_.state_dict(), "sched": sched.state_dict(), "epoch": ep + 1}, out)
        if (time.time() - t_start) / 60.0 > max_minutes:
            break
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
