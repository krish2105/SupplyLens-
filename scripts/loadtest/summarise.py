"""Print a compact table from one or more loadtest-*.json reports."""
import json
import sys


def r(x):
    return "-" if x is None else f"{x:,.0f}"


for path in sys.argv[1:]:
    d = json.load(open(path))
    res = d["result"]
    print(f"\n## {path}  [{d['phase']}: {d['condition']}]")
    if d["phase"] == "interactive":
        print(f"duration {res['seconds']}s | host {d['host']['vcpus']} vCPU, {d['host']['mem_total']}")
        for name in ("metadata_reads", "retrieval"):
            x = res[name]
            print(f"{name:15s} n={x['n']:5d} failed={x['failed']:4d} rps={x['rps']:5.2f} p50={r(x['p50_ms'])} p95={r(x['p95_ms'])} p99={r(x['p99_ms'])} max={r(x['max_ms'])} ms  codes={x['status_codes']}")
        for k, x in res["per_endpoint"].items():
            print(f"   {k:34s} n={x['n']:4d} p50={r(x['p50_ms']):>6} p95={r(x['p95_ms']):>6} p99={r(x['p99_ms']):>6}  failed={x['failed']}")
        print("resources:", res["resources"])
    else:
        print(json.dumps(res, indent=1))
