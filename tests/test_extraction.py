"""Phase 8 WP7: rule-based contract-term extraction (supplylens.knowledge.extract) and its read-only endpoint.

The extractor: every field cites a valid character span, results are deterministic, the fictional demo contracts give
their known terms, common non-clauses are not read as clauses, and adversarial text cannot make the patterns slow.
The endpoint: same authentication, workspace scope and document access rule as reading the version; draft only;
nothing is written (no terms, no audit rows, no labels)."""
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from supplylens.api.app import app
from supplylens.config import REPO_ROOT
from supplylens.db import admin_engine, tenant_session
from supplylens.knowledge.extract import FIELDS, MAX_CHARS, MAX_PER_FIELD, extract, sentences
from supplylens.seed import dev_email

H = {"X-Requested-With": "supplylens"}
DEMO = {**H, "X-SupplyLens-Tenant": "demo"}
UCI = {**H, "X-SupplyLens-Tenant": "uci-research"}

CONTRACT = """THIS SUPPLY AGREEMENT is made and entered into as of March 1, 2019 (the "Effective Date") by and between Acme \
Widgets, Inc., a Delaware corporation ("Supplier"), and Beta Retail LLC ("Buyer").

1. Term. The initial term of this Agreement shall be three (3) years from the Effective Date. This Agreement shall \
automatically renew for successive one (1) year periods unless either party gives ninety (90) days written notice of \
non-renewal.

2. Termination. Either party may terminate this Agreement without cause upon ninety (90) days prior written notice to \
the other party. Supplier may terminate this Agreement upon written notice if Buyer materially breaches this Agreement.

3. Exclusivity. Supplier appoints Buyer as its exclusive distributor of the Products in the Territory. Buyer's sole \
and exclusive remedy for defective Products is replacement.

4. Purchase commitment. Buyer shall purchase at least 10,000 units of Product in each Contract Year. The minimum order \
quantity is 500 units. Supplier shall deliver each order within thirty (30) days of receipt of the purchase order.

5. Price. The unit price is USD 12.50 per unit. Supplier may not increase the price more than once per Contract Year.
"""


def by_field(fields):
    out = {}
    for f in fields:
        out.setdefault(f.field, []).append(f)
    return out


def spoken(t: str, f) -> str:
    return " ".join(t[f.start:f.end].split())


# ------------------------------------------------------------------------------------------------ extractor
def test_every_field_cites_a_valid_span_and_says_it_came_from_a_rule():
    fields = extract(CONTRACT)
    assert fields
    for f in fields:
        assert f.field in FIELDS and f.source == "rule"
        assert 0 <= f.start < f.end <= len(CONTRACT)
        span = spoken(CONTRACT, f)
        # the value is the span (clauses, names, dates), a clipped span (long clauses) or read from inside it: a
        # quantity is its number and unit ("thirty (30) days" gives "30 days")
        assert (f.value == span or f.value in span or (f.value.endswith("…") and span.startswith(f.value[:-1]))
                or all(w in span for w in f.value.split())), f


def test_the_synthetic_contract_gives_each_term_once_and_skips_non_clauses():
    got = by_field(extract(CONTRACT))
    values = {k: [f.value for f in v] for k, v in got.items()}
    assert {"Acme Widgets, Inc.", "Beta Retail LLC", "Supplier", "Buyer"} <= set(values["parties"])
    assert values["agreement_date"] == ["March 1, 2019"] and values["effective_date"] == ["March 1, 2019"]
    assert values["expiry_date"][0].startswith("The initial term of this Agreement shall be three (3) years")
    assert values["renewal"][0].startswith("This Agreement shall automatically renew for successive")
    # termination without cause is found; termination for breach is not termination for convenience
    assert len(values["termination_for_convenience"]) == 1 and "without cause" in values["termination_for_convenience"][0]
    # "exclusive distributor" is exclusivity; "sole and exclusive remedy" is not
    assert values["exclusivity"] == ["Supplier appoints Buyer as its exclusive distributor of the Products in the Territory."]
    assert "Buyer shall purchase at least 10,000 units of Product in each Contract Year." in values["minimum_commitment"]
    assert values["moq"] == ["500 units"] and values["lead_time"] == ["30 days"]
    assert "USD 12.50 per unit" in values["price"]
    assert any(v.startswith("Supplier may not increase the price") for v in values["price"])


@pytest.mark.parametrize("name, expected", [
    ("fixtures/reference_case/supplier-A-v1.txt",
     {"effective_date": "2026-01-01", "moq": "20 units", "lead_time": "2 calendar days", "price": "USD 5.00 per unit",
      "parties": "Reference Supplier A (FICTIONAL)"}),
    ("fixtures/reference_case/supplier-A-amendment-v2.txt",
     {"effective_date": "2026-10-20", "moq": "40 units", "lead_time": "2 calendar days", "price": "USD 5.00 per unit"}),
    ("knowledge/synthetic_contracts/DEMO-SUP-001-framework-v1.txt",
     {"effective_date": "2027-01-01", "moq": "40 units", "lead_time": "7 calendar days",
      "parties": "SupplyLens Demo Company (FICTIONAL)"}),
    ("knowledge/synthetic_contracts/DEMO-SUP-001-amendment-v2.txt",
     {"effective_date": "2027-04-01", "moq": "60 units", "lead_time": "10 days"}),
])
def test_the_fictional_demo_contracts_give_their_known_terms(name, expected):
    body = (REPO_ROOT / name).read_text()
    got = by_field(extract(body))
    for field, value in expected.items():
        assert value in [f.value for f in got.get(field, [])], (field, got.get(field))
    # a minimum-order sentence that spans several label lines is cut at the labels, not read as one clause
    assert all(len(f.value) < 200 for f in got.get("minimum_commitment", []))


def test_text_without_terms_gives_nothing():
    assert extract("") == [] and extract("   \n\n ") == []
    assert extract("Meeting notes: the team discussed the warehouse layout and the new shelving.") == []


def test_extraction_is_deterministic_and_ordered_by_field_then_position():
    a, b = extract(CONTRACT), extract(CONTRACT)
    assert a == b
    order = {f: i for i, f in enumerate(FIELDS)}
    assert [(order[f.field], f.start) for f in a] == sorted((order[f.field], f.start) for f in a)


def test_each_clause_field_is_capped():
    body = "\n\n".join(f"Clause {i}. This Agreement shall automatically renew for successive one (1) year periods "
                       f"number {i}." for i in range(10))
    assert len([f for f in extract(body) if f.field == "renewal"]) == MAX_PER_FIELD


def test_sentences_keep_abbreviations_and_cover_the_text():
    t = "Acme Inc. supplies Beta. The U.S. market is served.\n\nSupplier: Acme\nBuyer: Beta"
    spans = [t[a:z] for a, z in sentences(t)]
    assert spans == ["Acme Inc. supplies Beta.", "The U.S. market is served.", "Supplier: Acme", "Buyer: Beta"]


@pytest.mark.parametrize("unit", ["a ", "Abc ", "exclusive ", "1 ", "_", ". ", "\n", '("A" ', "price USD 1", "lead time ",
                                  "minimum order of X1 ", "Acme Inc ", "between Acme ", "Effective Date ", "1st day of ",
                                  "January ____ ", "may terminate ", "deliver within ", "Ab: x\n"])
def test_adversarial_text_cannot_make_the_patterns_slow(unit):
    body = unit * (300_000 // len(unit))
    t0 = time.perf_counter()
    extract(body)
    assert time.perf_counter() - t0 < 3.0, unit


def test_input_beyond_the_cap_is_not_read():
    body = "x " * (MAX_CHARS // 2) + "The minimum order quantity is 500 units."
    assert [f for f in extract(body) if f.field == "moq"] == []


# ------------------------------------------------------------------------------------------------ endpoint
@pytest.fixture()
def demo_world(clean_db, tenant_b):
    from supplylens.simulation import demo
    demo.load(tenant_b)
    return tenant_b


def signed(role):
    c = TestClient(app)
    assert c.post("/api/v1/auth/dev-login", json={"email": dev_email(role)}, headers=H).status_code == 200
    return c


def reference_version(c) -> str:
    docs = c.get("/api/v1/documents", headers=DEMO).json()
    return next(d["version_id"] for d in docs if d["title"] == "Reference Supplier A agreement" and d["version_label"] == "v1")


def counts() -> dict:
    with admin_engine().connect() as conn:
        return {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar()                     # fixed table names
                for t in ("supplier_terms", "audit_events", "clause_labels", "documents", "document_versions", "chunks",
                          "actions", "agent_runs")}


def test_a_viewer_reads_draft_terms_whose_spans_point_into_the_version_text(demo_world):
    c = signed("viewer")
    vid = reference_version(c)
    before = counts()
    r = c.get(f"/api/v1/documents/versions/{vid}/extracted-terms", headers=DEMO)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "draft" and body["version_id"] == vid and body["extractor"] == "rules-v1"
    assert "not used for planning" in body["note"]
    doc = c.get(f"/api/v1/documents/versions/{vid}", headers=DEMO).json()["text"]
    values = {}
    for f in body["fields"]:
        assert f["source"] == "rule" and 0 <= f["start"] < f["end"] <= len(doc)
        assert f["value"] in " ".join(doc[f["start"]:f["end"]].split())
        values.setdefault(f["field"], []).append(f["value"])
    assert values["moq"] == ["20 units"] and values["lead_time"] == ["2 calendar days"]
    assert values["price"] == ["USD 5.00 per unit"] and values["effective_date"] == ["2026-01-01"]
    assert counts() == before                              # nothing extracted is stored, audited or planned with


def test_extracted_terms_follow_the_document_reading_rules(demo_world):
    c = signed("viewer")
    vid = reference_version(c)
    path = f"/api/v1/documents/versions/{vid}/extracted-terms"
    assert TestClient(app).get(path, headers=DEMO).status_code == 401                       # no session
    assert c.get(path, headers=UCI).status_code == 404                                      # another workspace (RLS)
    assert c.get(f"/api/v1/documents/versions/{uuid.uuid4()}/extracted-terms", headers=DEMO).status_code == 404
    with tenant_session(demo_world) as s:                  # restrict the document: a viewer may no longer read it
        s.execute(text("""UPDATE documents SET allowed_roles = ARRAY['planner','approver']
            WHERE id = (SELECT document_id FROM document_versions WHERE id = :v)"""), {"v": vid})
    assert c.get(f"/api/v1/documents/versions/{vid}", headers=DEMO).status_code == 404
    r = c.get(path, headers=DEMO)
    assert r.status_code == 404 and "Reference Supplier" not in r.text
    assert signed("planner").get(path, headers=DEMO).status_code == 200


def test_the_contract_names_the_extracted_terms_response():
    op = app.openapi()["paths"]["/api/v1/documents/versions/{version_id}/extracted-terms"]
    assert set(op) == {"get"}                              # read-only: no method writes extracted terms
    schema = op["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/ExtractedTerms")

