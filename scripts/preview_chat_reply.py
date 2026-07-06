#!/usr/bin/env python3
"""Preview what the agent would do for a live Marketplace chat (no send, no Telegram)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from adapters import build_reply_context
from fb_agent import (
    AgentConfig,
    HandoffSummarizer,
    MarketplaceResponder,
    ReplyContext,
    classify_message,
)
from fb_marketplace import MarketplaceSession, MessageSender, SessionConfig, facebook_credentials_from_env
from fb_store import ChatPolicy, Database


def _print_transcript(ctx) -> None:
    buyer = ctx.buyer_name or "buyer"
    seller = ctx.seller_name
    print("--- conversation ---")
    for message in ctx.messages:
        label = seller if message.sender == "seller" else buyer
        print(f"[{label}] {message.text}")
    print()


def _trim_trailing_seller_messages(ctx: ReplyContext) -> ReplyContext:
    messages = list(ctx.messages)
    trimmed = 0
    while messages and messages[-1].sender == "seller":
        messages.pop()
        trimmed += 1
    if trimmed:
        print(f"(preview: ignoring {trimmed} trailing seller message(s))\n")
    return ReplyContext(
        chat_id=ctx.chat_id,
        buyer_name=ctx.buyer_name,
        messages=messages,
        listing=ctx.listing,
        seller_name=ctx.seller_name,
    )


async def preview(chat_id: str, args: argparse.Namespace) -> None:
    email, password = facebook_credentials_from_env(args.env_file)
    config = SessionConfig(
        user_data_dir=args.user_data_dir,
        headless=not args.headful,
        facebook_email=email,
        facebook_password=password,
        manual_login=args.manual_login,
    )
    agent_config = AgentConfig.from_env(args.profile, env_file=args.env_file)
    db = Database(db_path=args.store_db) if args.check_store else None
    store = ChatPolicy(db) if db is not None else None

    try:
        async with MarketplaceSession(config) as session:
            print(f"Fetching chat {chat_id}...")
            chat = await session.get_chat(chat_id)

            if not chat.listing_url:
                raise SystemExit("Chat has no listing URL.")

            print(f"Fetching listing {chat.listing_url}...")
            listing = await session.get_listing(chat.listing_url)

            ctx = build_reply_context(chat, listing, agent_config=agent_config)
            ctx = _trim_trailing_seller_messages(ctx)
            _print_transcript(ctx)

            if not ctx.messages:
                raise SystemExit("Chat has no messages after trimming trailing seller replies.")
            if ctx.messages[-1].sender != "buyer":
                raise SystemExit("No buyer message to evaluate.")

            if store is not None:
                decision = store.should_allow_agentic_response(chat_id, chat.messages)
                print(f"store gate: allowed={decision.allowed} reason={decision.reason!r}")
                if not decision.allowed:
                    print("\nWould skip this chat in production.")
                    return

            latest_buyer = next(
                (m for m in reversed(chat.messages) if m.sender == MessageSender.BUYER),
                None,
            )
            if latest_buyer and latest_buyer.age_seconds is not None:
                print(f"buyer message age: {latest_buyer.age_seconds}s (reply delay: {args.reply_delay_seconds}s)")
                if latest_buyer.age_seconds < args.reply_delay_seconds:
                    print("Would wait for reply delay in production.")

            print("Classifying...")
            classification = classify_message(ctx, config=agent_config)
            print(json.dumps(
                {
                    "action": classification.action,
                    "reason": classification.reason,
                    "question": classification.question,
                    "model": classification.model,
                },
                indent=2,
            ))
            print()

            if classification.action == "auto_reply":
                print("=== would reply ===")
                draft = MarketplaceResponder(agent_config).generate_reply(ctx)
                print(draft.text)
                print(f"\n(model: {draft.model})")
                return

            print("=== would notify seller on Telegram ===")
            summary = HandoffSummarizer(agent_config).summarize(ctx, classification=classification)
            chat_url = chat.summary.chat_url
            prefix = "[MORE INFO NEEDED]" if classification.action == "need_seller_input" else "[HAND_OFF]"
            print(f"{prefix}\n{chat_url}\n\n{summary.summary_text}")
            if classification.action == "hand_off":
                print("\nWould blacklist this chat in production.")
    finally:
        if db is not None:
            db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview agent action for a Marketplace chat without sending",
    )
    parser.add_argument("chat_id", help="Marketplace / Messenger thread id")
    parser.add_argument("--user-data-dir", required=True, help="Chromium profile directory")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--profile", default=None, help="Path to agent.yaml")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--manual-login", action="store_true")
    parser.add_argument(
        "--check-store",
        action="store_true",
        help="Apply fb_store gate (blacklist / human override)",
    )
    parser.add_argument("--store-db", default=None, help="SQLite path for --check-store")
    parser.add_argument(
        "--reply-delay-seconds",
        type=float,
        default=120.0,
        help="Show whether production would wait for this delay (default 120)",
    )
    args = parser.parse_args()
    asyncio.run(preview(args.chat_id, args))


if __name__ == "__main__":
    main()
