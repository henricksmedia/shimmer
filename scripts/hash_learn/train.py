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

Loss: L1 between the masked mixture log-magnitude and the clean
log-magnitude over the hash band, plus a penalty on over-suppression. Each
example is normalised by its own mean log-magnitude so level does not
matter.

Usage (under .venv-stems):
    python scripts/hash_learn/train.py --data D:/MusicVault/Tools/Shimmer/hash_data
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

    z = np.load(os.path.join(data, "shard_0.npz"))
    X, Y, band = z["X"], z["Y"], z["band"]
    n = X.shape[0]
    idx = np.random.default_rng(1).permutation(n)
    n_val = max(1, n // 10)
    val, tr = idx[:n_val], idx[n_val:]
    Xt = torch.from_numpy(X); Yt = torch.from_numpy(Y)
    bandt = torch.from_numpy(band.astype(np.float32)).to(dev)[None, None, :, None]

    net = MaskNet().to(dev)
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
        torch.save({"state": net.state_dict(), "band": band, "opt": opt_.state_dict(),
                    "sched": sched.state_dict(), "epoch": ep + 1}, out)
        if (time.time() - t_start) / 60.0 > max_minutes:
            break
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
