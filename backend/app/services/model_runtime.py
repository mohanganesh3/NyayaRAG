from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import get_settings


class ModelTask(StrEnum):
    PLACEHOLDER_GENERATION = "placeholder_generation"
    AGENTIC_PLANNING = "agentic_planning"
    AGENTIC_SYNTHESIS = "agentic_synthesis"


class ModelRuntimeError(RuntimeError):
    pass


class JSONTaskModelClient(Protocol):
    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1400,
    ) -> dict[str, object]: ...


Transport = Callable[[str, dict[str, str], dict[str, object], float], str]


def _default_transport(
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    timeout_seconds: float,
) -> str:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ModelRuntimeError(
            f"Anthropic request failed with status {exc.code}: {body}"
        ) from exc
    except URLError as exc:
        raise ModelRuntimeError(f"Anthropic request failed: {exc.reason}") from exc


@dataclass(slots=True, frozen=True)
class AnthropicTaskModelClient:
    api_key: str
    model_name: str
    base_url: str
    timeout_seconds: float
    transport: Transport = _default_transport

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1400,
    ) -> dict[str, object]:
        response_text = self.transport(
            self.base_url,
            {
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
                "x-api-key": self.api_key,
            },
            {
                "model": self.model_name,
                "max_tokens": max_tokens,
                "temperature": 0,
                "system": system_prompt,
                "messages": [
                    {
                        "role": "user",
                        "content": user_prompt,
                    }
                ],
            },
            self.timeout_seconds,
        )
        return self._parse_response(response_text)

    def _parse_response(self, response_text: str) -> dict[str, object]:
        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise ModelRuntimeError("Anthropic response was not valid JSON.") from exc

        content = payload.get("content")
        if not isinstance(content, list):
            raise ModelRuntimeError("Anthropic response did not include content blocks.")

        text_blocks = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        if not text_blocks:
            raise ModelRuntimeError("Anthropic response did not include text content.")

        rendered = "".join(text_blocks).strip()
        if rendered.startswith("```json"):
            rendered = rendered.removeprefix("```json").strip()
        if rendered.endswith("```"):
            rendered = rendered.removesuffix("```").strip()

        try:
            parsed = json.loads(rendered)
        except json.JSONDecodeError as exc:
            raise ModelRuntimeError("Anthropic text content was not valid JSON.") from exc

        if not isinstance(parsed, dict):
            raise ModelRuntimeError("Anthropic JSON content must be an object.")
        return parsed


def build_task_model_client(task: ModelTask) -> JSONTaskModelClient | None:
    settings = get_settings()
    provider = settings.llm_provider.strip().lower()
    if provider != "anthropic":
        return None

    model_name = {
        ModelTask.PLACEHOLDER_GENERATION: settings.anthropic_generation_model,
        ModelTask.AGENTIC_PLANNING: settings.anthropic_planner_model,
        ModelTask.AGENTIC_SYNTHESIS: settings.anthropic_synthesis_model,
    }[task]
    if not settings.anthropic_api_key:
        raise ModelRuntimeError(
            "LLM provider is set to anthropic, but ANTHROPIC_API_KEY is missing."
        )
    if not model_name:
        raise ModelRuntimeError(
            f"LLM provider is set to anthropic, but no model is configured for {task.value}."
        )

    return AnthropicTaskModelClient(
        api_key=settings.anthropic_api_key,
        model_name=model_name,
        base_url=settings.anthropic_base_url,
        timeout_seconds=settings.anthropic_timeout_seconds,
    )
