"""Compact quantile TCN (PyTorch), run in its own process.

    python -m supplylens_ml.tcn train   --panel p.npz --index I --seed S --cfg '{...}' --model-out m.pt --pred-out y.npy
    python -m supplylens_ml.tcn predict --panel p.npz --index I --model m.pt --pred-out y.npy

LightGBM and PyTorch bundle different OpenMP runtimes; keeping them in separate processes
avoids the duplicate-runtime crash without the unsafe KMP_DUPLICATE_LIB_OK workaround.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import warnings

import numpy as np
import torch
from torch import nn

from .panel import HORIZON, QUANTILES, WINDOW, Panel, load_panel, scale_at

warnings.filterwarnings("ignore", category=RuntimeWarning)


class CausalBlock(nn.Module):
    def __init__(self, ch: int, dilation: int, k: int = 3, dropout: float = 0.1):
        super().__init__()
        self.pad = (k - 1) * dilation
        self.c1 = nn.Conv1d(ch, ch, k, dilation=dilation)
        self.c2 = nn.Conv1d(ch, ch, k, dilation=dilation)
        self.drop = nn.Dropout(dropout)
        self.act = nn.GELU()

    def forward(self, x):
        h = self.act(self.c1(nn.functional.pad(x, (self.pad, 0))))
        h = self.drop(h)
        h = self.act(self.c2(nn.functional.pad(h, (self.pad, 0))))
        return x + self.drop(h)


class QuantileTCN(nn.Module):
    """Causal dilated residual TCN; receptive field 1 + 2*(k-1)*sum(dilations) = 125 >= 56-day window."""

    def __init__(self, in_ch: int = 9, ch: int = 32, dilations=(1, 2, 4, 8, 16), horizon: int = HORIZON,
                 n_q: int = 3, dropout: float = 0.1):
        super().__init__()
        self.inp = nn.Conv1d(in_ch, ch, 1)
        self.blocks = nn.Sequential(*[CausalBlock(ch, d, dropout=dropout) for d in dilations])
        self.head = nn.Sequential(nn.Linear(ch + 7, 64), nn.GELU(), nn.Linear(64, horizon * n_q))
        self.horizon, self.n_q = horizon, n_q

    def forward(self, x, origin_dow):
        h = self.blocks(self.inp(x))[:, :, -1]
        return self.head(torch.cat([h, origin_dow], dim=1)).view(-1, self.horizon, self.n_q)


def tcn_inputs(panel: Panel, i: int):
    """(S, 9, 56): scaled series, log1p(scale), 7 weekday one-hot channels; plus origin weekday one-hot."""
    sc = scale_at(panel, i)
    w = (panel.y[i - WINDOW + 1: i + 1] / sc).T
    S = w.shape[0]
    onehot = np.eye(7)[panel.dates[i - WINDOW + 1: i + 1].dayofweek.to_numpy()].T
    x = np.concatenate([np.nan_to_num(w)[:, None, :], np.repeat(np.log1p(sc)[:, None, None], WINDOW, 2),
                        np.repeat(onehot[None], S, 0)], axis=1)
    od = np.repeat(np.eye(7)[panel.dates[i].dayofweek][None], S, 0)
    return x.astype(np.float32), od.astype(np.float32), sc


def pinball_torch(pred, y):
    return torch.stack([torch.maximum(q * (y - pred[:, :, k]), (q - 1) * (y - pred[:, :, k]))
                        for k, q in enumerate(QUANTILES)]).mean()


def device():
    return torch.device("mps") if torch.backends.mps.is_available() else torch.device("cpu")


def train(panel: Panel, origins: list[int], seed: int, epochs: int = 12, batch: int = 512, lr: float = 2e-3,
          ch: int = 32, dropout: float = 0.1, log=print):
    torch.manual_seed(seed)
    np.random.seed(seed)
    xs, ods, ys = [], [], []
    for i in origins:
        x, od, sc = tcn_inputs(panel, i)
        lab = panel.y[i + 1: i + 1 + HORIZON].T / sc[:, None]
        ok = ~np.isnan(lab).any(1) & ~np.isnan(panel.y[i - WINDOW + 1])
        xs.append(x[ok]); ods.append(od[ok]); ys.append(lab[ok].astype(np.float32))
    X, OD, Y = (torch.from_numpy(np.concatenate(a)) for a in (xs, ods, ys))
    dev = device()
    model = QuantileTCN(ch=ch, dropout=dropout).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    n, t0, history = len(X), time.time(), []
    g = torch.Generator().manual_seed(seed)
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(n, generator=g)
        total = 0.0
        for b in range(0, n, batch):
            idx = perm[b: b + batch]
            loss = pinball_torch(model(X[idx].to(dev), OD[idx].to(dev)), Y[idx].to(dev))
            opt.zero_grad(); loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            total += loss.item() * len(idx)
        sched.step()
        history.append(round(total / n, 5))
        log(f"  tcn seed={seed} epoch {ep + 1}/{epochs} train_pinball={total / n:.4f}")
    info = {"samples": n, "epochs": epochs, "seconds": round(time.time() - t0, 1), "device": str(dev),
            "params": sum(p.numel() for p in model.parameters()), "train_loss": history}
    return model.cpu(), info


@torch.no_grad()
def predict(model: QuantileTCN, panel: Panel, i: int) -> np.ndarray:
    model.eval()
    x, od, sc = tcn_inputs(panel, i)
    return model(torch.from_numpy(x), torch.from_numpy(od)).numpy() * sc[:, None, None]


def load_model(path: str, expected_sha256: str | None = None) -> QuantileTCN:
    """Load only trusted, hash-verified artifacts produced by the training pipeline."""
    raw = open(path, "rb").read()
    if expected_sha256 and hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("model artifact hash mismatch")
    ck = torch.load(path, map_location="cpu", weights_only=True)
    m = QuantileTCN(ch=ck["config"]["ch"], dropout=ck["config"]["dropout"])
    m.load_state_dict(ck["state_dict"])
    return m


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["train", "predict"])
    ap.add_argument("--panel", required=True)
    ap.add_argument("--index", type=int, required=True)
    ap.add_argument("--pred-out", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--cfg", default="{}")
    ap.add_argument("--origins", default="[]")
    ap.add_argument("--model-out")
    ap.add_argument("--model")
    ap.add_argument("--model-sha256")
    ap.add_argument("--info-out")
    ns = ap.parse_args(argv)
    panel = load_panel(ns.panel)
    log = lambda m: print(m, file=sys.stderr, flush=True)  # noqa: E731
    if ns.cmd == "train":
        cfg = json.loads(ns.cfg)
        model, info = train(panel, json.loads(ns.origins), ns.seed, epochs=cfg["epochs"], ch=cfg["ch"],
                            dropout=cfg["dropout"], log=log)
        torch.save({"state_dict": model.state_dict(), "config": {k: cfg[k] for k in ("ch", "dropout", "epochs")},
                    "window": WINDOW, "horizon": HORIZON}, ns.model_out)
        if ns.info_out:
            open(ns.info_out, "w").write(json.dumps(info))
    else:
        model = load_model(ns.model, ns.model_sha256)
    np.save(ns.pred_out, predict(model, panel, ns.index))


if __name__ == "__main__":
    main()
