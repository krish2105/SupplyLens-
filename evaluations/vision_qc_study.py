"""QC1: visual quality control at goods-in with a convolutional network (week-9 style defect vs non-defect classifier).

Goods-in inspection: a camera photographs each received item's surface (a glazed ceramic gift, typical of the UCI
catalogue) and a model flags defects for a person to check. No labelled photo set of these products exists, so the images
are GENERATED from stated rules: 64x64 greyscale surfaces with glaze texture, a printed pattern, uneven lighting, small
rotations and sensor noise; 30 % carry one defect: a scratch (thin bright line), a chip (dark notch at the rim) or a stain
(soft dark blob), at random size, position and contrast, some faint on purpose.
Models: a baseline (logistic regression on hand-made features: intensity and edge statistics) and a small CNN (PyTorch).
Reported on a held-out set: AUC, precision and recall, recall by defect type, an occlusion map of where the CNN looks, and
an inspection policy: inspect everything by hand, or let the model pass items and have a person check what it flags.
All costs are ASSUMED. Read the accuracy as a method check on generated images, not as performance on real photographs.

uv run python evaluations/vision_qc_study.py
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import numpy as np

from supplylens.config import REPO_ROOT

SEED = 9
SIZE = 64
N_TRAIN, N_VAL, N_TEST = 6000, 1500, 3000
DEFECT_RATE = 0.30
KINDS = ("scratch", "chip", "stain")
COST_MANUAL = 0.30        # ASSUMED: a person inspects one item (GBP)
COST_ESCAPE = 12.0        # ASSUMED: a defective item reaches a customer (return, replacement, goodwill)
COST_FALSE = 0.30         # ASSUMED: a good item flagged and re-checked by hand


def surface(rng):
    yy, xx = np.mgrid[0:SIZE, 0:SIZE] / SIZE
    a = rng.uniform(0, np.pi)
    light = 0.55 + 0.18 * (np.cos(a) * (xx - 0.5) + np.sin(a) * (yy - 0.5)) * rng.uniform(0.5, 1.5)
    k = rng.uniform(6, 10)
    phase = rng.uniform(0, 2 * np.pi)
    pattern = 0.06 * np.sin(k * 2 * np.pi * (np.cos(a / 3) * xx + np.sin(a / 3) * yy) + phase)    # printed band
    glaze = rng.normal(0, 0.025, (SIZE, SIZE))
    glaze = (glaze + np.roll(glaze, 1, 0) + np.roll(glaze, 1, 1)) / 3
    return light + pattern + glaze


def add_defect(img, rng, kind):
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    strength = rng.uniform(0.12, 0.35)                    # some defects are faint on purpose
    if kind == "scratch":
        x0, y0 = rng.uniform(8, 56, 2)
        ang, length = rng.uniform(0, np.pi), rng.uniform(10, 30)
        dx, dy = np.cos(ang), np.sin(ang)
        t = np.clip((xx - x0) * dx + (yy - y0) * dy, 0, length)
        d = np.hypot(xx - (x0 + t * dx), yy - (y0 + t * dy))
        img = img + strength * np.exp(-(d / rng.uniform(0.5, 1.0)) ** 2)
    elif kind == "chip":
        side = rng.integers(4)
        c = rng.uniform(10, 54)
        cx, cy = [(c, 0), (c, SIZE - 1), (0, c), (SIZE - 1, c)][side]
        r = rng.uniform(3, 7)
        img = img - strength * 1.6 * (np.hypot(xx - cx, yy - cy) < r)
    else:
        cx, cy = rng.uniform(10, 54, 2)
        r = rng.uniform(4, 10)
        img = img - strength * 0.8 * np.exp(-(np.hypot(xx - cx, yy - cy) / r) ** 2)
    return img


def dataset(rng, n):
    X = np.empty((n, SIZE, SIZE), dtype=np.float32)
    y = np.zeros(n, dtype=np.float32)
    kind = np.array(["none"] * n, dtype=object)
    for i in range(n):
        img = surface(rng)
        if rng.random() < DEFECT_RATE:
            kind[i] = KINDS[rng.integers(3)]
            img = add_defect(img, rng, kind[i])
            y[i] = 1
        img = img + rng.normal(0, 0.02, img.shape)        # sensor noise
        X[i] = np.clip(img, 0, 1)
    return X, y, kind


def handmade(X):
    gx, gy = np.abs(np.diff(X, axis=2))[:, :-1, :], np.abs(np.diff(X, axis=1))[:, :, :-1]
    g = gx + gy
    flat = X.reshape(len(X), -1)
    rim = np.concatenate([X[:, :4, :].reshape(len(X), -1), X[:, -4:, :].reshape(len(X), -1),
                          X[:, :, :4].reshape(len(X), -1), X[:, :, -4:].reshape(len(X), -1)], 1)
    return np.c_[flat.mean(1), flat.std(1), np.percentile(flat, 1, axis=1), np.percentile(flat, 99, axis=1),
                 g.reshape(len(X), -1).mean(1), g.reshape(len(X), -1).std(1), np.percentile(g.reshape(len(X), -1), 99.5, axis=1),
                 rim.min(1), rim.std(1)]


def logistic(Ftr, ytr):
    mu, sd = Ftr.mean(0), Ftr.std(0) + 1e-9
    A = np.c_[np.ones(len(Ftr)), (Ftr - mu) / sd]
    w = np.zeros(A.shape[1])
    for _ in range(4000):
        p = 1 / (1 + np.exp(-(A @ w)))
        w -= 0.3 * (A.T @ (p - ytr) / len(ytr) + 1e-3 * np.r_[0, w[1:]])
    return lambda F: 1 / (1 + np.exp(-(np.c_[np.ones(len(F)), (F - mu) / sd] @ w)))


def auc(y, p):
    order = np.argsort(p)
    ranks = np.empty(len(p))
    ranks[order] = np.arange(1, len(p) + 1)
    pos = y == 1
    return float((ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * (~pos).sum()))


def cnn_model():
    from torch import nn
    return nn.Sequential(nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
                         nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
                         nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(), nn.AdaptiveMaxPool2d(1), nn.Flatten(),
                         nn.Linear(64, 32), nn.ReLU(), nn.Linear(32, 1))


def train_cnn(Xtr, ytr):
    import torch
    from torch import nn
    torch.manual_seed(SEED)
    model = cnn_model()
    opt = torch.optim.Adam(model.parameters(), lr=2e-3)
    Xt, yt = torch.tensor(Xtr[:, None]), torch.tensor(ytr)
    g = torch.Generator().manual_seed(SEED)
    for _epoch in range(12):
        perm = torch.randperm(len(Xt), generator=g)
        for i in range(0, len(Xt), 128):
            b = perm[i:i + 128]
            xb = Xt[b]
            if _epoch % 2:                                       # flips: a defect is a defect whichever way up
                xb = torch.flip(xb, dims=[3])
            opt.zero_grad()
            loss = nn.functional.binary_cross_entropy_with_logits(model(xb).squeeze(-1), yt[b])
            loss.backward()
            opt.step()
    model.eval()

    def predict(X):
        with torch.no_grad():
            out = []
            for i in range(0, len(X), 512):
                out.append(torch.sigmoid(model(torch.tensor(X[i:i + 512, None]))).squeeze(-1).numpy())
            return np.concatenate(out)
    return predict


def occlusion(predict, img, patch=8):
    base = predict(img[None])[0]
    heat = np.zeros((SIZE // patch, SIZE // patch))
    for i in range(0, SIZE, patch):
        for j in range(0, SIZE, patch):
            x = img.copy()
            x[i:i + patch, j:j + patch] = np.median(img)
            heat[i // patch, j // patch] = base - predict(x[None])[0]
    return heat


def cost_policy(y, p, t):
    flag = p >= t
    escapes = int(np.sum((~flag) & (y == 1)))
    false = int(np.sum(flag & (y == 0)))
    return {"threshold": round(float(t), 4), "flagged": int(flag.sum()), "escaped_defects": escapes, "false_flags": false,
            "recall": round(float(np.sum(flag & (y == 1)) / max(1, y.sum())), 4),
            "precision": round(float(np.sum(flag & (y == 1)) / max(1, flag.sum())), 4),
            "cost_gbp": round(COST_MANUAL * flag.sum() + COST_ESCAPE * escapes, 2)}


def best_threshold(y, p):
    ts = np.unique(np.round(p, 4))
    costs = [COST_MANUAL * np.sum(p >= t) + COST_ESCAPE * np.sum((p < t) & (y == 1)) for t in ts]
    return float(ts[int(np.argmin(costs))])


def main() -> None:
    rng = np.random.default_rng(SEED)
    Xtr, ytr, _ = dataset(rng, N_TRAIN)
    Xva, yva, _ = dataset(rng, N_VAL)
    Xte, yte, kte = dataset(rng, N_TEST)
    base = logistic(handmade(Xtr), ytr)
    cnn = train_cnn(Xtr, ytr)
    preds = {"handmade_features_logistic": (base(handmade(Xva)), base(handmade(Xte))), "cnn": (cnn(Xva), cnn(Xte))}
    models = {}
    for name, (pva, pte) in preds.items():
        t = best_threshold(yva, pva)
        at05 = pte >= 0.5
        models[name] = {"auc": round(auc(yte, pte), 4),
                        "accuracy_at_0_5": round(float(np.mean(at05 == (yte == 1))), 4),
                        "recall_by_kind_at_cost_threshold": {k: round(float(np.mean(pte[kte == k] >= t)), 3) for k in KINDS},
                        "false_flag_rate_good_items": round(float(np.mean(pte[kte == "none"] >= t)), 4),
                        "policy": cost_policy(yte, pte, t)}
        print(name, models[name])
    manual_all = round(COST_MANUAL * N_TEST, 2)
    # where the CNN looks: occlusion maps for one example of each defect type
    examples, heat = [], []
    for k in KINDS:
        i = int(np.where(kte == k)[0][0])
        examples.append(Xte[i])
        heat.append(occlusion(cnn, Xte[i]))
    i = int(np.where(kte == "none")[0][0])
    examples.append(Xte[i])
    heat.append(occlusion(cnn, Xte[i]))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = REPO_ROOT / "artifacts" / "experiments" / f"QC1-{stamp}"
    out.mkdir(parents=True)
    np.savez_compressed(out / "examples.npz", images=np.array(examples, dtype=np.float16), occlusion=np.array(heat, dtype=np.float16),
                        kinds=np.array(list(KINDS) + ["none"]))
    metrics = {"experiment_id": out.name, "study": "QC1", "kind": "simulated images",
               "question": "Can a small CNN flag surface defects at goods-in well enough to replace inspecting every item by hand?",
               "data": {"train": N_TRAIN, "validation": N_VAL, "test": N_TEST, "defect_rate": DEFECT_RATE, "image": f"{SIZE}x{SIZE} greyscale",
                        "test_defects": int(yte.sum()), "test_by_kind": {k: int(np.sum(kte == k)) for k in KINDS}},
               "models": models, "inspect_everything_cost_gbp": manual_all,
               "costs_assumed": {"manual_inspection_gbp": COST_MANUAL, "escaped_defect_gbp": COST_ESCAPE, "false_flag_gbp": COST_FALSE},
               "occlusion_examples": "examples.npz (one image per defect type and one good item, with 8x8 occlusion maps)",
               "seed": SEED,
               "limits": ["images are generated from stated rules, not photographs; real lighting, glare and product variety are harder",
                          "one defect per image; no multi-defect or mislabelled images", "costs are assumed"]}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str))
    print(json.dumps({"inspect_everything_cost_gbp": manual_all, "models": {k: v["policy"] for k, v in models.items()}}, indent=1))
    print(out.name)


if __name__ == "__main__":
    main()
