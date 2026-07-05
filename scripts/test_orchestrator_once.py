#!/usr/bin/env python3
"""Dry-run orchestrator cycle with mocked MarketplaceSession (no browser/LLM)."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from adapters import build_reply_context
from fb_agent import AgentConfig, ReplyContext
from fb_marketplace import ChatDetail, ChatMessage, ChatSummary, ListingDetail, MessageSender
from fb_store import ChatStore
from orchestrator import BotOrchestrator


@dataclass
class MockSession:
    sent: list[tuple[str, str]] = field(default_factory=list)

    async def list_chats(self) -> list[ChatSummary]:
        return [
            ChatSummary(
                chat_id="chat-1",
                chat_url="https://www.facebook.com/messages/t/chat-1",
                unread=True,
                latest_message_sender=MessageSender.BUYER,
                buyer_name="Shawn",
                listing_name="1970 mopar bench seat",
                listing_url="https://www.facebook.com/marketplace/item/123",
            )
        ]

    async def get_chat(self, chat_id: str) -> ChatDetail:
        return ChatDetail(
            summary=ChatSummary(
                chat_id=chat_id,
                chat_url=f"https://www.facebook.com/messages/t/{chat_id}",
                unread=True,
                latest_message_sender=MessageSender.BUYER,
                buyer_name="Shawn",
            ),
            buyer_name="Shawn",
            listing_url="https://www.facebook.com/marketplace/item/123",
            messages=[
                ChatMessage(
                    sender=MessageSender.BUYER,
                    text="Is this still available?",
                    age_seconds=300,
                )
            ],
        )

    async def get_listing(self, listing_url: str) -> ListingDetail:
        return ListingDetail(
            url=listing_url,
            title="1970 mopar bench seat",
            description="700 dollars firm - driver quality mopar bench seat.",
            price="$700",
            condition="Used - Good",
            location_city="San Jose",
            location_state="CA",
        )

    async def send_message(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))
        print(f"[mock send] chat_id={chat_id}\n{text}")


async def test_store_gate_and_delay() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = ChatStore(Path(tmp) / "test.sqlite")
        session = MockSession()

        chat = await session.get_chat("chat-1")
        listing = await session.get_listing(chat.listing_url or "")
        decision = store.should_allow_agentic_response("chat-1", chat.messages)
        assert decision.allowed, decision
        ctx = build_reply_context(chat, listing, agent_config=AgentConfig.from_env())
        assert isinstance(ctx, ReplyContext)
        print("OK store gate + adapter")

        orchestrator = BotOrchestrator(
            store=store,
            agent_config=AgentConfig.from_env(),
            responder=MagicMock(),
            seller_input=MagicMock(),
            summarizer=MagicMock(),
            telegram=None,
            reply_delay_seconds=120,
        )

        # Mock agent to REPLY without LLM
        from fb_agent import AgentAction, ClassificationResult

        async def fake_act(session, chat_id, ctx, action, classification):
            if action == AgentAction.REPLY:
                await session.send_message(chat_id, "mock auto reply")
                store.record_outbound(chat_id, "mock auto reply")

        orchestrator._act = fake_act  # type: ignore[method-assign]

        import orchestrator as orchestrator_module
        from fb_agent.classifier import MessageAction

        def fake_classify(ctx, config=None, stored_facts=None):
            return ClassificationResult(action=MessageAction.AUTO_REPLY.value, reason="test")

        orchestrator_module.classify_message = fake_classify  # type: ignore[assignment]

        await orchestrator.run_once(session)
        assert session.sent == [("chat-1", "mock auto reply")]
        assert store.get_last_outbound("chat-1") is not None
        print("OK orchestrator run_once with mocked agent")


def main() -> None:
    asyncio.run(test_store_gate_and_delay())
    print("All orchestrator dry-run checks passed.")


if __name__ == "__main__":
    main()
