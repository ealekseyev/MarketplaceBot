#!/usr/bin/env python3
"""Demo scenarios for fb_store ChatPolicy."""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fb_agent import ClassificationResult, ReplyContext
from fb_agent.models import ChatMessageInput, ListingInput
from fb_store import AgenticAccessDecision, ChatPolicy, Database, OutboundMessage


@dataclass
class Msg:
    sender: str
    text: str


def _assert_decision(decision: AgenticAccessDecision, *, allowed: bool, reason: str) -> None:
    assert decision.allowed is allowed, f"expected allowed={allowed}, got {decision}"
    assert decision.reason == reason, f"expected reason={reason!r}, got {decision.reason!r}"


def run_scenarios(db_path: Path) -> None:
    print(f"Using database: {db_path}")

    with Database(db_path) as db:
        store = ChatPolicy(db)
        chat_id = "chat-new"

        buyer_only = [Msg(sender="buyer", text="Is this still available?")]
        decision = store.should_allow_agentic_response(chat_id, buyer_only)
        _assert_decision(decision, allowed=True, reason="new_chat")
        print("OK new chat (buyer only) -> allow")

        store.record_outbound(chat_id, "Yes, still available!")
        outbound = store.get_last_outbound(chat_id)
        assert outbound is not None and outbound.text == "Yes, still available!"
        assert store.has_logged_outbound(chat_id, "Yes, still available!")
        print("OK record_outbound + get_last_outbound")

        awaiting_buyer = buyer_only + [
            Msg(sender="seller", text="Yes, still available!"),
            Msg(sender="buyer", text="What's your best price?"),
        ]
        decision = store.should_allow_agentic_response(chat_id, awaiting_buyer)
        _assert_decision(decision, allowed=True, reason="awaiting_buyer_reply")
        print("OK logged seller reply + new buyer message -> allow")

        human_override_id = "chat-human"
        human_messages = [
            Msg(sender="buyer", text="Can you do $500?"),
            Msg(sender="seller", text="I typed this myself in FB."),
            Msg(sender="buyer", text="Still interested."),
        ]
        decision = store.should_allow_agentic_response(human_override_id, human_messages)
        _assert_decision(decision, allowed=False, reason="human_override")
        assert store.is_blacklisted(human_override_id)
        assert not store.is_allowed(human_override_id)
        print("OK unlogged seller message -> blacklist human_override")

        mismatch_id = "chat-mismatch"
        store.record_outbound(mismatch_id, "Bot reply")
        mismatch_messages = [
            Msg(sender="buyer", text="Hello"),
            Msg(sender="seller", text="Different seller text"),
            Msg(sender="buyer", text="Anyone there?"),
        ]
        decision = store.should_allow_agentic_response(mismatch_id, mismatch_messages)
        _assert_decision(decision, allowed=False, reason="seller_message_mismatch")
        assert store.is_blacklisted(mismatch_id)
        print("OK seller text mismatch -> blacklist seller_message_mismatch")

        seller_latest_id = "chat-seller-latest"
        store.blacklist_chat(seller_latest_id, reason="manual")
        seller_latest = [
            Msg(sender="buyer", text="Hi"),
            Msg(sender="seller", text="I'll handle this"),
        ]
        decision = store.should_allow_agentic_response(seller_latest_id, seller_latest)
        _assert_decision(decision, allowed=False, reason="blacklisted")
        print("OK manual blacklist -> deny")

        seller_turn_id = "chat-seller-turn"
        seller_turn = [
            Msg(sender="buyer", text="Hi"),
            Msg(sender="seller", text="Thanks for reaching out"),
        ]
        decision = store.should_allow_agentic_response(seller_turn_id, seller_turn)
        _assert_decision(decision, allowed=False, reason="latest_sender_seller")
        print("OK latest sender seller -> deny")

        store.log_outbound(OutboundMessage(chat_id="chat-log-alias", text="Alias path works"))
        assert store.has_logged_outbound("chat-log-alias", "Alias path works")
        print("OK log_outbound alias")

        waiting_id = "chat-waiting"
        ctx = ReplyContext(
            chat_id=waiting_id,
            buyer_name="Alex",
            messages=[ChatMessageInput(sender="buyer", text="Does it fit a 1970 cuda?")],
            listing=ListingInput(title="Bench seat", price="$700"),
        )
        classification = ClassificationResult(
            action="need_seller_input",
            reason="missing_fitment",
            question="Will this fit a 1970 cuda?",
        )
        store.mark_waiting_telegram(
            waiting_id,
            42,
            json.dumps(ctx.to_dict()),
            json.dumps(classification.to_dict()),
        )
        assert store.has_waiting_telegram()
        decision = store.should_allow_agentic_response(waiting_id, buyer_only)
        _assert_decision(decision, allowed=False, reason="waiting_telegram")
        print("OK waiting_telegram blocks agentic response")

        consumed = store.consume_telegram_reply(42)
        assert consumed is not None
        assert consumed.chat_id == waiting_id
        restored_ctx = ReplyContext.from_dict(json.loads(consumed.pending_context))
        restored_classification = ClassificationResult.from_dict(
            json.loads(consumed.pending_classification),
        )
        assert restored_ctx.chat_id == waiting_id
        assert restored_classification.action == "need_seller_input"
        assert not store.has_waiting_telegram()
        print("OK consume_telegram_reply by message id")

        fallback_id = "chat-fallback"
        store.mark_waiting_telegram(
            fallback_id,
            99,
            json.dumps(ctx.to_dict()),
            json.dumps(classification.to_dict()),
        )
        consumed_fallback = store.consume_telegram_reply(None)
        assert consumed_fallback is not None
        assert consumed_fallback.chat_id == fallback_id
        assert not store.has_waiting_telegram()
        print("OK consume_telegram_reply fallback with single waiting row")

    print("All fb_store scenarios passed.")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        run_scenarios(Path(tmp) / "test.sqlite")


if __name__ == "__main__":
    main()
