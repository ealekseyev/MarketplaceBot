from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

from .client import FacebookMarketplaceClient
from .env import facebook_credentials_from_env
from .models import SessionConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Facebook Marketplace extraction scaffold")
    parser.add_argument("command", choices=["inbox", "chat", "listing"])
    parser.add_argument("value", nargs="?", help="chat id for 'chat' or listing url for 'listing'")
    parser.add_argument("--user-data-dir", required=True, help="persistent Chromium profile directory")
    parser.add_argument("--env-file", default=".env", help="path to .env containing Facebook credentials")
    parser.add_argument("--headful", action="store_true", help="run Chromium with a visible window")
    parser.add_argument("--timeout-ms", type=int, default=15_000)
    args = parser.parse_args()

    facebook_email, facebook_password = facebook_credentials_from_env(args.env_file)
    config = SessionConfig(
        user_data_dir=args.user_data_dir,
        headless=not args.headful,
        timeout_ms=args.timeout_ms,
        facebook_email=facebook_email,
        facebook_password=facebook_password,
    )
    asyncio.run(_run(args.command, args.value, config))


async def _run(command: str, value: str | None, config: SessionConfig) -> None:
    async with FacebookMarketplaceClient(config) as client:
        if command == "inbox":
            result = [chat.to_dict() for chat in await client.list_chats()]
        elif command == "chat":
            if not value:
                raise SystemExit("chat requires a chat id")
            result = (await client.get_chat(value)).to_dict()
        else:
            if not value:
                raise SystemExit("listing requires a listing url")
            result = (await client.get_listing(value)).to_dict()

    print(json.dumps(_json_ready(result), indent=2, sort_keys=True))


def _json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return _json_ready(asdict(value))
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value
