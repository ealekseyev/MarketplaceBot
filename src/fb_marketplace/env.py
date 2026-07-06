from __future__ import annotations

from pathlib import Path


def load_env_file(path: str = ".env") -> dict[str, str]:
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

        if value and value[0] == value[-1] and value[0] in {"\"", "'"}:
            value = value[1:-1]
        values[key] = value

    return values


def facebook_credentials_from_env(path: str = ".env") -> tuple[str | None, str | None]:
    values = load_env_file(path)
    email = (
        values.get("FACEBOOK_EMAIL")
        or values.get("FACEBOOK_USERNAME")
        or values.get("FB_EMAIL")
    )
    password = values.get("FACEBOOK_PASSWORD") or values.get("FB_PASSWORD")
    return email, password
