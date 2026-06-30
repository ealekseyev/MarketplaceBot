from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

from fb_marketplace import FacebookMarketplaceClient, SessionConfig, facebook_credentials_from_env


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Authenticate to Facebook and print the 20 most recent Marketplace chats")
    parser.add_argument("--env-file", default=".env", help="path to .env containing Facebook credentials")
    parser.add_argument("--user-data-dir", default="./.browser-profile", help="persistent Chromium profile directory")
    parser.add_argument("--headful", action="store_true", help="run Chromium with a visible window")
    parser.add_argument("--timeout-ms", type=int, default=20_000)
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()
    email, password = facebook_credentials_from_env(args.env_file)
    config = SessionConfig(
        user_data_dir=args.user_data_dir,
        headless=not args.headful,
        timeout_ms=args.timeout_ms,
        facebook_email=email,
        facebook_password=password,
    )

    async with FacebookMarketplaceClient(config) as client:
        chats = await client.list_chats()

    print(json.dumps(_json_ready([chat.to_dict() for chat in chats[: args.limit]]), indent=2, sort_keys=True))


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


if __name__ == "__main__":
    asyncio.run(main_async())
