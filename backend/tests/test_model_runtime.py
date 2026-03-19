from __future__ import annotations

import json

from app.services.model_runtime import AnthropicTaskModelClient, ModelRuntimeError


def test_anthropic_task_model_client_parses_json_text_blocks() -> None:
    captured: dict[str, object] = {}

    def fake_transport(
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> str:
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        captured["timeout"] = timeout_seconds
        return json.dumps(
            {
                "content": [
                    {
                        "type": "text",
                        "text": '{"strategy":"live planning","questions":[]}',
                    }
                ]
            }
        )

    client = AnthropicTaskModelClient(
        api_key="test-key",
        model_name="test-model",
        base_url="https://example.test/messages",
        timeout_seconds=15.0,
        transport=fake_transport,
    )

    result = client.generate_json(
        system_prompt="system",
        user_prompt="user",
        max_tokens=512,
    )

    assert result == {"strategy": "live planning", "questions": []}
    assert captured["url"] == "https://example.test/messages"
    headers = captured["headers"]
    payload = captured["payload"]
    assert isinstance(headers, dict)
    assert isinstance(payload, dict)
    assert headers["x-api-key"] == "test-key"
    assert payload["model"] == "test-model"


def test_anthropic_task_model_client_rejects_invalid_json_payload() -> None:
    client = AnthropicTaskModelClient(
        api_key="test-key",
        model_name="test-model",
        base_url="https://example.test/messages",
        timeout_seconds=15.0,
        transport=lambda *_args: json.dumps({"content": [{"type": "text", "text": "not-json"}]}),
    )

    try:
        client.generate_json(system_prompt="system", user_prompt="user")
    except ModelRuntimeError as exc:
        assert "valid JSON" in str(exc)
    else:
        raise AssertionError("Expected a ModelRuntimeError for invalid JSON content.")
