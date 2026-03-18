# NyayaRAG Backend

FastAPI service for NyayaRAG.

## Run locally

```bash
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Database migrations

```bash
uv run alembic -c alembic.ini upgrade head
uv run alembic -c alembic.ini downgrade base
```

## Worker

```bash
uv run celery -A app.tasks.celery_app:celery_app worker --loglevel=INFO
```
