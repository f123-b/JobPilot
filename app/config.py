from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "JobPilot")
    database_path: Path = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "jobpilot.db")))

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
    browser_headless: bool = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"

    agent_max_retries: int = int(os.getenv("AGENT_MAX_RETRIES", "2"))
    eval_min_score: int = int(os.getenv("EVAL_MIN_SCORE", "65"))


settings = Settings()
