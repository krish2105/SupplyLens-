"""One-shot local bootstrap: seed control plane, ingest UCI (if downloaded), build the
simulated UCI operations layer, and load the fictional Demo workspace. Idempotent."""
import json
from pathlib import Path

from sqlalchemy import text

from .config import REPO_ROOT
from .db import tenant_session
from .ingest.uci import ingest
from .seed import seed, tenant_id
from .simulation import demo, uci_ops

UCI_ZIP = REPO_ROOT / "data" / "raw" / "core" / "online_retail_ii" / "online_retail_ii.zip"


def main() -> None:
    seed()
    out = {}
    research = tenant_id("uci-research")
    if UCI_ZIP.exists():
        r = ingest(research, UCI_ZIP)
        out["uci_ingest"] = {"dataset_id": r["dataset_id"], "reused": r["reused"], "totals": r["report"]["totals"]}
        report_path = REPO_ROOT / "artifacts" / "reports" / "uci_qualification.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(r["report"], indent=2))
        out["uci_ops"] = uci_ops.build(research, r["dataset_id"])
    else:
        out["uci_ingest"] = "SKIPPED: raw file missing; run scripts/download_datasets.py --dataset online_retail_ii"
    out["demo"] = demo.load(tenant_id("demo"))
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
