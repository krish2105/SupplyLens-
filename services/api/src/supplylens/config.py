"""Runtime settings loaded from environment variables (prefix SUPPLYLENS_) or .env.

Environment profile (audit S09). `environment` is development (the default for a local checkout), test, demo or
production. `demo` is a public showcase on fictional and public data: the role accounts stay available, but everything else
fails closed like production (generated secrets, Secure cookies, no owner credentials for the API).
Production fails closed at start-up: development sign-in must be off, every secret and database password must differ
from the published development defaults, session cookies must be Secure, and an OIDC identity provider must be
configured. Development sign-in itself is only available in development and test.
"""
import os
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]
DEV_OWNER_URL = "postgresql+psycopg://supplylens_owner:supplylens_owner_dev@localhost:5432/supplylens"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUPPLYLENS_", env_file=REPO_ROOT / ".env", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://supplylens_app:supplylens_app_dev@localhost:5432/supplylens"
    # Owner credentials are for migrations, seeding and maintenance commands only. The serving API never needs them, and
    # in the demo and production profiles it refuses to start holding them (audit P1-SEC-02); hosted one-time setup is
    # the single exception (SUPPLYLENS_SETUP_TOKEN, hosting/setup.py). Development and test fall back to the published
    # local default.
    admin_database_url: str | None = None
    # True only for migration, seeding and maintenance commands (e.g. scripts/render/predeploy.sh), never for the API.
    maintenance: bool = False
    # Declares this stack disposable test infrastructure, so the browser suite may reset business data (cancel test
    # orders) before it runs. Refused in demo and production; reported by /api/v1/auth/config (Phase 2, SEC-P2-01).
    e2e_disposable: bool = False
    # Sign-in attempts per client address and minute (api/guards.py). The client address comes from X-Forwarded-For only
    # when trust_forwarded_for is set, i.e. behind a platform proxy that overwrites the header (Vercel, Render).
    sign_in_per_minute: int = 20
    trust_forwarded_for: bool = False
    storage_dir: Path = Path("storage")
    # Purchasing-system adapter (integrations/registry.py). Only registered adapters exist; today the local sandbox.
    erp_adapter: str = "sandbox_erp"
    ollama_url: str = "http://localhost:11434"
    embed_model: str = "bge-m3:567m"
    embed_dim: int = 1024
    # Cited generative answers (knowledge/generate.py, D-094). Off unless enabled; never in the demo profile.
    generation_enabled: bool = False
    generation_model: str = "qwen2.5:7b"
    generation_timeout_s: float = 90.0
    # Optional cross-encoder reranker: a local model directory or hub id. Unset = rule-based reranking only.
    reranker_model: str | None = None
    reranker_candidates: int = 20
    environment: Literal["development", "test", "demo", "production"] = "development"
    session_secret: str = "dev-only-change-me"
    dev_auth: bool = True
    cookie_secure: bool = False
    # OIDC authorization-code flow with PKCE (verified locally against Keycloak, see infra/keycloak/).
    # oidc_issuer is the issuer the API reaches (token, JWKS); oidc_public_issuer the one the browser is sent to.
    oidc_issuer: str | None = None
    oidc_public_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str = "http://localhost:3100/api/v1/auth/oidc/callback"
    oidc_post_login_uri: str = "http://localhost:3100/"
    oidc_role_claim: str = "supplylens_roles"     # values "<workspace-slug>:<role>"
    oidc_recheck_seconds: int = 60                # how often a session is re-confirmed with the provider
    # Back-pressure (DEF-10): requests in flight per API process. Past the limit a request is refused at once with 503
    # and Retry-After instead of queueing; costly routes (retrieval, forecasts, scenarios, run starts) have a lower cap.
    # Serverless hosting (Vercel) has no always-on worker: with inline_jobs the request that queues work (agent run,
    # approval, retry, reconcile) also runs that tenant's queued jobs and dispatches before it returns.
    inline_jobs: bool = False
    db_pool_size: int = 10
    # Seconds a request waits for a pooled connection before it is refused with 503 (the SQLAlchemy default, 30 s, let
    # requests pile up behind an exhausted pool long after their callers gave up).
    db_pool_timeout_s: float = 5.0
    # Upper bound for any one SQL statement of the API (0 = none). The worker sets its own (worker_statement_timeout_ms).
    db_statement_timeout_ms: int = 30_000
    worker_statement_timeout_ms: int = 0
    # Retrieval statements are cancelled after this long: past it the database is saturated and the answer would arrive
    # after the 2 s target anyway; cancelling frees the CPU for requests that can still meet it (Phase 3).
    retrieval_statement_timeout_ms: int = 8_000
    # Admission control (api/admission.py), per API process. max_inflight bounds all counted requests and sizes the
    # worker-thread pool that runs them. Retrieval (evidence search) and compute (forecasts, scenarios, run starts) each have
    # their own cap, so a burst of one cannot starve the other. A request finding its class full may wait up to
    # admission_wait_ms in a bounded queue (admission_queue per class) before it is refused with 503 and Retry-After. One
    # workspace may hold at most tenant_share of a class (rounded up), so one tenant cannot take all of it (SEC-P2-11).
    max_inflight: int = 48
    max_inflight_retrieval: int = 6
    max_inflight_compute: int = 4
    admission_queue: int = 12
    admission_wait_ms: int = 500
    tenant_share: float = 0.5
    # Listing endpoints (inventory, documents) return at most this many rows per request; clients page with limit/offset.
    list_max_rows: int = 5_000
    # Prometheus-format metrics at /metrics, only with this bearer token (unset: the endpoint does not exist).
    metrics_token: str | None = None
    approval_ttl_minutes: int = 60 * 24
    # Operational alert queue: the alerts table is the queue; a webhook is an optional second route.
    alert_webhook_url: str | None = None
    alert_webhook_secret: str = "dev-only-change-me"
    # OpenTelemetry: set an OTLP/HTTP endpoint (e.g. http://collector:4318) to export traces.
    otel_endpoint: str | None = None
    otel_service_name: str = "supplylens"

    @model_validator(mode="after")
    def _fail_closed(self):
        """Refuse to start with published defaults outside development, and with any insecure setting in production."""
        defaults = "dev-only-change-me" in (self.session_secret, self.alert_webhook_secret)
        if not self.dev_auth and defaults:
            raise ValueError("SUPPLYLENS_DEV_AUTH=false requires SUPPLYLENS_SESSION_SECRET and "
                             "SUPPLYLENS_ALERT_WEBHOOK_SECRET to be set to non-default values")
        if self.environment in ("production", "demo"):
            problems = []
            if self.dev_auth and self.environment == "production":
                problems.append("SUPPLYLENS_DEV_AUTH must be false")
            if defaults:
                problems.append("session and webhook secrets must not be the development defaults")
            if len(self.session_secret) < 32:
                problems.append("SUPPLYLENS_SESSION_SECRET must be at least 32 characters")
            if "_dev@" in self.database_url or "_dev@" in (self.admin_database_url or ""):
                problems.append("database passwords must not be the development defaults")
            if self.database_url == self.admin_database_url:
                problems.append("the API must not connect with the migration/owner credentials")
            if self.admin_database_url and not (self.maintenance or os.environ.get("SUPPLYLENS_SETUP_TOKEN")):
                problems.append("the serving process must not hold owner database credentials "
                                "(SUPPLYLENS_ADMIN_DATABASE_URL); run migrations and maintenance separately")
            if not self.cookie_secure:
                problems.append("SUPPLYLENS_COOKIE_SECURE must be true (cookies only over TLS)")
            if self.e2e_disposable:
                problems.append("SUPPLYLENS_E2E_DISPOSABLE marks test infrastructure; it is never allowed here")
            if self.generation_enabled and self.environment == "demo":
                problems.append("generated answers are off in the public demo (D-094): unset SUPPLYLENS_GENERATION_ENABLED")
            if self.environment == "production" and not (self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret):
                problems.append("an OIDC provider (issuer, client id, client secret) must be configured")
            if problems:
                raise ValueError(f"{self.environment} profile refused to start: " + "; ".join(problems))
        return self

    @property
    def owner_database_url(self) -> str:
        """The owner connection for migrations, seeding and maintenance commands (never for serving requests)."""
        if self.admin_database_url:
            return self.admin_database_url
        if self.environment in ("development", "test"):
            return DEV_OWNER_URL
        raise RuntimeError("SUPPLYLENS_ADMIN_DATABASE_URL is not set: owner access is only for migrations and maintenance")

    @property
    def generation_available(self) -> bool:
        return self.generation_enabled and self.environment != "demo"

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret)

    @property
    def dev_login_available(self) -> bool:
        return self.dev_auth and self.environment != "production"

    @property
    def storage_path(self) -> Path:
        p = self.storage_dir if self.storage_dir.is_absolute() else REPO_ROOT / self.storage_dir
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
