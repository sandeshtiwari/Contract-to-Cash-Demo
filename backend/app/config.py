from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "backend" / ".env")


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    agent_model: str = os.getenv("AGENT_MODEL", "gpt-5-mini")
    synapsor_url: str = os.getenv("SYNAPSOR_URL", "https://synapsor.ai")
    synapsor_api_key: str = os.getenv("SYNAPSOR_API_KEY", "")
    synapsor_project_id: str = os.getenv("SYNAPSOR_PROJECT_ID", "contract_to_cash")
    synapsor_database_id: str = os.getenv("SYNAPSOR_DATABASE_ID", "db_contract_to_cash_dev")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.openai_api_key:
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
    return settings
