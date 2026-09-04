from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "JobPilot")
    database_path: Path = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "jobpilot.db")))
    database_backend: str = os.getenv("DATABASE_BACKEND", "auto").lower()
    database_url: str | None = os.getenv("DATABASE_URL") or None

    openai_api_key: str | None = os.getenv("OPENAI_API_KEY") or None
    openai_base_url: str | None = os.getenv("OPENAI_BASE_URL") or None
    llm_model: str = os.getenv("LLM_MODEL", "gpt-5-mini")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    local_embedding_dim: int = int(os.getenv("LOCAL_EMBEDDING_DIM", "1536"))
    vector_dim: int = int(os.getenv("VECTOR_DIM", os.getenv("LOCAL_EMBEDDING_DIM", "1536")))
    vector_backend: str = os.getenv("VECTOR_BACKEND", "auto").lower()
    postgres_url: str | None = os.getenv("POSTGRES_URL") or None
    checkpoint_backend: str = os.getenv("CHECKPOINT_BACKEND", "auto").lower()
    checkpoint_path: Path = Path(os.getenv("CHECKPOINT_PATH", str(BASE_DIR / "data" / "checkpoints.sqlite")))

    browser_use_api_key: str | None = os.getenv("BROWSER_USE_API_KEY") or None
    browser_model: str = os.getenv("BROWSER_MODEL", "bu-2-0-mini-preview")
    browser_max_steps: int = int(os.getenv("BROWSER_MAX_STEPS", "30"))
    browser_headless: bool = _bool("BROWSER_HEADLESS", False)

    agent_max_retries: int = int(os.getenv("AGENT_MAX_RETRIES", "2"))
    eval_min_score: int = int(os.getenv("EVAL_MIN_SCORE", "65"))

    worker_enabled: bool = _bool("WORKER_ENABLED", True)
    worker_poll_seconds: float = float(os.getenv("WORKER_POLL_SECONDS", "0.75"))
    worker_lease_seconds: int = int(os.getenv("WORKER_LEASE_SECONDS", "180"))
    worker_max_attempts: int = int(os.getenv("WORKER_MAX_ATTEMPTS", "3"))

    llm_input_cost_per_1m: float = float(os.getenv("LLM_INPUT_COST_PER_1M", "0"))
    llm_output_cost_per_1m: float = float(os.getenv("LLM_OUTPUT_COST_PER_1M", "0"))
    embedding_cost_per_1m: float = float(os.getenv("EMBEDDING_COST_PER_1M", "0"))

    otel_enabled: bool = _bool("OTEL_ENABLED", False)
    otel_service_name: str = os.getenv("OTEL_SERVICE_NAME", "jobpilot")
    otel_exporter_endpoint: str | None = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or None

    @property
    def app_database_url(self) -> str | None:
        if self.database_url:
            return self.database_url
        if self.database_backend in {"postgres", "postgresql"}:
            return self.postgres_url
        if self.database_backend == "auto" and self.postgres_url and _bool("USE_POSTGRES_APP_DB", False):
            return self.postgres_url
        return None


settings = Settings()
