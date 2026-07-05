from __future__ import annotations

import logging
import os

from fb_marketplace.env import load_env_file

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_BASE_URL = "http://10.0.30.33:8080/v1"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "qwen3.6-27b-mtp"
DEFAULT_LOCAL_API_KEY = "local"


def _env_value(key: str, file_values: dict[str, str]) -> str | None:
    if key in os.environ:
        return os.environ[key]
    if key in file_values:
        return file_values[key]
    return None


def _first_env_value(
    keys: tuple[str, ...],
    file_values: dict[str, str],
    *,
    default: str | None = None,
) -> str | None:
    for key in keys:
        value = _env_value(key, file_values)
        if value is not None:
            return value
    return default


def resolve_llm_settings(path: str = ".env") -> dict[str, str | bool]:
    """Resolve LLM provider settings from process env and a .env file."""
    file_values = load_env_file(path)

    provider = (_first_env_value(("LLM_PROVIDER",), file_values, default="local") or "local").lower()
    if provider not in {"local", "openai"}:
        logger.warning("Unknown LLM_PROVIDER=%r; falling back to local", provider)
        provider = "local"

    if provider == "openai":
        base_url = _first_env_value(
            ("LLM_BASE_URL", "OPENAI_BASE_URL"),
            file_values,
            default=DEFAULT_OPENAI_BASE_URL,
        )
        model = _first_env_value(("LLM_MODEL", "OPENAI_MODEL"), file_values, default=DEFAULT_MODEL)
        api_key = _first_env_value(("LLM_API_KEY", "OPENAI_API_KEY"), file_values)
        if api_key is None:
            api_key = ""
            logger.warning("LLM_PROVIDER=openai but LLM_API_KEY is not set")
        enable_thinking = _first_env_value(("OPENAI_ENABLE_THINKING",), file_values, default="false")
    else:
        base_url = _first_env_value(
            ("LLM_BASE_URL", "OPENAI_BASE_URL"),
            file_values,
            default=DEFAULT_LOCAL_BASE_URL,
        )
        model = _first_env_value(("LLM_MODEL", "OPENAI_MODEL"), file_values, default=DEFAULT_MODEL)
        api_key = _first_env_value(("LLM_API_KEY", "OPENAI_API_KEY"), file_values)
        if api_key is None:
            api_key = DEFAULT_LOCAL_API_KEY
        enable_thinking = _first_env_value(("OPENAI_ENABLE_THINKING",), file_values, default="true")

    return {
        "provider": provider,
        "base_url": base_url or DEFAULT_LOCAL_BASE_URL,
        "model": model or DEFAULT_MODEL,
        "api_key": api_key,
        "enable_thinking": enable_thinking.lower() in {"1", "true", "yes"},
    }
