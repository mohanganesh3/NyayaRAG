from pathlib import Path

from alembic import command
from alembic.config import Config
from app.db.base import Base
from app.db.session import build_engine
from app.models import BackgroundTaskRun, RuntimeSetting
from sqlalchemy import inspect


def _make_alembic_config(database_url: str) -> Config:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_model_imports_are_stable() -> None:
    assert BackgroundTaskRun.__tablename__ == "background_task_runs"
    assert RuntimeSetting.__tablename__ == "runtime_settings"


def test_test_database_can_be_created_and_torn_down(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'foundation.db'}"
    engine = build_engine(database_url)

    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    assert "background_task_runs" in inspector.get_table_names()
    assert "runtime_settings" in inspector.get_table_names()

    Base.metadata.drop_all(engine)
    inspector = inspect(engine)
    assert "background_task_runs" not in inspector.get_table_names()
    assert "runtime_settings" not in inspector.get_table_names()

    engine.dispose()


def test_alembic_migrations_run_cleanly(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'migration.db'}"
    config = _make_alembic_config(database_url)

    command.upgrade(config, "head")
    engine = build_engine(database_url)
    inspector = inspect(engine)
    assert "background_task_runs" in inspector.get_table_names()
    assert "runtime_settings" in inspector.get_table_names()
    engine.dispose()

    command.downgrade(config, "base")
    engine = build_engine(database_url)
    inspector = inspect(engine)
    assert "background_task_runs" not in inspector.get_table_names()
    assert "runtime_settings" not in inspector.get_table_names()
    engine.dispose()

