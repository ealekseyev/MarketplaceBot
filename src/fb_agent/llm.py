from __future__ import annotations

import re
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from .config import AgentConfig

_THINK_OPEN = "<" + "think" + ">"
_THINK_CLOSE = "<" + "/" + "think" + ">"


class LLMError(RuntimeError):
    pass


def _extract_message_text(content: str | None) -> str:
    text = (content or "").strip()
    if _THINK_CLOSE in text:
        text = text.rsplit(_THINK_CLOSE, 1)[-1].strip()
    if text.startswith(_THINK_OPEN):
        text = re.sub(r"^.*?(?:" + _THINK_CLOSE + "|$)", "", text, flags=re.DOTALL).strip()
    return text


def _make_client(config: AgentConfig) -> OpenAI:
    api_key = config.api_key or "not-needed"
    return OpenAI(
        base_url=config.base_url,
        api_key=api_key,
        timeout=config.timeout_s,
    )


def chat_completion(
    config: AgentConfig,
    messages: list[dict[str, Any]],
    *,
    temperature: float | None = None,
) -> tuple[str, dict[str, Any]]:
    client = _make_client(config)
    request_kwargs: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature if temperature is None else temperature,
    }
    if config.provider == "local" and config.enable_thinking:
        extra_body: dict[str, Any] = {
            "enable_thinking": True,
            "chat_template_kwargs": {"enable_thinking": True},
        }
        if config.thinking_budget is not None:
            extra_body["thinking_budget"] = config.thinking_budget
        request_kwargs["extra_body"] = extra_body

    try:
        response = client.chat.completions.create(**request_kwargs)
    except APIStatusError as exc:
        detail = exc.response.text if exc.response is not None else str(exc)
        raise LLMError(f"LLM HTTP {exc.status_code}: {detail}") from exc
    except (APITimeoutError, APIConnectionError) as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc

    if not response.choices:
        raise LLMError(f"Unexpected LLM response shape: {response!r}")

    message = response.choices[0].message
    text = _extract_message_text(message.content)
    if not text:
        raise LLMError(f"LLM returned empty content: {response!r}")

    usage = response.usage.model_dump() if response.usage is not None else {}
    return text, usage
