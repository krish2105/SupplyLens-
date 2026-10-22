"""Aggregate the per-page lab measurements written by apps/web/e2e/vitals.spec.ts into artifacts/reports/webvitals-lab.json
and print a markdown table.   uv run python scripts/summarise_vitals.py"""
import glob
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
rows = [json.loads(Path(f).read_text()) for f in sorted(glob.glob(str(REPO / "artifacts/reports/webvitals/*.json")))]
conditions = {
    "desktop": "Chromium headless 1440x900, no throttling, loopback network, production build, one run per page",
    "mobile": "Chromium headless phone viewport, 4x CPU slowdown, 150 ms RTT, 1.6 Mbps down / 750 kbps up (Lighthouse-style slow 4G), "
              "production build, one run per page",
}
doc = {"targets_field_p75": {"lcp_ms": 2500, "inp_ms": 200, "cls": 0.1}, "kind": "laboratory measurement, not field data",
       "conditions": conditions, "results": rows}
(REPO / "artifacts/reports/webvitals-lab.json").write_text(json.dumps(doc, indent=2))
print("| profile | page | LCP (ms) | INP proxy (ms) | CLS |\n|---|---|---:|---:|---:|")
for r in sorted(rows, key=lambda r: (r["profile"], r["path"])):
    print(f"| {r['profile']} | {r['path']} | {r['lcp_ms']} | {r['inp_ms']} | {r['cls']} |")
