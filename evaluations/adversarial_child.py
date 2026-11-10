"""B1 child process: adversarial debiasing in PyTorch (Zhang, Lemoine & Mitchell, 2018), run apart from LightGBM (D-023).

The predictor is a logistic regression (one linear layer) trained with balanced class weights. The adversary sees the
predictor's output and the true label, as in the paper's equality-of-odds set-up: inputs [s, s*y, s*(1-y)] with
s = sigmoid((1 + |c|) * logit), and tries to recover the machine Type (3 classes). Each predictor step uses the paper's
update, per parameter tensor:  grad_P - proj_{grad_A} grad_P - alpha * grad_A, so the predictor never moves in a
direction that helps the adversary. "off" trains the same predictor and adversary, but the adversary does not touch the
predictor (the before case).

After training, a fresh probe (multinomial logistic regression on [z, z*y, y], z = standardised logit) is fitted on the
validation rows and scored on test: how much Type can still be read from the output given the label.

usage (called by evaluations/imbalance_study.py; never imported by pytest):
    python evaluations/adversarial_child.py IN.npz OUT.npz \
        '{"seeds": [0, 1, 2], "alphas": [0.01, 0.1], "steps": 3000, "lr": 0.05, "lr_final": 0.0005, "C": 1.0}'
IN.npz holds X (rows x features), y (0/1), g (group code 0..k-1), tr, va, te (row indices).
OUT.npz receives p_va and p_te with shape (configs, seeds, rows); configs are "off" followed by each alpha.
One JSON line on stdout: torch version, configs, probe results, seconds.
"""
from __future__ import annotations

import json
import sys
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F


def adversary_inputs(logit, y, c):
    s = torch.sigmoid((1 + torch.abs(c)) * logit)
    return torch.stack([s, s * y, s * (1 - y)], 1)


def train(X, y, g, n_groups, seed, alpha, debias, cfg):
    """Full-batch Adam with exponential learning-rate decay. Full batch because mini-batches (about 8 failures each)
    left the plain predictor short of scikit-learn's optimum; with the adversary off this converges to it."""
    torch.manual_seed(seed)                                   # the seed sets the initial weights of both networks
    pred = nn.Linear(X.shape[1], 1)
    adv = nn.Linear(3, n_groups)
    c = nn.Parameter(torch.ones(1))
    p_params, a_params = list(pred.parameters()), [c, *adv.parameters()]
    opt_p = torch.optim.Adam(p_params, lr=cfg["lr"])
    opt_a = torch.optim.Adam(a_params, lr=cfg["lr"])
    gamma = (cfg["lr_final"] / cfg["lr"]) ** (1 / cfg["steps"])
    sched = [torch.optim.lr_scheduler.ExponentialLR(o, gamma=gamma) for o in (opt_p, opt_a)]
    n_pos = float(y.sum())
    w = torch.where(y == 1, len(y) / (2 * n_pos), len(y) / (2 * (len(y) - n_pos)))      # balanced class weights
    l2 = 1.0 / (cfg["C"] * len(y))                            # scikit-learn's L2 at C, on the per-row mean loss
    for _step in range(cfg["steps"]):
        logit = pred(X).squeeze(-1)
        lp = (w * F.binary_cross_entropy_with_logits(logit, y, reduction="none")).mean() + 0.5 * l2 * (pred.weight ** 2).sum()
        la = F.cross_entropy(adv(adversary_inputs(logit, y, c)), g)
        gp = torch.autograd.grad(lp, p_params, retain_graph=True)
        ga = torch.autograd.grad(la, p_params + a_params)
        for prm, gpi, gai in zip(p_params, gp, ga[:len(p_params)], strict=True):
            if debias:                                        # Zhang et al.: drop the part of the step that helps the adversary
                unit = gai / (gai.norm() + 1e-12)
                prm.grad = gpi - (gpi * unit).sum() * unit - alpha * gai
            else:
                prm.grad = gpi
        for prm, gai in zip(a_params, ga[len(p_params):], strict=True):
            prm.grad = gai
        opt_p.step()
        opt_a.step()
        for s in sched:
            s.step()
    return pred


def probe(z_va, y_va, g_va, z_te, y_te, g_te, n_groups):
    """Fit Type from (output, label) on validation, score on test. Returns balanced accuracy and log-loss vs the prior."""
    mu, sd = z_va.mean(), z_va.std() + 1e-9
    feats = lambda z, yy: torch.stack([(z - mu) / sd, (z - mu) / sd * yy, yy], 1)  # noqa: E731
    A_va, A_te = feats(z_va, y_va), feats(z_te, y_te)
    lin = nn.Linear(3, n_groups)
    opt = torch.optim.LBFGS(lin.parameters(), max_iter=200)

    def closure():
        opt.zero_grad()
        loss = F.cross_entropy(lin(A_va), g_va)
        loss.backward()
        return loss
    opt.step(closure)
    with torch.no_grad():
        logp = F.log_softmax(lin(A_te), 1)
        guess = logp.argmax(1)
    recalls = [float((guess[g_te == k] == k).float().mean()) for k in range(n_groups) if (g_te == k).any()]
    prior = torch.bincount(g_va, minlength=n_groups).float() / len(g_va)
    return {"balanced_accuracy": round(float(np.mean(recalls)), 4), "chance": round(1 / n_groups, 4),
            "log_loss": round(float(-logp[torch.arange(len(g_te)), g_te].mean()), 4),
            "prior_log_loss": round(float(-torch.log(prior[g_te]).mean()), 4)}


def main() -> None:
    t0 = time.perf_counter()
    src, dst, cfg = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
    torch.set_num_threads(1)
    d = np.load(src)
    X, y, g = d["X"].astype(np.float32), d["y"].astype(np.float32), d["g"].astype(np.int64)
    tr, va, te = d["tr"], d["va"], d["te"]
    mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-9                  # standardised with training statistics only
    T = lambda idx: torch.tensor((X[idx] - mu) / sd)  # noqa: E731
    Xtr, Xva, Xte = T(tr), T(va), T(te)
    ytr, yva, yte = (torch.tensor(y[i]) for i in (tr, va, te))
    gtr, gva, gte = (torch.tensor(g[i]) for i in (tr, va, te))
    n_groups = int(g.max()) + 1
    configs = [("off", 0.0, False)] + [(f"alpha_{a}", float(a), True) for a in cfg["alphas"]]
    p_va = np.zeros((len(configs), len(cfg["seeds"]), len(va)))
    p_te = np.zeros((len(configs), len(cfg["seeds"]), len(te)))
    probes = {}
    for ci, (name, alpha, debias) in enumerate(configs):
        probes[name] = []
        for si, seed in enumerate(cfg["seeds"]):
            pred = train(Xtr, ytr, gtr, n_groups, seed, alpha, debias, cfg)
            with torch.no_grad():
                z_va, z_te = pred(Xva).squeeze(-1), pred(Xte).squeeze(-1)
            p_va[ci, si], p_te[ci, si] = torch.sigmoid(z_va).numpy(), torch.sigmoid(z_te).numpy()
            probes[name].append(probe(z_va, yva, gva, z_te, yte, gte, n_groups))
    np.savez(dst, p_va=p_va, p_te=p_te)
    print(json.dumps({"torch": torch.__version__, "configs": [c[0] for c in configs], "alphas": [c[1] for c in configs],
                      "probe": probes, "seconds": round(time.perf_counter() - t0, 1)}))


if __name__ == "__main__":
    main()
