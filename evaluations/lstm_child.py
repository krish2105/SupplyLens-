"""W2 child process: fit the small LSTM at every origin for one seed and write the scaled 7-day forecasts.

    python evaluations/lstm_child.py --inputs in.npz --seed S --cfg '{...}' --out pred.npz --info info.json [--repeat-first]

All data preparation happens in evaluations/lstm_study.py; this file only trains and predicts. It is the only W2 code
that imports PyTorch, and it never runs inside pytest's process (D-023). CPU, one thread, deterministic algorithms.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import numpy as np
import torch
from torch import nn


class LSTMForecaster(nn.Module):
    """LSTM over the history window; its last hidden state plus the target days' calendar -> one value per horizon."""

    def __init__(self, n_step: int, n_cal: int, horizon: int, hidden: int = 32, head: int = 64, layers: int = 1,
                 dropout: float = 0.0):
        super().__init__()
        self.lstm = nn.LSTM(n_step, hidden, num_layers=layers, batch_first=True, dropout=dropout if layers > 1 else 0.0)
        self.head = nn.Sequential(nn.Linear(hidden + horizon * n_cal, head), nn.ReLU(), nn.Dropout(dropout),
                                  nn.Linear(head, horizon))

    def forward(self, x: torch.Tensor, cal: torch.Tensor) -> torch.Tensor:
        _, (h, _) = self.lstm(x)
        return self.head(torch.cat([h[-1], cal.flatten(1)], dim=1))


# MSE matches W1 XGBoost's squared-error objective; Huber caps the pull of the few bulk-order days (up to ~5x a normal day).
LOSSES = {"mse": lambda cfg: nn.MSELoss(), "huber": lambda cfg: nn.HuberLoss(delta=cfg["huber_delta"])}


def fit_predict(X, C, Y, Xp, Cp, seed: int, cfg: dict) -> tuple[np.ndarray, dict]:
    torch.manual_seed(seed)
    np.random.seed(seed)
    X, C, Y, Xp, Cp = (torch.from_numpy(np.ascontiguousarray(a, dtype=np.float32)) for a in (X, C, Y, Xp, Cp))
    model = LSTMForecaster(X.shape[2], C.shape[2], Y.shape[1], cfg["hidden"], cfg["head"], cfg["layers"], cfg["dropout"])
    opt = torch.optim.AdamW(model.parameters(), lr=cfg["lr"], weight_decay=cfg["weight_decay"])
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=cfg["epochs"])
    g = torch.Generator().manual_seed(seed)
    loss_fn = LOSSES[cfg["loss"]](cfg)
    n, losses = len(X), []
    for _ in range(cfg["epochs"]):
        model.train()
        perm = torch.randperm(n, generator=g)
        tot = 0.0
        for b in range(0, n, cfg["batch"]):
            idx = perm[b: b + cfg["batch"]]
            loss = loss_fn(model(X[idx], C[idx]), Y[idx])
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), cfg["grad_clip"])
            opt.step()
            tot += loss.item() * len(idx)
        sched.step()
        losses.append(tot / n)
    model.eval()
    with torch.no_grad():
        pred = model(Xp, Cp).numpy()[0]
    return pred, {"samples": n, "first_loss": round(losses[0], 5), "final_loss": round(losses[-1], 5),
                  "params": sum(p.numel() for p in model.parameters())}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--cfg", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--info", required=True)
    ap.add_argument("--repeat-first", action="store_true", help="fit the first origin twice and report the difference")
    ns = ap.parse_args(argv)
    cfg = json.loads(ns.cfg)
    if cfg.get("device", "cpu") != "cpu":
        raise SystemExit("W2 runs on CPU only (determinism)")
    torch.set_num_threads(int(cfg.get("threads", 1)))
    torch.use_deterministic_algorithms(True)
    d = np.load(ns.inputs)
    preds, fits, t0 = [], [], time.time()
    for k in range(int(d["n_origins"])):
        p, info = fit_predict(d[f"X{k}"], d[f"C{k}"], d[f"Y{k}"], d[f"Xp{k}"], d[f"Cp{k}"], ns.seed, cfg)
        preds.append(p)
        fits.append(info)
        print(f"seed {ns.seed} origin {k}: samples={info['samples']} loss {info['first_loss']} -> {info['final_loss']} "
              f"({time.time() - t0:.0f}s)", file=sys.stderr, flush=True)
    meta = {"seed": ns.seed, "torch": torch.__version__, "threads": torch.get_num_threads(), "device": "cpu",
            "params": fits[0]["params"], "fits": fits, "seconds": round(time.time() - t0, 1)}
    if ns.repeat_first:
        again, _ = fit_predict(d["X0"], d["C0"], d["Y0"], d["Xp0"], d["Cp0"], ns.seed, cfg)
        meta["repeat_first_max_abs_diff"] = float(np.max(np.abs(again - preds[0])))
    np.savez(ns.out, pred=np.stack(preds))
    with open(ns.info, "w") as fh:
        fh.write(json.dumps(meta))


if __name__ == "__main__":
    main()
