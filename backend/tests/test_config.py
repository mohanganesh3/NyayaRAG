from app.core.config import get_settings
from app.db.session import reset_db_caches


def test_settings_load_from_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_NAME", "NyayaRAG Test Backend")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/9")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    get_settings.cache_clear()
    reset_db_caches()

    settings = get_settings()

    assert settings.app_name == "NyayaRAG Test Backend"
    assert settings.redis_url == "redis://localhost:6379/9"
    assert settings.log_level == "DEBUG"

    get_settings.cache_clear()
    reset_db_caches()

