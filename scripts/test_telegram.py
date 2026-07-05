#!/usr/bin/env python3
"""Send or poll Telegram updates via fb_telegram.

Setup: see src/fb_telegram/TELEGRAM_SETUP.md

Usage:
  python scripts/test_telegram.py send "hello"
  python scripts/test_telegram.py poll
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fb_telegram import TelegramClient, TelegramError, telegram_credentials_from_env


def _require_credentials(env_file: str) -> TelegramClient:
    bot_token, chat_id = telegram_credentials_from_env(env_file)
    missing = [
        name
        for name, value in (
            ("TELEGRAM_BOT_TOKEN", bot_token),
            ("TELEGRAM_CHAT_ID", chat_id),
        )
        if not value
    ]
    if missing:
        print(f"Missing required env vars: {', '.join(missing)}", file=sys.stderr)
        print("See src/fb_telegram/TELEGRAM_SETUP.md", file=sys.stderr)
        raise SystemExit(1)
    return TelegramClient(bot_token, chat_id)


async def _send(client: TelegramClient, text: str) -> None:
    sent = await client.send_message(text)
    print(f"Sent message_id={sent.message_id} chat_id={sent.chat_id}")


async def _poll(client: TelegramClient) -> None:
    updates = await client.get_updates(timeout=0)
    if not updates:
        print("No recent updates.")
        return
    for update in updates:
        print(
            f"update_id={update.update_id} "
            f"chat_id={update.chat_id} "
            f"message_id={update.message_id} "
            f"reply_to={update.reply_to_message_id} "
            f"text={update.text!r}"
        )


async def _run(args: argparse.Namespace) -> None:
    client = _require_credentials(args.env_file)
    try:
        if args.command == "send":
            await _send(client, args.text)
        else:
            await _poll(client)
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Test fb_telegram send/poll")
    parser.add_argument("--env-file", default=".env", help="Path to .env with Telegram credentials")
    subparsers = parser.add_subparsers(dest="command", required=True)

    send_parser = subparsers.add_parser("send", help="Send a message to TELEGRAM_CHAT_ID")
    send_parser.add_argument("text", help="Message text")

    subparsers.add_parser("poll", help="Print recent bot updates once")

    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except TelegramError as exc:
        print(f"Telegram API error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
