"""Phase 8 WP2: docs/course/metrics.md is the one source for presentation numbers. These tests fail when a current run
in the registry has no metrics.json, when a listed field disappears, or when the committed files are stale."""
from __future__ import annotations

import importlib.util
import json
import re
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


def test_current_runs_are_evidence_and_exploratory_runs_are_kept_apart():
    reg = json.loads((REPO_ROOT / "evaluations" / "study_registry.json").read_text())["experiments"]
    doc = cm.build()
    assert [s["run_id"] for s in doc["studies"]] == sorted(current_runs(), key=lambda r: r.split("-")[0])
    assert all(s["status"] == "current" for s in doc["studies"])
    assert sorted(s["run_id"] for s in doc["exploratory"]) == sorted(k for k, v in reg.items() if v.get("status") == "exploratory")
    assert all(s["status"] == "exploratory" and "exploratory" in s["data_kind"] for s in doc["exploratory"])
    shown = {s["run_id"] for s in doc["studies"] + doc["exploratory"]}
    assert not set(doc["not_included"]) & shown
    assert all(reg[r]["status"] == "superseded" for r in doc["not_included"])


def test_committed_files_match_a_fresh_build():
    doc = cm.build()
    assert (REPO_ROOT / "docs" / "course" / "metrics.md").read_text() == cm.render(doc), (
        "docs/course/metrics.md is stale: run uv run python scripts/course_metrics.py")
    assert json.loads((REPO_ROOT / "docs" / "course" / "metrics.json").read_text()) == json.loads(
        json.dumps(doc, ensure_ascii=False)), "docs/course/metrics.json is stale"


COURSE = REPO_ROOT / "docs" / "course"
QUOTING = ["interim-deck.md", "final-deck.md", "demo-script-5min.md", "marker-guide.md"]


def _slide_text(path: Path) -> str:
    """Slide or script text without front matter and HTML comments (speaker notes, instructions)."""
    text = path.read_text()
    if text.startswith("---\n"):
        text = text.split("\n---\n", 1)[1]
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


@pytest.mark.parametrize("name", QUOTING)
def test_course_documents_quote_numbers_only_from_metrics_md(name):
    path = COURSE / name
    if not path.exists():
        pytest.skip(f"{name} not written yet")
    metrics = (COURSE / "metrics.md").read_text()
    current, _, rest = metrics.partition("\n# Exploratory runs")
    exploratory = rest.partition("\n# Not presentation evidence")[0]
    cell = r"^\| [^|]+ \| ([^|]+?) \| `[^`]+` \|$"
    cur_values = set(re.findall(cell, current, flags=re.M))
    exp_values = set(re.findall(cell, exploratory, flags=re.M))
    # per slide (or section): an exploratory number or headline may appear only where the slide says "exploratory"
    for slide in _slide_text(path).split("\n---\n"):
        labelled = "exploratory" in slide.lower()
        values = cur_values | (exp_values if labelled else set())
        source = current + (exploratory if labelled else "")
        # every bold number is a value of metrics.md (bold marks a quoted result; a range quotes two values)
        for bold in re.findall(r"\*\*([^*]+)\*\*", slide):
            for number in re.findall(r"\d[\d,]*(?:\.\d+)?", bold):
                assert number in values, (f"{name}: **{bold}** quotes {number}, which is not a value in docs/course/metrics.md"
                                          + ("" if labelled else " (exploratory values need the word \"exploratory\" on the slide)"))
        # every quoted registry headline (in italics) is in metrics.md word for word
        for quote in re.findall(r"(?<![*\w])\*([^*]+?)\*(?![*\w])", slide):
            if re.search(r"\d", quote):
                assert quote.strip(" .") in source, f"{name}: *{quote}* is not quoted from docs/course/metrics.md"
