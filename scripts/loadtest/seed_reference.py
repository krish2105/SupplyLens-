"""Build the ARC-07 reference data set in its own database and workspace (`load-ref`).

    SUPPLYLENS_LOAD_DB=supplylens_load uv run python scripts/loadtest/seed_reference.py

Declared reference data (ARC-07): 100,000 indexed chunks (1024-d embeddings) and 1,000,000 transaction rows
(2,000 SKUs x 560 days of daily sales, ~10% of days absent). Everything is SYNTHETIC, generated with a fixed seed; the text is pseudo-English
built from a skewed vocabulary so full-text selectivity is realistic, and the vectors are random unit vectors (exact
cosine scan cost does not depend on their content). Also creates 20 load-test accounts (dev accounts, one per virtual
user) because rate limits are per user: sharing one account would measure the limiter, not the system.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import psycopg

DB = os.environ.get("SUPPLYLENS_LOAD_DB", "supplylens_load")
HOST = os.environ.get("PGHOST", "/tmp")
N_SKU, DAYS, N_DOCS, CHUNKS_PER_DOC, DIM, N_USERS = 2000, 560, 2000, 50, 1024, 20
LAST_DAY = date(2011, 12, 8)
NS = uuid.UUID("5a1e5b0e-0000-4000-8000-000000000001")
REPO = Path(__file__).resolve().parents[2]

DOMAIN = ("supplier lead time minimum order quantity price break payment terms penalty delivery warranty liability "
          "indemnity termination renewal audit confidential governing law force majeure exclusivity rebate discount "
          "shipment pallet carton inspection quality defect return credit invoice currency tariff incoterm packaging").split()


def conn(dbname=DB, **kw):
    return psycopg.connect(host=HOST, user="postgres", dbname=dbname, autocommit=True, **kw)


def ensure_database() -> None:
    with conn("postgres") as c:
        if not c.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DB,)).fetchone():
            c.execute(f"CREATE DATABASE {DB} OWNER supplylens_owner")
    with conn() as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        c.execute(f"GRANT CONNECT ON DATABASE {DB} TO supplylens_app")
    env = {**os.environ, "SUPPLYLENS_MIGRATION_URL": f"postgresql+psycopg://supplylens_owner:supplylens_owner_dev@localhost:5432/{DB}"}
    subprocess.run(["uv", "run", "--no-sync", "alembic", "-c", "services/api/alembic.ini", "upgrade", "head"], cwd=REPO, env=env, check=True)


def vocabulary(rng) -> list[str]:
    """Frequency-ordered words (index 0 = most frequent). The domain words sit at ranks 100-140, so each appears in roughly
    5% of chunks and a two-word query matches a few hundred: realistic for contract text, unlike stop-word-level frequency."""
    syll = ["ba", "ko", "ren", "tul", "mar", "vis", "pol", "den", "sa", "lo", "tri", "quen", "dor", "fel", "gan", "hu"]
    pseudo = sorted({"".join(rng.choice(syll, size=rng.integers(2, 4))) for _ in range(6000)})
    return pseudo[:100] + list(DOMAIN) + pseudo[100:]


def main() -> None:
    t0 = time.time()
    ensure_database()
    rng = np.random.default_rng(20111208)
    sys.path.insert(0, str(REPO / "services/api/src"))
    os.environ["SUPPLYLENS_ADMIN_DATABASE_URL"] = f"postgresql+psycopg://supplylens_owner:supplylens_owner_dev@localhost:5432/{DB}"
    os.environ["SUPPLYLENS_DATABASE_URL"] = f"postgresql+psycopg://supplylens_app:supplylens_app_dev@localhost:5432/{DB}"
    from supplylens.seed import create_tenant, seed, tenant_id, user_id
    seed()
    create_tenant("load-ref", "Load reference (SYNTHETIC)", "customer", "ARC-07 reference-profile workload. Synthetic.")
    t = tenant_id("load-ref")
    did = uuid.uuid5(NS, "dataset")
    with conn() as c:
        if c.execute("SELECT count(*) FROM sales_daily WHERE tenant_id=%s", (t,)).fetchone()[0]:
            print(json.dumps({"reused": True})); return
        # accounts: one per virtual user, mix of roles (viewer / planner)
        for i in range(N_USERS):
            email = f"load{i:02d}@dev.supplylens.local"
            uid = user_id(email)
            c.execute("INSERT INTO users (id,email,display_name,is_dev_account) VALUES (%s,%s,%s,true) ON CONFLICT DO NOTHING",
                      (uid, email, f"Load user {i:02d}"))
            c.execute("INSERT INTO memberships (tenant_id,user_id,role) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                      (t, uid, "planner" if i % 4 == 0 else "viewer"))
        c.execute("""INSERT INTO datasets (id,tenant_id,name,source_kind,license,file_name,sha256,bytes,schema_version,status,report)
                     VALUES (%s,%s,'SYNTHETIC load reference','generated','synthetic','load-ref',%s,0,'load-v1','READY',%s)""",
                  (did, t, uuid.uuid4().hex * 2, json.dumps({"totals": {"input_rows": N_SKU * DAYS, "accepted": N_SKU * DAYS, "returned": 0, "quarantined": 0},
                   "sheets": {}, "date_span": [(LAST_DAY - timedelta(days=DAYS - 1)).isoformat(), LAST_DAY.isoformat()],
                   "distinct_skus_accepted": N_SKU, "distinct_customers": 0, "missing_customer_id_rows": 0, "notes": ["Generated. Not real data."]})))
        c.execute("INSERT INTO locations VALUES (%s,'WH-LOAD','Synthetic warehouse','warehouse',true,'synthetic')", (t,))
        for s in ("LOAD-SUP-A", "LOAD-SUP-B"):
            c.execute("INSERT INTO suppliers VALUES (%s,%s,%s,'generated','synthetic')", (t, s, s))
        c.execute("""INSERT INTO products (tenant_id,sku_id,description,unit,source_kind,dataset_id,first_sale,last_sale)
                     SELECT %s, 'L'||lpad(g::text,5,'0'), 'Synthetic product '||g, 'unit','generated',%s,%s,%s FROM generate_series(1,%s) g""",
                  (t, did, LAST_DAY - timedelta(days=DAYS - 1), LAST_DAY, N_SKU))
        # 1,000,000 daily sales rows: per-SKU rate (skewed), weekly pattern, ~10% missing days
        c.execute("""INSERT INTO sales_daily (tenant_id,dataset_id,sku_id,location_id,day,units)
            SELECT %s,%s,'L'||lpad(s::text,5,'0'),'WH-LOAD',(%s::date - d),
                   greatest(0, round((1 + (s %% 17)) * (case extract(isodow from (%s::date - d)) when 5 then 1.3 when 6 then .5 when 7 then .45 else 1 end)
                          * (0.5 + random()))::numeric)::int
            FROM generate_series(1,%s) s, generate_series(0,%s) d WHERE random() > 0.10""",
                  (t, did, LAST_DAY, LAST_DAY, N_SKU, DAYS - 1))
        c.execute("""INSERT INTO inventory_positions
            SELECT %s,'WH-LOAD','Z'||(s %% 8),'L'||lpad(s::text,5,'0'),%s, ((1 + (s %% 17)) * (2 + (s %% 40)))::int, 0, 0, 5000,'synthetic',NULL
            FROM generate_series(1,%s) s""", (t, LAST_DAY, N_SKU))
        for sup, cost, moq, lt in (("LOAD-SUP-A", 480, 20, 5), ("LOAD-SUP-B", 520, 10, 3)):
            c.execute("""INSERT INTO supplier_terms (term_id,tenant_id,supplier_id,sku_id,unit_cost_minor,currency,moq,order_multiple,lead_time_days,
                           valid_from,known_at,value_kind,source_kind)
                         SELECT %s||'-L'||lpad(s::text,5,'0'), %s, %s, 'L'||lpad(s::text,5,'0'), %s + s %% 50,'GBP',%s,5,%s,'2011-01-01','2011-01-01T00:00:00Z','simulated','generated'
                         FROM generate_series(1,%s) s""", (sup, t, sup, cost, moq, lt, N_SKU))
        c.execute("INSERT INTO tenant_settings VALUES (%s,%s,'GBP',%s,NULL,%s::jsonb) ON CONFLICT (tenant_id) DO NOTHING",
                  (t, datetime(2011, 12, 8, 23, 59, tzinfo=UTC), did,
                   json.dumps({"weekly_budget_minor": 50_000_000, "coverage_days": 21, "safety_days": 5})))
        print(f"relational data done {time.time() - t0:.0f}s", flush=True)

        # documents -> versions -> chunks (100,000 with 1024-d embeddings)
        words = np.array(vocabulary(rng))
        zipf = 1.0 / np.arange(1, len(words) + 1) ** 0.9
        zipf /= zipf.sum()
        for d in range(N_DOCS):
            doc_id, ver_id = uuid.uuid5(NS, f"doc{d}"), uuid.uuid5(NS, f"ver{d}")
            c.execute("INSERT INTO documents (id,tenant_id,title,doc_type,supplier_id,source_kind) VALUES (%s,%s,%s,'contract',%s,'generated')",
                      (doc_id, t, f"Synthetic agreement {d:04d}", "LOAD-SUP-A" if d % 2 == 0 else "LOAD-SUP-B"))
            c.execute("""INSERT INTO document_versions (id,tenant_id,document_id,version_label,file_name,sha256,storage_key,known_at,valid_from,parser_version,embed_model)
                         VALUES (%s,%s,%s,'v1',%s,%s,%s,'2011-01-01T00:00:00Z','2011-01-01','load-v1','synthetic-random')""",
                      (ver_id, t, doc_id, f"agreement-{d:04d}.txt", uuid.uuid4().hex * 2, f"load/{d:04d}"))
        buf = io.StringIO()
        for d in range(N_DOCS):
            ver_id = uuid.uuid5(NS, f"ver{d}")
            vec = rng.standard_normal((CHUNKS_PER_DOC, DIM)).astype(np.float32)
            vec /= np.linalg.norm(vec, axis=1, keepdims=True)
            toks = rng.choice(words, size=(CHUNKS_PER_DOC, 60), p=zipf)
            for k in range(CHUNKS_PER_DOC):
                body = " ".join(toks[k])
                emb = "[" + ",".join(f"{x:.3f}" for x in vec[k]) + "]"
                buf.write("\t".join([str(uuid.uuid5(NS, f"c{d}-{k}")), str(t), str(ver_id), str(k), f"Section {k + 1}",
                                      str(k * 400), str(k * 400 + len(body)), body, emb]) + "\n")
            if d % 100 == 99 or d == N_DOCS - 1:
                buf.seek(0)
                with c.cursor().copy("COPY chunks (id,tenant_id,version_id,ordinal,section,char_start,char_end,body,embedding) FROM STDIN") as cp:
                    cp.write(buf.read())
                buf = io.StringIO()
                print(f"chunks {(d + 1) * CHUNKS_PER_DOC} / {N_DOCS * CHUNKS_PER_DOC}  {time.time() - t0:.0f}s", flush=True)
        c.execute("ANALYZE")
        counts = {k: c.execute(f"SELECT count(*) FROM {k}").fetchone()[0] for k in ("sales_daily", "chunks", "products", "documents")}
    print(json.dumps({"reused": False, "seconds": round(time.time() - t0), **counts}))


if __name__ == "__main__":
    main()
