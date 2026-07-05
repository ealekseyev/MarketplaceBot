#!/usr/bin/env python3
"""Experiment with inbox preview sender detection — does not modify production code."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fb_marketplace.helpers import guess_sender_from_preview
from fb_marketplace.models import MessageSender

# User's live inbox output (Jul 2026)
FIXTURES: list[dict[str, Any]] = [
    {
        "buyer_name": "Evan",
        "chat_id": "858819563627349",
        "preview": "Evan Alekseyev sent you a message about your listing: Mercedes c class w203 2001-2007 door panel rear left.",
        "read_by_me": False,
    },
    {
        "buyer_name": "Shawn",
        "chat_id": "2131486027397586",
        "preview": "Shawn is waiting for your response.",
        "read_by_me": True,
    },
    {
        "buyer_name": "Max",
        "chat_id": "1200198092232951",
        "preview": "?",
        "read_by_me": True,
    },
    {
        "buyer_name": "Junior",
        "chat_id": "2485540785247111",
        "preview": "Junior is waiting for your response.",
        "read_by_me": True,
    },
    {
        "buyer_name": "Facebook user",
        "chat_id": "mp_row_47_7444d6c23c3d",
        "preview": "Jan 7",
        "read_by_me": True,
    },
    {
        "buyer_name": "Facebook user",
        "chat_id": "mp_row_48_cecd1ee29f92",
        "preview": "08/10/25",
        "read_by_me": True,
    },
    {
        "buyer_name": "Facebook user",
        "chat_id": "mp_row_49_d595653592b6",
        "preview": "08/10/25",
        "read_by_me": True,
    },
    {
        "buyer_name": "Anthony",
        "chat_id": "24325388283732989",
        "preview": "07/31/25",
        "read_by_me": True,
    },
    {
        "buyer_name": "Richard",
        "chat_id": "9740031092769475",
        "preview": "Richard Lisle sent you a message about your listing: 2005 RockShox Boxxer Dual Crown Fork.",
        "read_by_me": False,
    },
    {
        "buyer_name": "Gregory",
        "chat_id": "28927723503540319",
        "preview": "05/07/25",
        "read_by_me": True,
    },
    {
        "buyer_name": "Javier",
        "chat_id": "29833012452964630",
        "preview": "05/07/25",
        "read_by_me": True,
    },
    {
        "buyer_name": "John",
        "chat_id": "9476797192440823",
        "preview": "05/07/25",
        "read_by_me": True,
    },
]

_SLASH_DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")
_MONTH_DAY = re.compile(
    r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}$",
    re.IGNORECASE,
)
_WAITING = re.compile(r"^.+ is waiting for your response\.$", re.IGNORECASE)


@dataclass(frozen=True)
class ExperimentResult:
    sender: str
    rule: str
    note: str = ""


def is_timestamp_only_preview(preview: str | None) -> bool:
    if not preview:
        return False
    cleaned = preview.strip()
    if _SLASH_DATE.match(cleaned):
        return True
    if _MONTH_DAY.match(cleaned):
        return True
    return False


def experiment_guess_sender(
    preview: str | None,
    buyer_name: str | None = None,
    *,
    read_by_me: bool | None = None,
    graphql_snippet: str | None = None,
    unread_count: int | None = None,
) -> ExperimentResult:
    """Heuristic sender detection for marketplace inbox previews."""

    if graphql_snippet:
        snippet_result = _classify_from_snippet(graphql_snippet, buyer_name)
        if snippet_result.sender != "unknown":
            return snippet_result

    if not preview:
        if unread_count and unread_count > 0:
            return ExperimentResult("buyer", "graphql_unread_count", "no preview; unread_count > 0")
        if read_by_me is False:
            return ExperimentResult("buyer", "unread_fallback", "no preview; row unread")
        return ExperimentResult("unknown", "empty_preview")

    cleaned = preview.strip()
    lowered = cleaned.lower()
    short_buyer = (buyer_name or "").split(" · ", 1)[0].strip()

    if lowered.startswith("you:"):
        return ExperimentResult("seller", "you_colon_prefix")

    if short_buyer and lowered.startswith(f"{short_buyer.lower()}:"):
        return ExperimentResult("buyer", "buyer_name_colon_prefix")

    if "sent you a message about your listing" in lowered:
        return ExperimentResult("buyer", "listing_notification")

    if _WAITING.match(cleaned):
        return ExperimentResult("buyer", "waiting_for_response")

    if "send a quick response" in lowered:
        return ExperimentResult("buyer", "send_quick_response")

    if lowered.startswith("you sent"):
        return ExperimentResult("seller", "you_sent")

    if is_timestamp_only_preview(cleaned):
        return ExperimentResult("timestamp_only", "timestamp_only", "open chat to see last sender")

    if unread_count and unread_count > 0:
        return ExperimentResult("buyer", "graphql_unread_count", f"preview={cleaned!r}")

    if read_by_me is False:
        return ExperimentResult("buyer", "unread_row", f"preview={cleaned!r}")

    if not _looks_like_system_phrase(cleaned):
        return ExperimentResult("buyer", "raw_message_heuristic", "short message text, not a system phrase")

    return ExperimentResult("unknown", "no_rule_matched")


def _classify_from_snippet(snippet: str, buyer_name: str | None) -> ExperimentResult:
    cleaned = snippet.strip()
    lowered = cleaned.lower()
    short_buyer = (buyer_name or "").split(" · ", 1)[0].strip().lower()

    if lowered.startswith("you:"):
        return ExperimentResult("seller", "graphql_snippet_you_colon")
    if short_buyer and lowered.startswith(f"{short_buyer}:"):
        return ExperimentResult("buyer", "graphql_snippet_buyer_colon")
    if "sent you a message about your listing" in lowered:
        return ExperimentResult("buyer", "graphql_snippet_listing_notification")
    if _WAITING.match(cleaned):
        return ExperimentResult("buyer", "graphql_snippet_waiting")
    return ExperimentResult("unknown", "graphql_snippet_unmatched")


def _looks_like_system_phrase(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in (
            "started this chat",
            "is waiting for your response",
            "send a quick response",
            "sent you a message about your listing",
            "view buyer profile",
            "view seller profile",
            "facebook marketplace assistant",
        )
    )


def run_fixtures() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in FIXTURES:
        preview = item["preview"]
        buyer_name = item["buyer_name"]
        production = guess_sender_from_preview(preview, buyer_name, unread=not item.get("read_by_me", True))
        experiment = experiment_guess_sender(
            preview,
            buyer_name,
            read_by_me=item.get("read_by_me"),
            graphql_snippet=item.get("graphql_snippet"),
            unread_count=item.get("unread_count"),
        )
        rows.append(
            {
                "chat_id": item["chat_id"],
                "buyer_name": buyer_name,
                "preview": preview,
                "read_by_me": item.get("read_by_me"),
                "production_sender": production.value,
                "experiment_sender": experiment.sender,
                "experiment_rule": experiment.rule,
                "note": experiment.note,
            }
        )
    return rows


async def run_live(
    user_data_dir: str,
    env_file: str,
    headful: bool,
    limit: int | None,
) -> list[dict[str, Any]]:
    from fb_marketplace import FacebookMarketplaceClient, SessionConfig, facebook_credentials_from_env

    email, password = facebook_credentials_from_env(env_file)
    config = SessionConfig(
        user_data_dir=user_data_dir,
        headless=not headful,
        facebook_email=email,
        facebook_password=password,
    )
    rows: list[dict[str, Any]] = []
    async with FacebookMarketplaceClient(config) as client:
        chats = await client.list_chats(limit=limit)
        for chat in chats:
            production = chat.latest_message_sender
            experiment = experiment_guess_sender(
                chat.latest_message_preview,
                chat.buyer_name,
                read_by_me=not chat.unread,
            )
            rows.append(
                {
                    "chat_id": chat.chat_id,
                    "buyer_name": chat.buyer_name,
                    "preview": chat.latest_message_preview,
                    "read_by_me": not chat.unread,
                    "raw_text_parts": chat.raw_text_parts,
                    "production_sender": production.value,
                    "experiment_sender": experiment.sender,
                    "experiment_rule": experiment.rule,
                    "note": experiment.note,
                }
            )
    return rows


def print_table(rows: list[dict[str, Any]]) -> None:
    print(f"{'chat_id':<22} {'buyer':<14} {'prod':<10} {'exp':<16} {'rule':<28} preview")
    print("-" * 120)
    for row in rows:
        preview = (row["preview"] or "")[:50]
        if len(row.get("preview") or "") > 50:
            preview += "…"
        print(
            f"{row['chat_id']:<22} "
            f"{(row['buyer_name'] or ''):<14} "
            f"{row['production_sender']:<10} "
            f"{row['experiment_sender']:<16} "
            f"{row['experiment_rule']:<28} "
            f"{preview}"
        )
        if row.get("note"):
            print(f"{'':22} note: {row['note']}")
        if row.get("raw_text_parts"):
            print(f"{'':22} text_parts: {row['raw_text_parts']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Experiment with inbox sender detection heuristics")
    parser.add_argument("--fixtures", action="store_true", default=True, help="run on baked-in sample data (default)")
    parser.add_argument("--live", action="store_true", help="fetch live inbox via FacebookMarketplaceClient")
    parser.add_argument("--user-data-dir", default="./.browser-profile")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of table")
    args = parser.parse_args()

    if args.live:
        rows = asyncio.run(
            run_live(args.user_data_dir, args.env_file, args.headful, args.limit)
        )
    else:
        rows = run_fixtures()

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print_table(rows)

        buyer_count = sum(1 for r in rows if r["experiment_sender"] == "buyer")
        ts_count = sum(1 for r in rows if r["experiment_sender"] == "timestamp_only")
        unknown_count = sum(1 for r in rows if r["experiment_sender"] == "unknown")
        prod_unknown = sum(1 for r in rows if r["production_sender"] == MessageSender.UNKNOWN.value)
        print()
        print(
            f"Summary: production unknown={prod_unknown}/{len(rows)}, "
            f"experiment buyer={buyer_count}, timestamp_only={ts_count}, unknown={unknown_count}"
        )


if __name__ == "__main__":
    main()
