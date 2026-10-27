"""Cited generative answers (F1; D-094). The local model is replaced by a stub: these tests pin the
checks around it, not the model's wording."""
import json
from datetime import date, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from supplylens.api.app import app
from supplylens.config import settings
from supplylens.knowledge import generate as G
from supplylens.knowledge.retrieve import Evidence
from supplylens.seed import dev_email

P1 = Evidence(chunk_id="c1", document_id="d1", version_id="v1", title="Agreement", version_label="v1", section="Item 20724",
              excerpt="Unit price GBP 0.42 per unit. Minimum order quantity 72 units, in multiples of 24 units. Lead time 13 days.",
              char_start=0, char_end=100, valid_from=date(2011, 1, 1), valid_to=None, known_at=datetime(2011, 1, 1),
              supplier_id="S", source_kind="simulated", sha256="h", supersedes_version_id=None, score=1.0)
P2 = Evidence(**{**P1.__dict__, "chunk_id": "c2", "section": "Item 85099B", "excerpt": "Minimum order quantity 12 units."})


def reply(answer, insufficient=False):
    return {"answer": answer, "insufficient": insufficient}


def test_a_grounded_cited_answer_passes():
    out, why = G.check(reply([{"sentence": "The minimum order is 72 units in multiples of 24.", "cites": [1]},
                              {"sentence": "Delivery takes 13 days.", "cites": [1, 1]}]), [P1, P2])
    assert why is None and [s["cites"] for s in out] == [[1], [1]]


@pytest.mark.parametrize("answer, reason", [
    (reply([{"sentence": "The minimum order is 72 units.", "cites": []}]), "without a valid citation"),
    (reply([{"sentence": "The minimum order is 72 units.", "cites": [3]}]), "without a valid citation"),     # no passage 3
    (reply([{"sentence": "The minimum order is 80 units.", "cites": [1]}]), "figures not in the cited passages (80)"),
    (reply([{"sentence": "The minimum order is 72 units.", "cites": [2]}]), "figures not in the cited passages (72)"),
    (reply([], insufficient=True), "do not answer"),
    ({"text": "free prose"}, "not in the required form"),
    (reply([{"sentence": f"Fact {i}.", "cites": [1]} for i in range(6)]), "figures not in the cited passages"),
])
def test_an_answer_that_is_uncited_ungrounded_or_refused_is_withheld(answer, reason):
    out, why = G.check(answer, [P1, P2])
    assert out == [] and reason in why


def test_a_model_that_is_down_or_babbles_is_withheld_not_an_error(monkeypatch):
    def down(*a, **k):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(G, "_chat", down)
    g = G.generate("moq for 20724", [P1])
    assert g["abstained"] and "unavailable" in g["reason"] and g["sentences"] == []

    monkeypatch.setattr(G, "_chat", lambda *a, **k: {"message": {"content": "not json at all"}})
    assert "unreadable" in G.generate("moq for 20724", [P1])["reason"]


def test_the_demo_profile_refuses_to_start_with_generation_on():
    with pytest.raises(ValueError, match="generated answers are off in the public demo"):
        type(settings)(environment="demo", generation_enabled=True, dev_auth=True, session_secret="x" * 40,
                       alert_webhook_secret="y" * 40, cookie_secure=True,
                       database_url="postgresql+psycopg://app:secret@db/x", admin_database_url=None)


@pytest.fixture()
def demo_docs(clean_db, tenant_b):
    from supplylens.simulation import demo
    demo.load(tenant_b)
    return tenant_b


H = {"X-Requested-With": "supplylens", "X-SupplyLens-Tenant": "demo"}
# scoped to one supplier: two demo suppliers quote this product, and an unscoped question is (rightly) ambiguous
Q = {"q": "minimum order quantity for DEMO-REF-SKU", "supplier_id": "DEMO-REF-A", "effective_date": "2026-10-20",
     "knowledge_cutoff": "2026-10-20T09:00:00Z"}


def viewer():
    c = TestClient(app)
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("viewer")}, headers=H)
    return c


def test_generation_is_off_unless_enabled_and_the_passages_are_still_the_answer(demo_docs, monkeypatch):
    monkeypatch.setattr(settings, "generation_enabled", False)
    r = viewer().post("/api/v1/evidence/answer", headers=H, json=Q)
    assert r.status_code == 200 and r.json()["generation"] == "off" and r.json()["results"]


def test_an_enabled_answer_cites_the_retrieved_passages(demo_docs, monkeypatch):
    monkeypatch.setattr(settings, "generation_enabled", True)
    seen = {}

    def chat(url, body, timeout):
        seen["body"] = body
        passage = body["messages"][1]["content"].split("[2]")[0]
        n = next(t.strip(".,:") for t in passage.split() if t.strip(".,:").isdigit())   # a figure in passage 1
        return {"message": {"content": json.dumps(reply([{"sentence": f"The minimum order is {n} units.", "cites": [1]}]))}}
    monkeypatch.setattr(G, "_chat", chat)
    r = viewer().post("/api/v1/evidence/answer", headers=H, json=Q)
    d = r.json()
    assert r.status_code == 200, r.text
    assert d["generation"] == "answered" and d["generated"]["sentences"][0]["cites"] == [1]
    assert d["generated"]["citations"][0]["version_id"] == d["results"][0]["version_id"]
    assert seen["body"]["options"]["temperature"] == 0 and seen["body"]["format"] == "json"


def test_nothing_is_generated_when_no_passage_answers(demo_docs, monkeypatch):
    monkeypatch.setattr(settings, "generation_enabled", True)
    monkeypatch.setattr(G, "_chat", lambda *a, **k: pytest.fail("the model must not be called"))
    r = viewer().post("/api/v1/evidence/answer", headers=H, json={**Q, "q": "what is the penalty for late payment by the buyer"})
    assert r.json()["generation"] == "not_attempted" and r.json()["generated"] is None


def test_a_question_without_a_product_over_several_products_is_not_answered(clean_db, tenant_a, monkeypatch):
    """G1: "minimum order quantity" with no product code was answered with one product's terms."""
    from supplylens.api import routes_decisions as R
    monkeypatch.setattr(settings, "generation_enabled", True)
    items = [{**P1.__dict__, "section": "Schedule item 20724 (BAG):"}, {**P1.__dict__, "chunk_id": "c2", "section": "Schedule item 22993 (TIN):"}]
    monkeypatch.setattr(R, "_evidence", lambda *a, **k: {"answer": {"type": "extractive", "claims": [], "abstained": False}, "results": items})
    monkeypatch.setattr(G, "_chat", lambda *a, **k: pytest.fail("the model must not be called"))
    c = TestClient(app)
    c.post("/api/v1/auth/dev-login", json={"email": dev_email("viewer")}, headers=H)
    r = c.post("/api/v1/evidence/answer", headers={**H, "X-SupplyLens-Tenant": "uci-research"}, json={"q": "minimum order quantity"})
    assert r.status_code == 200, r.text
    assert r.json()["generation"] == "not_attempted" and "Name the product code" in r.json()["message"]
