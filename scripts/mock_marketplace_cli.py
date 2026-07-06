#!/usr/bin/env python3
"""Interactive REPL for the mock Facebook Marketplace store."""

from __future__ import annotations

import json
import shlex
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fb_marketplace_mock.seed import seed_default_listings
from fb_marketplace_mock.store import MockStore


def _json_ready(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return _json_ready(asdict(value))
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


def _print_json(value: object) -> None:
    print(json.dumps(_json_ready(value), indent=2, sort_keys=True))


def _help() -> None:
    print(
        "Commands:\n"
        "  seed                         Insert default sample listings\n"
        "  listings                     List all listings\n"
        "  inbox                        List unread buyer chats\n"
        "  chat <id>                    Show chat detail\n"
        "  buy <listing_id> [name] msg  Simulate a buyer message\n"
        "  help                         Show this help\n"
        "  quit                         Exit"
    )


def _handle_buy(store: MockStore, parts: list[str]) -> None:
    if len(parts) < 3:
        print("Usage: buy <listing_id> [buyer_name] <message>")
        return

    listing_id = parts[1]
    if len(parts) == 3:
        buyer_name = "Buyer"
        message = parts[2]
    else:
        buyer_name = parts[2]
        message = " ".join(parts[3:])

    chat_id = store.add_buyer_message(listing_id, buyer_name, message)
    print(f"Created/updated chat {chat_id}")


def main() -> None:
    store = MockStore()
    print(f"Mock marketplace DB: {store.db_path}")
    _help()

    while True:
        try:
            line = input("mock> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue

        parts = shlex.split(line)
        command = parts[0].lower()

        if command in {"quit", "exit", "q"}:
            break
        if command == "help":
            _help()
            continue
        if command == "seed":
            inserted = seed_default_listings(store)
            print(f"Seeded {inserted} listing(s)")
            continue
        if command == "listings":
            _print_json([listing.to_dict() for listing in store.list_listings()])
            continue
        if command == "inbox":
            _print_json([chat.to_dict() for chat in store.list_inbox_chats()])
            continue
        if command == "chat":
            if len(parts) < 2:
                print("Usage: chat <id>")
                continue
            try:
                detail = store.get_chat(parts[1])
            except KeyError as exc:
                print(exc)
                continue
            _print_json(detail.to_dict())
            continue
        if command == "buy":
            _handle_buy(store, parts)
            continue

        print(f"Unknown command: {command!r}. Type 'help' for commands.")

    store.close()


if __name__ == "__main__":
    main()
