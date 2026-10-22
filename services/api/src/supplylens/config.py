"""Runtime settings loaded from environment variables (prefix SUPPLYLENS_) or .env.

Environment profile (audit S09). `environment` is development (the default for a local checkout), test or production.
Production fails closed at start-up: development sign-in must be off, every secret and database password must differ
from the published development defaults, session cookies must be Secure, and an OIDC identity provider must be
configured. Development sign-in itself is only available in development and test.
"""
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUPPLYLENS_", env_file=REPO_ROOT / ".env", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://supplylens_app:supplylens_app_dev@localhost:5432/supplylens"
    admin_database_url: str = (
        "postgresql+psycopg://supplylens_owner:supplylens_owner_dev@localhost:5432/supplylens"
    )
    storage_dir: Path = Path("storage")
    ollama_url: str = "http://localhost:11434"
    embed_model: str = "bge-m3:567m"
    embed_dim: int = 1024
    # Optional cross-encoder reranker: a local model directory or hub id. Unset = rule-based reranking only.
    reranker_model: str | None = None
    reranker_candidates: int = 20
    environment: Literal["development", "test", "production"] = "development"
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
    max_inflight: int = 64
    max_inflight_costly: int = 8
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
        if self.environment == "production":
            problems = []
            if self.dev_auth:
                problems.append("SUPPLYLENS_DEV_AUTH must be false")
            if defaults:
                problems.append("session and webhook secrets must not be the development defaults")
            if len(self.session_secret) < 32:
                problems.append("SUPPLYLENS_SESSION_SECRET must be at least 32 characters")
            if "_dev@" in self.database_url or "_dev@" in self.admin_database_url:
                problems.append("database passwords must not be the development defaults")
            if self.database_url == self.admin_database_url:
                problems.append("the API must not connect with the migration/owner credentials")
            if not self.cookie_secure:
                problems.append("SUPPLYLENS_COOKIE_SECURE must be true (cookies only over TLS)")
            if not (self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret):
                problems.append("an OIDC provider (issuer, client id, client secret) must be configured")
            if problems:
                raise ValueError("production profile refused to start: " + "; ".join(problems))
        return self

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
