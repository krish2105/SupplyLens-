"""Phase 8 WP2: docs/course/metrics.md is the one source for presentation numbers. These tests fail when a current run
in the registry has no metrics.json, when a listed field disappears, or when the committed files are stale."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("course_metrics", REPO_ROOT / "scripts" / "course_metrics.py")
cm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cm)


def current_runs() -> list[str]:
    reg = json.loads((REPO_ROOT / "evaluations" / "study_registry.json").read_text())
    return sorted(k for k, v in reg["experiments"].items() if v.get("status") == "current")


@pytest.mark.parametrize("run", current_runs())
def test_every_current_run_has_a_metrics_file(run):
    assert (REPO_ROOT / "artifacts" / "experiments" / run / "metrics.json").exists(), (
        f"{run} is current in evaluations/study_registry.json but has no committed metrics.json")


def test_every_current_study_has_a_data_kind_and_metrics():
    for run in current_runs():
        study = run.split("-")[0]
        assert study in cm.DATA_KIND and study in cm.METRICS and study in cm.N, f"{study}: add it to scripts/course_metrics.py"


def test_a_missing_field_is_an_error_not_a_blank():
    doc = {"a": {"b": [1, {"c": 2}]}}
    assert cm.lookup(doc, "a.b[1].c") == 2
    with pytest.raises(KeyError):
        cm.lookup(doc, "a.x")
    with pytest.raises(KeyError):
        cm.lookup(doc, "a.b[5]")


def test_only_current_runs_are_presentation_evidence():
    doc = cm.build()
    assert [s["run_id"] for s in doc["studies"]] == sorted(current_runs(), key=lambda r: r.split("-")[0])
    assert all(s["status"] == "current" for s in doc["studies"])
    assert not set(doc["not_included"]) & {s["run_id"] for s in doc["studies"]}


def test_committed_files_match_a_fresh_build():
    doc = cm.build()
    assert (REPO_ROOT / "docs" / "course" / "metrics.md").read_text() == cm.render(doc), (
        "docs/course/metrics.md is stale: run uv run python scripts/course_metrics.py")
    assert json.loads((REPO_ROOT / "docs" / "course" / "metrics.json").read_text()) == json.loads(
        json.dumps(doc, ensure_ascii=False)), "docs/course/metrics.json is stale"
