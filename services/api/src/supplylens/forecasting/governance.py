"""Model governance: the evaluation gate a forecaster must pass before it may become CHAMPION (Phase 5, MLOps).

Promotion stays an audited administrative decision (D-031); this gate makes it evidence-bound. A trained model may be
promoted only when its own recorded evaluation shows that, on the VALIDATION origins of the same experiment, it beat the
seasonal-naive baseline in mean pinball loss; its recorded 80% interval coverage and raw quantile crossing are within
sanity bounds; and every registered artifact is present on this host with its registered hash. Selection never reads
test-window results (the coverage bound is a sanity check, not a tuning target).
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import text

from ..config import REPO_ROOT

COVERAGE_BOUNDS = (0.65, 0.95)      # recorded 80% interval coverage outside this is a broken interval, not a choice
MAX_CROSSING = 0.20                 # raw quantile crossing above this means the quantile heads disagree badly


def promotion_problems(s, model: dict) -> list[str]:
    """Reasons `model` (a model_versions row with family, metrics, artifact_path, artifact_sha256) may not be CHAMPION.
    `s` is a tenant session. An empty list means the gate passes."""
    if model["family"] == "seasonal_naive":
        return []                                   # the baseline rule needs no evidence beyond itself
    m = model.get("metrics") or {}
    problems = []
    exp = m.get("experiment_id")
    if not exp:
        return ["no recorded evaluation (metrics.experiment_id)"]
    if "smoke" in exp:
        problems.append(f"{exp} is a smoke run, not a research result")
    base = s.execute(text("""SELECT metrics FROM model_versions WHERE family = 'seasonal_naive'
        AND metrics->>'experiment_id' = :e ORDER BY created_at DESC LIMIT 1"""), {"e": exp}).scalar()
    own, ref = m.get("validation_pinball"), (base or {}).get("validation_pinball")
    if own is None or ref is None:
        problems.append("validation pinball of the model or of the same experiment's seasonal-naive baseline is missing")
    elif not own < ref:
        problems.append(f"validation pinball {own:.4f} does not beat the seasonal-naive baseline {ref:.4f}")
    cov = m.get("coverage_80")
    if cov is None or not COVERAGE_BOUNDS[0] <= cov <= COVERAGE_BOUNDS[1]:
        problems.append(f"recorded 80% interval coverage {cov} is outside {COVERAGE_BOUNDS}")
    cross = m.get("crossing_rate_raw")
    if cross is not None and cross > MAX_CROSSING:
        problems.append(f"raw quantile crossing {cross:.1%} exceeds {MAX_CROSSING:.0%}")
    arts = model.get("artifact_sha256")
    arts = json.loads(arts) if isinstance(arts, str) else (arts or [])
    if not arts or not model.get("artifact_path"):
        problems.append("no registered artifacts")
    for a in arts:
        f = REPO_ROOT / model["artifact_path"] / a["file"]
        if not f.exists():
            problems.append(f"artifact {a['file']} is not on this host")
        elif hashlib.sha256(f.read_bytes()).hexdigest() != a["sha256"]:
            problems.append(f"artifact {a['file']} does not match its registered hash")
    return problems
