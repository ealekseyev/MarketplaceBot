from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from .config import AgentConfig

_THINK_OPEN = "<" + "think" + ">"
_THINK_CLOSE = "<" + "/" + "think" + ">"


class LLMError(RuntimeError):
    pass


def _extract_message_text(message: dict[str, Any]) -> str:
    text = (message.get("content") or "").strip()
    if _THINK_CLOSE in text:
        text = text.rsplit(_THINK_CLOSE, 1)[-1].strip()
    if text.startswith(_THINK_OPEN):
        text = re.sub(r"^.*?(?:" + _THINK_CLOSE + "|$)", "", text, flags=re.DOTALL).strip()
    return text


def chat_completion(
    config: AgentConfig,
    messages: list[dict[str, Any]],
    *,
    temperature: float | None = None,
) -> tuple[str, dict[str, Any]]:
    url = f"{config.base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature if temperature is None else temperature,
    }
    if config.enable_thinking:
        extra_body: dict[str, Any] = {
            "enable_thinking": True,
            "chat_template_kwargs": {"enable_thinking": True},
        }
        if config.thinking_budget is not None:
            extra_body["thinking_budget"] = config.thinking_budget
        payload["extra_body"] = extra_body
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=config.timeout_s) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LLMError(f"LLM HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc

    try:
        message = body["choices"][0]["message"]
        text = _extract_message_text(message)
    except (KeyError, IndexError, AttributeError) as exc:
        raise LLMError(f"Unexpected LLM response shape: {body!r}") from exc

    if not text:
        raise LLMError(f"LLM returned empty content: {body!r}")

    return text, body.get("usage") or {}
