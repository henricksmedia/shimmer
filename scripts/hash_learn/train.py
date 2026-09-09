"""
hash_learn/train.py — Train the mask network on the generated pairs.

Loss: L1 between the masked mixture log-magnitude and the clean
log-magnitude over the hash band, plus a small penalty on gain below 1
outside it (the network should leave the rest alone). Each example is
normalised by its own mean log-magnitude so level does not matter.

Usage (under .venv-stems):
    python scripts/hash_learn/train.py --data D:/MusicVault/Tools/Shimmer/hash_data
        [--epochs 30] [--batch 16] [--out scripts/hash_learn/masknet.pt]
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from model import MaskNet   # noqa: E402


def main(argv):
    def opt(k, d=None):
        return argv[argv.index(k) + 1] if k in argv else d
    data = opt("--data")
    epochs = int(opt("--epochs", 30))
    batch = int(opt("--batch", 16))
    out = opt("--out", os.path.join(HERE, "masknet.pt"))
    dev = "cuda" if torch.cuda.is_available() else "cpu"
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
    print(f"{n} pairs ({len(tr)} train / {n_val} val), {sum(p.numel() for p in net.parameters())} params, {dev}")

    def step(ix, train=True):
        x = Xt[ix].to(dev).float()[:, None]; y = Yt[ix].to(dev).float()[:, None]
        mu = x.mean(dim=(2, 3), keepdim=True)
        g = net(x - mu)
        g = g * bandt + (1.0 - bandt)                  # outside the band the gain is 1
        yhat = x + torch.log(g + 1e-6)                 # log-magnitude after masking
        loss_band = ((yhat - y).abs() * bandt).sum() / (bandt.sum() * x.shape[0] * x.shape[3])
        # never amplify, and do not drop below the clean target: penalise
        # over-suppression more than under-suppression
        over = torch.relu(y - yhat) * bandt
        loss = loss_band + 0.5 * over.mean()
        if train:
            opt_.zero_grad(); loss.backward(); opt_.step()
        return float(loss)

    for ep in range(epochs):
        net.train(); t0 = time.time(); tl = []
        perm = np.random.default_rng(ep).permutation(tr)
        for i in range(0, len(perm), batch):
            tl.append(step(perm[i:i + batch]))
        net.eval(); vl = []
        with torch.no_grad():
            for i in range(0, len(val), batch):
                vl.append(step(val[i:i + batch], train=False))
        sched.step()
        print(f"epoch {ep + 1:3d} train {np.mean(tl):.4f} val {np.mean(vl):.4f} {time.time() - t0:.0f}s", flush=True)
    torch.save({"state": net.state_dict(), "band": band}, out)
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
