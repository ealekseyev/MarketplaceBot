#!/usr/bin/env python3
"""Interactive REPL for the mock Facebook Marketplace store."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fb_marketplace.models import ChatDetail, ChatMessage, ChatSummary, ListingDetail, MessageSender
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


def _seller_name(listing: ListingDetail | None) -> str:
    return (listing.seller_name if listing else None) or "Seller"


def _print_message(message: ChatMessage, *, buyer_name: str, seller_name: str) -> None:
    if message.sender == MessageSender.BUYER:
        label = f"You ({buyer_name})"
    else:
        label = seller_name
    print(f"  {label}: {message.text}")


def _print_transcript(
    detail: ChatDetail,
    *,
    buyer_name: str,
    seller_name: str | None = None,
) -> None:
    seller = seller_name or "Seller"
    title = detail.listing_name or "(listing)"
    print(f"--- {title} ---")
    print(f"Chat {detail.summary.chat_id} · buyer {detail.buyer_name or buyer_name}")

    if not detail.messages:
        print("  (no messages yet)")
        print()
        return

    for message in detail.messages:
        _print_message(message, buyer_name=buyer_name, seller_name=seller)
    print()


def _print_listings_friendly(listings: list[ListingDetail]) -> None:
    if not listings:
        print("No listings. Run: seed")
        return
    for listing in listings:
        lid = listing.url.rstrip("/").split("/")[-1] if listing.url else "?"
        title = listing.title or "(untitled)"
        price = listing.price or ""
        print(f"  {lid}  {title}  {price}")


def _print_inbox_friendly(chats: list[ChatSummary]) -> None:
    if not chats:
        print("Inbox empty (no unread buyer chats).")
        return
    for chat in chats:
        preview = (chat.latest_message_preview or "")[:60]
        name = chat.buyer_name or "Buyer"
        listing = chat.listing_name or "listing"
        print(f"  [{chat.chat_id}] {name} · {listing}")
        print(f"           {preview}")


def _help() -> None:
    print(
        "Commands:\n"
        "  seed                         Insert default sample listings\n"
        "  listings                     List listings (readable)\n"
        "  inbox                        Unread buyer chats (readable)\n"
        "  open <listing_id> [name]     Chat as buyer (type messages, /refresh for replies)\n"
        "  show <chat_id>               View a thread (readable)\n"
        "  buy <listing_id> [name] msg  One-shot buyer message\n"
        "  dump <chat_id>               Raw JSON for a chat\n"
        "  help                         Show this help\n"
        "  quit                         Exit\n"
        "\n"
        "Tip: run with --chat to jump straight into buyer chat mode."
    )


def _find_chat_id(store: MockStore, listing_id: str, buyer_name: str) -> str | None:
    for chat in store.list_chats():
        if chat.buyer_name != buyer_name:
            continue
        url = chat.listing_url or ""
        if listing_id in url or url.rstrip("/").endswith(f"/{listing_id}"):
            return chat.chat_id
    return None


def _listing_for_id(store: MockStore, listing_id: str) -> ListingDetail:
    return store.get_listing(listing_id)


def _print_new_messages(
    detail: ChatDetail,
    *,
    buyer_name: str,
    seller_name: str,
    since: int,
) -> int:
    for message in detail.messages[since:]:
        _print_message(message, buyer_name=buyer_name, seller_name=seller_name)
    return len(detail.messages)


def run_chat_session(store: MockStore, listing_id: str, buyer_name: str) -> None:
    try:
        listing = _listing_for_id(store, listing_id)
    except KeyError:
        print(f"Listing not found: {listing_id}. Run: seed")
        return

    seller = _seller_name(listing)
    title = listing.title or listing_id
    price = f" · {listing.price}" if listing.price else ""
    print(f"\n--- {title}{price} ---")
    print(f"You are {buyer_name}. Seller is {seller}.")
    print("Type a message and press Enter. /refresh  /back\n")

    chat_id = _find_chat_id(store, listing_id, buyer_name)
    last_count = 0
    if chat_id is not None:
        detail = store.get_chat(chat_id)
        last_count = len(detail.messages)
        if detail.messages:
            _print_new_messages(
                detail,
                buyer_name=buyer_name,
                seller_name=seller,
                since=0,
            )
            print()

    while True:
        try:
            line = input(f"{buyer_name}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.lower() in {"/back", "/exit", "/quit"}:
            break
        if line.lower() == "/refresh":
            if chat_id is None:
                print("  (no chat yet — send a message first)")
                continue
            detail = store.get_chat(chat_id)
            if len(detail.messages) == last_count:
                print("  (no new messages)")
            else:
                _print_new_messages(
                    detail,
                    buyer_name=buyer_name,
                    seller_name=seller,
                    since=last_count,
                )
                last_count = len(detail.messages)
            print()
            continue

        chat_id = store.add_buyer_message(listing_id, buyer_name, line)
        detail = store.get_chat(chat_id)
        _print_new_messages(
            detail,
            buyer_name=buyer_name,
            seller_name=seller,
            since=last_count,
        )
        last_count = len(detail.messages)
        print("  (sent — run the bot in another terminal, then /refresh)\n")


def run_chat_picker(store: MockStore) -> None:
    listings = store.list_listings()
    if not listings:
        inserted = seed_default_listings(store)
        print(f"Seeded {inserted} listing(s).\n")
        listings = store.list_listings()

    print("Pick a listing to message:\n")
    _print_listings_friendly(listings)
    print()

    try:
        listing_id = input("Listing id> ").strip()
        if not listing_id:
            return
        buyer_name = input("Your name (buyer)> ").strip() or "Buyer"
    except (EOFError, KeyboardInterrupt):
        print()
        return

    run_chat_session(store, listing_id, buyer_name)


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
    print(f"Sent as {buyer_name} → chat {chat_id}")


def _repl(store: MockStore) -> None:
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
            _print_listings_friendly(store.list_listings())
            continue
        if command == "inbox":
            _print_inbox_friendly(store.list_inbox_chats())
            continue
        if command == "open":
            if len(parts) == 1:
                run_chat_picker(store)
            elif len(parts) == 2:
                run_chat_session(store, parts[1], "Buyer")
            else:
                run_chat_session(store, parts[1], parts[2])
            continue
        if command in {"show", "chat"}:
            if len(parts) < 2:
                print("Usage: show <chat_id>")
                continue
            try:
                detail = store.get_chat(parts[1])
            except KeyError as exc:
                print(exc)
                continue
            buyer = detail.buyer_name or "Buyer"
            listing = None
            try:
                if detail.listing_url:
                    listing = store.get_listing(detail.listing_url)
            except KeyError:
                pass
            _print_transcript(
                detail,
                buyer_name=buyer,
                seller_name=_seller_name(listing),
            )
            continue
        if command == "dump":
            if len(parts) < 2:
                print("Usage: dump <chat_id>")
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock Facebook Marketplace buyer simulator")
    parser.add_argument(
        "--chat",
        action="store_true",
        help="Start in buyer chat mode (pick listing, then type messages)",
    )
    args = parser.parse_args()

    store = MockStore()
    try:
        if args.chat:
            run_chat_picker(store)
        else:
            _repl(store)
    finally:
        store.close()


if __name__ == "__main__":
    main()
