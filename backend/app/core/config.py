from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "NyayaRAG Backend"
    app_version: str = "0.1.0"
    app_env: str = "local"
    log_level: str = "INFO"
    log_json: bool = True
    database_url: str = (
        "postgresql+psycopg://nyayarag:nyayarag_dev_password@localhost:5432/nyayarag"
    )
    redis_url: str = "redis://localhost:6379/0"
    celery_task_always_eager: bool = False

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
