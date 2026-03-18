from app.tasks.celery_app import celery_app
from app.tasks.heartbeat import heartbeat


def test_celery_app_is_configured() -> None:
    assert celery_app.conf.task_default_queue == "nyayarag-default"
    assert str(celery_app.conf.broker_url).startswith("redis://")


def test_heartbeat_task_returns_expected_payload() -> None:
    assert heartbeat() == {"status": "ok", "task": "heartbeat"}
