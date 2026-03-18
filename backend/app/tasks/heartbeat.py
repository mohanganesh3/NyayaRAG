from app.tasks.celery_app import celery_app


@celery_app.task(name="nyayarag.tasks.heartbeat")
def heartbeat() -> dict[str, str]:
    return {"status": "ok", "task": "heartbeat"}

