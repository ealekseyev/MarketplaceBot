#!/usr/bin/env python3
"""Test fb_agent reply generation with saved conversation histories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fb_agent import (
    AgentConfig,
    ChatMessageInput,
    HandoffSummarizer,
    ListingInput,
    MarketplaceResponder,
    ReplyContext,
    SellerInputResponder,
    build_classifier_messages,
    build_classifier_prompt,
    build_handoff_messages,
    build_seller_input_messages,
    classify_message,
    decide_action,
)
from fb_agent.prompts import build_completion_messages

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "agent-conversations"

DEFAULT_LISTING = ListingInput(
    title="1970 mopar bench seat",
    description="700 dollars firm - driver quality mopar bench seat.",
    price="$700",
    condition="Used - Good",
    location_city="San Jose",
    location_state="CA",
)


def _prompt(text: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{text}{suffix}: ").strip()
    return value or default


def _listing_to_dict(listing: ListingInput) -> dict[str, Any]:
    return {
        "title": listing.title,
        "description": listing.description,
        "price": listing.price,
        "condition": listing.condition,
        "location_city": listing.location_city,
        "location_state": listing.location_state,
    }


def _listing_from_dict(data: dict[str, Any]) -> ListingInput:
    return ListingInput(
        title=data.get("title"),
        description=data.get("description"),
        price=data.get("price"),
        condition=data.get("condition"),
        location_city=data.get("location_city"),
        location_state=data.get("location_state"),
    )


def _messages_to_dict(messages: list[ChatMessageInput]) -> list[dict[str, Any]]:
    return [
        {"sender": message.sender, "text": message.text, "sent_at": message.sent_at}
        for message in messages
    ]


def _messages_from_dict(items: list[dict[str, Any]]) -> list[ChatMessageInput]:
    return [
        ChatMessageInput(
            sender=item["sender"],
            text=item["text"],
            sent_at=item.get("sent_at"),
        )
        for item in items
    ]


def _fixture_path(name: str) -> Path:
    slug = name.strip().replace(" ", "-")
    return FIXTURES_DIR / f"{slug}.json"


def _save_fixture(name: str, payload: dict[str, Any]) -> Path:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    path = _fixture_path(name)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _load_fixture(name: str) -> dict[str, Any]:
    path = _fixture_path(name)
    if not path.exists():
        raise SystemExit(f"Unknown history {name!r}. Run: python scripts/test_agent_reply.py list")
    return json.loads(path.read_text(encoding="utf-8"))


def _list_fixtures() -> list[str]:
    if not FIXTURES_DIR.exists():
        return []
    return sorted(path.stem for path in FIXTURES_DIR.glob("*.json"))


def _context_from_fixture(data: dict[str, Any], config: AgentConfig) -> ReplyContext:
    return ReplyContext(
        chat_id=data.get("chat_id", "test"),
        buyer_name=data.get("buyer_name"),
        messages=_messages_from_dict(data.get("messages", [])),
        listing=_listing_from_dict(data.get("listing", {})),
        seller_name=data.get("seller_name") or config.seller_name,
    )


def _print_prompt(ctx: ReplyContext, config: AgentConfig) -> None:
    messages = build_completion_messages(ctx, config.profile)
    print("=== LLM PROMPT ===")
    for message in messages:
        role = message["role"].upper()
        print(f"\n--- {role} ---")
        print(message["content"])
    print("\n=== END PROMPT ===\n")


def _apply_llm_overrides(config: AgentConfig, args: argparse.Namespace) -> AgentConfig:
    if args.base_url:
        config.base_url = args.base_url
    if args.model:
        config.model = args.model
    return config


def cmd_list(_args: argparse.Namespace) -> None:
    names = _list_fixtures()
    if not names:
        print(f"No saved histories in {FIXTURES_DIR}")
        return
    print(f"Saved histories ({FIXTURES_DIR}):")
    for name in names:
        data = _load_fixture(name)
        message_count = len(data.get("messages", []))
        buyer = data.get("buyer_name", "?")
        title = data.get("listing", {}).get("title", "?")
        print(f"  {name}  ({buyer}, {message_count} messages, {title})")


def cmd_save(args: argparse.Namespace) -> None:
    if not args.name:
        raise SystemExit("save requires a history name")

    print("Create conversation history (press Enter on empty sender to finish messages).\n")
    buyer_name = _prompt("Buyer name", "Shawn")
    seller_name = _prompt("Seller name", AgentConfig.from_env().seller_name)

    listing = ListingInput(
        title=_prompt("Listing title", DEFAULT_LISTING.title or ""),
        description=_prompt("Listing description", DEFAULT_LISTING.description or ""),
        price=_prompt("Listing price", DEFAULT_LISTING.price or ""),
        condition=_prompt("Listing condition", DEFAULT_LISTING.condition or ""),
        location_city=_prompt("City", DEFAULT_LISTING.location_city or ""),
        location_state=_prompt("State", DEFAULT_LISTING.location_state or ""),
    )

    messages: list[ChatMessageInput] = []
    print("\nMessages:")
    while True:
        sender = _prompt("Sender (buyer/seller, empty to done)", "").lower()
        if not sender:
            break
        if sender not in {"buyer", "seller"}:
            print("  use 'buyer' or 'seller'")
            continue
        text = _prompt("Text")
        if not text:
            print("  empty text skipped")
            continue
        messages.append(ChatMessageInput(sender=sender, text=text))

    if not messages:
        raise SystemExit("Need at least one message.")

    payload = {
        "name": args.name,
        "buyer_name": buyer_name,
        "seller_name": seller_name,
        "listing": _listing_to_dict(listing),
        "messages": _messages_to_dict(messages),
    }
    path = _save_fixture(args.name, payload)
    print(f"\nSaved {path}")


def _print_transcript(ctx: ReplyContext) -> None:
    buyer = ctx.buyer_name or "buyer"
    seller = ctx.seller_name
    if not ctx.messages:
        return
    print("--- transcript ---")
    for message in ctx.messages:
        label = seller if message.sender == "seller" else buyer
        print(f"[{label}] {message.text}")
    print()


def _make_context(
    *,
    buyer_name: str | None,
    seller_name: str,
    messages: list[ChatMessageInput],
    listing: ListingInput,
    chat_id: str = "test",
) -> ReplyContext:
    return ReplyContext(
        chat_id=chat_id,
        buyer_name=buyer_name,
        messages=list(messages),
        listing=listing,
        seller_name=seller_name,
    )


def _generate_seller_reply(
    responder: MarketplaceResponder,
    *,
    buyer_name: str | None,
    seller_name: str,
    messages: list[ChatMessageInput],
    listing: ListingInput,
) -> str:
    ctx = _make_context(buyer_name=buyer_name, seller_name=seller_name, messages=messages, listing=listing)
    draft = responder.generate_reply(ctx)
    messages.append(ChatMessageInput(sender="seller", text=draft.text))
    return draft.text


def _classify_and_maybe_reply(
    *,
    config: AgentConfig,
    responder: MarketplaceResponder,
    seller_input: SellerInputResponder,
    buyer_name: str | None,
    seller_name: str,
    messages: list[ChatMessageInput],
    listing: ListingInput,
) -> str | None:
    ctx = _make_context(
        buyer_name=buyer_name,
        seller_name=seller_name,
        messages=messages,
        listing=listing,
    )
    result = classify_message(ctx, config=config)
    print(result.action)
    if result.action == "need_seller_input":
        summary = HandoffSummarizer(config).summarize(ctx, classification=result)
        print("=== TELEGRAM ===")
        print(summary.summary_text)
        print()
        answer = _prompt("Seller answer (facts for the buyer)")
        if not answer:
            print("(no answer — skipped)\n")
            return None
        draft = seller_input.generate_reply(ctx, answer)
        messages.append(ChatMessageInput(sender="seller", text=draft.text))
        return draft.text
    if result.action != "auto_reply":
        return None
    reply = _generate_seller_reply(
        responder,
        buyer_name=buyer_name,
        seller_name=seller_name,
        messages=messages,
        listing=listing,
    )
    return reply


def cmd_chat(args: argparse.Namespace) -> None:
    if not args.history:
        raise SystemExit("chat requires --history <name>")

    config = _apply_llm_overrides(AgentConfig.from_env(getattr(args, "profile", None)), args)
    data = _load_fixture(args.history)
    listing = _listing_from_dict(data.get("listing", {}))
    buyer_name = data.get("buyer_name") or "buyer"
    seller_name = data.get("seller_name") or config.seller_name
    messages = _messages_from_dict(data.get("messages", []))

    print(f"history: {args.history} | listing: {listing.title} ({listing.price})")
    print(f"buyer: {buyer_name} | seller: {seller_name}")
    print("commands: /prompt  /save  /quit\n")

    _print_transcript(_make_context(buyer_name=buyer_name, seller_name=seller_name, messages=messages, listing=listing))

    ctx = _make_context(buyer_name=buyer_name, seller_name=seller_name, messages=messages, listing=listing)
    _print_prompt(ctx, config)

    responder = MarketplaceResponder(config)
    seller_input = SellerInputResponder(config)
    buyer_label = buyer_name

    if messages and messages[-1].sender == "buyer":
        reply = _classify_and_maybe_reply(
            config=config,
            responder=responder,
            seller_input=seller_input,
            buyer_name=buyer_name,
            seller_name=seller_name,
            messages=messages,
            listing=listing,
        )
        if reply:
            print(f"[{seller_name}] {reply}\n")

    while True:
        try:
            line = input(f"{buyer_label}> ").strip()
        except EOFError:
            print()
            break

        if not line:
            continue
        if line.lower() in {"/quit", "/q", "quit", "exit"}:
            break
        if line.lower() == "/prompt":
            ctx = _make_context(buyer_name=buyer_name, seller_name=seller_name, messages=messages, listing=listing)
            _print_prompt(ctx, config)
            continue
        if line.lower() == "/save":
            payload = {
                "name": args.history,
                "buyer_name": buyer_name,
                "seller_name": seller_name,
                "listing": _listing_to_dict(listing),
                "messages": _messages_to_dict(messages),
            }
            path = _save_fixture(args.history, payload)
            print(f"saved {path}\n")
            continue

        messages.append(ChatMessageInput(sender="buyer", text=line))
        reply = _classify_and_maybe_reply(
            config=config,
            responder=responder,
            seller_input=seller_input,
            buyer_name=buyer_name,
            seller_name=seller_name,
            messages=messages,
            listing=listing,
        )
        if reply:
            print(f"[{seller_name}] {reply}\n")


def cmd_classify(args: argparse.Namespace) -> None:
    config = _apply_llm_overrides(AgentConfig.from_env(getattr(args, "profile", None)), args)

    if args.history:
        ctx = _context_from_fixture(_load_fixture(args.history), config)
    else:
        ctx = ReplyContext(
            chat_id="test",
            buyer_name=args.buyer,
            messages=[ChatMessageInput(sender="buyer", text=args.message)],
            listing=DEFAULT_LISTING,
            seller_name=config.seller_name,
        )

    if args.prompt_only:
        messages = build_classifier_messages(ctx, config.profile)
        print("=== CLASSIFIER PROMPT ===")
        for message in messages:
            print(f"\n--- {message['role'].upper()} ---")
            print(message["content"])
        print("\n=== END PROMPT ===\n")
        return

    result = classify_message(ctx, config=config)
    action = decide_action(ctx, config=config)
    print(json.dumps(
        {
            "action": result.action,
            "decide_action": action.value,
            "reason": result.reason,
            "question": result.question,
            "model": result.model,
        },
        indent=2,
    ))


def cmd_seller_reply(args: argparse.Namespace) -> None:
    if not args.answer:
        raise SystemExit("seller-reply requires --answer")

    config = _apply_llm_overrides(AgentConfig.from_env(getattr(args, "profile", None)), args)

    if args.history:
        ctx = _context_from_fixture(_load_fixture(args.history), config)
    else:
        ctx = ReplyContext(
            chat_id="test",
            buyer_name=args.buyer,
            messages=[ChatMessageInput(sender="buyer", text=args.message)],
            listing=DEFAULT_LISTING,
            seller_name=config.seller_name,
        )

    if args.prompt_only:
        messages = build_seller_input_messages(ctx, config.profile, args.answer)
        print("=== SELLER-INPUT PROMPT ===")
        for message in messages:
            print(f"\n--- {message['role'].upper()} ---")
            print(message["content"])
        print("\n=== END PROMPT ===\n")
        return

    draft = SellerInputResponder(config).generate_reply(ctx, args.answer)
    print("=== SELLER-INPUT REPLY ===")
    print(json.dumps({"text": draft.text, "model": draft.model}, indent=2))


def cmd_summarize(args: argparse.Namespace) -> None:
    config = _apply_llm_overrides(AgentConfig.from_env(getattr(args, "profile", None)), args)

    if args.history:
        ctx = _context_from_fixture(_load_fixture(args.history), config)
    else:
        ctx = ReplyContext(
            chat_id="test",
            buyer_name=args.buyer,
            messages=[ChatMessageInput(sender="buyer", text=args.message)],
            listing=DEFAULT_LISTING,
            seller_name=config.seller_name,
        )

    if args.prompt_only:
        messages = build_handoff_messages(ctx, config.profile, classification=None)
        print("=== HANDOFF SUMMARY PROMPT ===")
        if args.classify:
            print("(note: --classify is skipped in --prompt-only mode)\n")
        for message in messages:
            print(f"\n--- {message['role'].upper()} ---")
            print(message["content"])
        print("\n=== END PROMPT ===\n")
        return

    classification = classify_message(ctx, config=config) if args.classify else None
    summary = HandoffSummarizer(config).summarize(ctx, classification=classification)
    print("=== HANDOFF SUMMARY ===")
    print(json.dumps(
        {
            "listing_title": summary.listing_title,
            "listing_price": summary.listing_price,
            "buyer_name": summary.buyer_name,
            "buyer_question": summary.buyer_question,
            "summary_text": summary.summary_text,
            "model": summary.model,
        },
        indent=2,
    ))


def cmd_run(args: argparse.Namespace) -> None:
    config = _apply_llm_overrides(AgentConfig.from_env(getattr(args, "profile", None)), args)

    if args.history:
        ctx = _context_from_fixture(_load_fixture(args.history), config)
    else:
        ctx = ReplyContext(
            chat_id="test",
            buyer_name=args.buyer,
            messages=[
                ChatMessageInput(sender="buyer", text="Is this still available?"),
                ChatMessageInput(sender="buyer", text=args.message),
            ],
            listing=DEFAULT_LISTING,
            seller_name=config.seller_name,
        )

    _print_prompt(ctx, config)

    if args.prompt_only:
        return

    draft = MarketplaceResponder(config).generate_reply(ctx)
    print("=== REPLY ===")
    print(json.dumps({"text": draft.text, "model": draft.model}, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test Marketplace auto-reply generation")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--profile", default=None, help="Path to agent.yaml (default: src/fb_agent/agent.yaml)")

    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Run agent against inline or saved history (default)")
    run.add_argument("--history", help="Saved history name from fixtures/agent-conversations/")
    run.add_argument("--buyer", default="Shawn")
    run.add_argument("--message", default="Would you take $600? I can pick up today.")
    run.add_argument("--prompt-only", action="store_true", help="Print prompt only, skip LLM call")
    run.set_defaults(func=cmd_run)

    save = sub.add_parser("save", help="Interactively create and save a conversation history")
    save.add_argument("name", help="History name (filename slug)")
    save.set_defaults(func=cmd_save)

    list_cmd = sub.add_parser("list", help="List saved conversation histories")
    list_cmd.set_defaults(func=cmd_list)

    chat = sub.add_parser("chat", help="Interactive chat using a saved history")
    chat.add_argument("--history", required=True, help="Saved history name")
    chat.set_defaults(func=cmd_chat)

    classify = sub.add_parser("classify", help="Classify whether a buyer message can be auto-replied")
    classify.add_argument("--history", help="Saved history name from fixtures/agent-conversations/")
    classify.add_argument("--buyer", default="Shawn")
    classify.add_argument(
        "--message",
        default="Do you know what it's out of? Like a duster or charger? Thanks",
    )
    classify.add_argument("--prompt-only", action="store_true", help="Print classifier prompt only")
    classify.set_defaults(func=cmd_classify)

    seller_reply = sub.add_parser(
        "seller-reply",
        help="Generate buyer reply from seller-provided facts",
    )
    seller_reply.add_argument("--history", help="Saved history name from fixtures/agent-conversations/")
    seller_reply.add_argument("--buyer", default="Shawn")
    seller_reply.add_argument(
        "--message",
        default="Do you know what it's out of? Like a duster or charger? Thanks",
    )
    seller_reply.add_argument("--answer", required=True, help="Seller-provided factual answer")
    seller_reply.add_argument("--prompt-only", action="store_true", help="Print seller-input prompt only")
    seller_reply.set_defaults(func=cmd_seller_reply)

    summarize = sub.add_parser("summarize", help="Summarize conversation for Telegram handoff")
    summarize.add_argument("--history", help="Saved history name from fixtures/agent-conversations/")
    summarize.add_argument("--buyer", default="Shawn")
    summarize.add_argument(
        "--message",
        default="Do you know what it's out of? Like a duster or charger? Thanks",
    )
    summarize.add_argument(
        "--classify",
        action="store_true",
        help="Run classifier first and include question/reason in summary prompt",
    )
    summarize.add_argument("--prompt-only", action="store_true", help="Print handoff summary prompt only")
    summarize.set_defaults(func=cmd_summarize)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        args.command = "run"
        args.func = cmd_run
        args.history = None
        args.buyer = "Shawn"
        args.message = "Would you take $600? I can pick up today."
        args.prompt_only = False
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        raise SystemExit(130) from None
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
