"""Control-plane seed: the two workspaces and dev-only accounts (one per role per tenant).

Dev accounts exist only for local development (`is_dev_account = true`); production
identity must come from OIDC, which is not configured in this build.
"""
import uuid

from sqlalchemy import text

from .db import admin_engine

NS = uuid.UUID("5e7d1f3c-0b1a-4c55-9a43-2b1c7e0c9d10")

TENANTS = {
    "uci-research": (
        "UCI Research",
        "research",
        "Real UCI Online Retail II sales (CC BY 4.0). Stock, suppliers and costs are SIMULATED.",
    ),
    "demo": (
        "Demo (fictional)",
        "demo",
        "Fictional suppliers, products and contracts from the execution pack. Not real data.",
    ),
}
ROLES = ["viewer", "planner", "approver", "tenant_admin"]


def tenant_id(slug: str) -> uuid.UUID:
    return uuid.uuid5(NS, f"tenant:{slug}")


def user_id(email: str) -> uuid.UUID:
    return uuid.uuid5(NS, f"user:{email}")


def dev_email(role: str) -> str:
    return f"{role}@dev.supplylens.local"


def seed(engine=None) -> None:
    engine = engine or admin_engine()
    with engine.begin() as conn:
        for slug, (name, kind, desc) in TENANTS.items():
            conn.execute(
                text(
                    "INSERT INTO tenants (id, slug, name, kind, description) VALUES (:i,:s,:n,:k,:d) "
                    "ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, description=EXCLUDED.description"
                ),
                {"i": tenant_id(slug), "s": slug, "n": name, "k": kind, "d": desc},
            )
        for role in ROLES:
            email = dev_email(role)
            conn.execute(
                text(
                    "INSERT INTO users (id, email, display_name, is_dev_account) VALUES (:i,:e,:n,true) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"i": user_id(email), "e": email, "n": f"Dev {role.replace('_', ' ').title()}"},
            )
            for slug in TENANTS:
                conn.execute(
                    text(
                        "INSERT INTO memberships (tenant_id, user_id, role) VALUES (:t,:u,:r) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {"t": tenant_id(slug), "u": user_id(email), "r": role},
                )
        # A second approver lets separation-of-duties be exercised in tests and demos.
        email = "approver2@dev.supplylens.local"
        conn.execute(
            text(
                "INSERT INTO users (id, email, display_name, is_dev_account) VALUES (:i,:e,:n,true) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"i": user_id(email), "e": email, "n": "Dev Approver Two"},
        )
        for slug in TENANTS:
            conn.execute(
                text("INSERT INTO memberships VALUES (:t,:u,'approver') ON CONFLICT DO NOTHING"),
                {"t": tenant_id(slug), "u": user_id(email)},
            )


if __name__ == "__main__":
    seed()
    print("seeded tenants and dev accounts")
