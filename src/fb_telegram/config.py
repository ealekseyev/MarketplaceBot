from __future__ import annotations

import os
from pathlib import Path


def _load_env_file(path: str) -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if value and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value

    return values


def telegram_credentials_from_env(path: str = ".env") -> tuple[str | None, str | None]:
    """Return TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from env or .env file."""
    file_values = _load_env_file(path)
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or file_values.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or file_values.get("TELEGRAM_CHAT_ID")
    return token, chat_id
