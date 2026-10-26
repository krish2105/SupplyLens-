"""Link every acceptance criterion to the CI run that exercised it (audit S19).

Reads docs/acceptance/acceptance_register.csv, takes the test files each row cites as evidence (tests/*.py,
apps/web/e2e/*.spec.ts, optionally narrowed to ::test names), and looks their outcomes up in this run's results:
pytest JUnit XML and the Playwright JSON report. Writes artifacts/reports/acceptance_evidence.json and .md stamped with
the commit, run id and run URL, so each claim points at an immutable CI artifact rather than at a remembered result.

uv run python scripts/acceptance_evidence.py --junit <pytest-junit.xml> --playwright <e2e-results.json> [<more.json> ...]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REF = re.compile(r"(tests/[\w/]+\.py|apps/web/e2e/[\w.-]+\.spec\.ts|e2e/[\w.-]+\.spec\.ts)(?:::([\w\[\]-]+))?")


def pytest_results(path: Path | None) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = defaultdict(dict)
    if not path or not path.exists():
        return out
    for case in ET.parse(path).iter("testcase"):  # noqa: S314 - JUnit XML written by this CI run's own pytest
        file = "tests/" + case.get("classname", "").split(".")[-1] + ".py"
        state = "failed" if case.find("failure") is not None or case.find("error") is not None else (
            "skipped" if case.find("skipped") is not None else "passed")
        out[file][case.get("name", "")] = state
    return out


def playwright_results(path: Path | None) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = defaultdict(dict)
    if not path or not path.exists():
        return out

    def walk(suite, file):
        file = suite.get("file") or file
        for spec in suite.get("specs", []):
            states = [r.get("status") for t in spec.get("tests", []) for r in t.get("results", [])]
            state = "failed" if any(s in ("failed", "timedOut") for s in states) else (
                "passed" if "passed" in states else "skipped")
            out["apps/web/e2e/" + Path(file).name][spec.get("title", "")] = state
        for s in suite.get("suites", []):
            walk(s, file)
    for s in json.loads(path.read_text()).get("suites", []):
        walk(s, s.get("file", ""))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--junit", type=Path)
    ap.add_argument("--playwright", type=Path, nargs="*", default=[])   # main suites + lab vitals (own CI step)
    a = ap.parse_args()
    results = pytest_results(a.junit)
    for f in a.playwright:
        for file, tests in playwright_results(f).items():
            results.setdefault(file, {}).update(tests)
    sha = os.environ.get("GITHUB_SHA") or subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                                                          cwd=ROOT).stdout.strip()
    run_id = os.environ.get("GITHUB_RUN_ID")
    run_url = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/"
               f"{run_id}") if run_id and os.environ.get("GITHUB_REPOSITORY") else None
    rows = []
    for r in csv.DictReader((ROOT / "docs/acceptance/acceptance_register.csv").open()):
        cited = REF.findall(" ".join(r.get(k) or "" for k in ("evidence", "requalification_evidence")))
        tests = []
        for file, name in cited:
            file = file if file.startswith(("tests/", "apps/")) else "apps/web/" + file
            got = results.get(file, {})
            if name:
                picked = {t: s for t, s in got.items() if t == name or t.startswith(name)}
            else:
                picked = got
            tests.append({"file": file, "test": name or None, "ran": len(picked),
                          "failed": sum(s == "failed" for s in picked.values()),
                          "passed": sum(s == "passed" for s in picked.values())})
        ran = [t for t in tests if t["ran"]]
        verdict = ("no automated test cited" if not tests else "cited tests did not run in this job set" if not ran
                   else "failed in CI" if any(t["failed"] for t in ran) else "passed in CI")
        rows.append({"id": r["id"], "register_status": r["status"], "ci": verdict, "tests": tests})
    out = {"commit": sha, "run_id": run_id, "run_url": run_url, "criteria": rows,
           "summary": {v: sum(x["ci"] == v for x in rows) for v in sorted({x["ci"] for x in rows})}}
    rep = ROOT / "artifacts" / "reports"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "acceptance_evidence.json").write_text(json.dumps(out, indent=1) + "\n")
    md = [f"# Acceptance evidence, commit `{sha[:12]}`" + (f", [run {run_id}]({run_url})" if run_url else ""), "",
          "| ID | Register | This CI run | Tests (passed/ran) |", "|---|---|---|---|"]
    for x in rows:
        md.append(f"| {x['id']} | {x['register_status']} | {x['ci']} | "
                  + "; ".join(f"{t['file']}{'::' + t['test'] if t['test'] else ''} {t['passed']}/{t['ran']}" for t in x["tests"])
                  + " |")
    (rep / "acceptance_evidence.md").write_text("\n".join(md) + "\n")
    print(json.dumps(out["summary"]))
    if any(x["ci"] == "failed in CI" for x in rows):
        raise SystemExit("an acceptance criterion's cited tests failed in this run")


if __name__ == "__main__":
    main()
