import json
import logging

from app.core.logging import JsonFormatter


def test_json_formatter_outputs_expected_keys() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="nyayarag.backend",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="structured log",
        args=(),
        exc_info=None,
    )

    payload = json.loads(formatter.format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "nyayarag.backend"
    assert payload["message"] == "structured log"

