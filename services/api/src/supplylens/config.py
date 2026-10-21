"""Runtime settings loaded from environment variables (prefix SUPPLYLENS_) or .env."""
from pathlib import Path

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
    session_secret: str = "dev-only-change-me"
    dev_auth: bool = True
    approval_ttl_minutes: int = 60 * 24
    # Operational alert queue: the alerts table is the queue; a webhook is an optional second route.
    alert_webhook_url: str | None = None
    alert_webhook_secret: str = "dev-only-change-me"
    # OpenTelemetry: set an OTLP/HTTP endpoint (e.g. http://collector:4318) to export traces.
    otel_endpoint: str | None = None
    otel_service_name: str = "supplylens"

    @property
    def storage_path(self) -> Path:
        p = self.storage_dir if self.storage_dir.is_absolute() else REPO_ROOT / self.storage_dir
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
