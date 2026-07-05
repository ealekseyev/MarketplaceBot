from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from adapters import build_reply_context
from fb_agent import (
    AgentAction,
    AgentConfig,
    ClassificationResult,
    HandoffSummarizer,
    MarketplaceResponder,
    ReplyContext,
    SellerInputResponder,
    classify_message,
)
from fb_agent.classifier import MessageAction
from fb_marketplace import ChatDetail, ChatSummary, MarketplaceSession, MessageSender
from fb_store import ChatStore
from fb_telegram import TelegramClient, TelegramUpdate

logger = logging.getLogger(__name__)


@dataclass
class PendingSellerInput:
    marketplace_chat_id: str
    ctx: ReplyContext
    classification: ClassificationResult


_ACTION_MAP = {
    MessageAction.AUTO_REPLY: AgentAction.REPLY,
    MessageAction.NEED_SELLER_INPUT: AgentAction.NEED_SELLER_INPUT,
    MessageAction.HAND_OFF: AgentAction.HAND_OFF,
}

_TELEGRAM_ACTION_PREFIX = {
    AgentAction.HAND_OFF: "[HAND_OFF]",
    AgentAction.NEED_SELLER_INPUT: "[MORE INFO NEEDED]",
}


def _format_telegram_notification(action: AgentAction, summary_text: str, *, footer: str | None = None) -> str:
    prefix = _TELEGRAM_ACTION_PREFIX.get(action)
    if prefix is None:
        body = summary_text.strip()
    else:
        body = f"{prefix}\n\n{summary_text.strip()}"
    if footer:
        return f"{body}\n\n{footer}"
    return body


class BotOrchestrator:
    def __init__(
        self,
        *,
        store: ChatStore,
        agent_config: AgentConfig,
        responder: MarketplaceResponder,
        seller_input: SellerInputResponder,
        summarizer: HandoffSummarizer,
        telegram: TelegramClient | None,
        reply_delay_seconds: float = 120.0,
        only_chat_id: str | None = None,
    ) -> None:
        self._store = store
        self._agent_config = agent_config
        self._responder = responder
        self._seller_input = seller_input
        self._summarizer = summarizer
        self._telegram = telegram
        self._reply_delay_seconds = reply_delay_seconds
        self._only_chat_id = only_chat_id
        self._pending_by_telegram_msg: dict[int, PendingSellerInput] = {}
        self._telegram_update_offset: int | None = None

    def _pending_marketplace_chat_ids(self) -> set[str]:
        return {pending.marketplace_chat_id for pending in self._pending_by_telegram_msg.values()}

    async def _notify(self, text: str) -> int | None:
        if self._telegram is None:
            print(f"[telegram mock]\n{text}")
            return None
        sent = await self._telegram.send_message(text)
        return sent.message_id

    async def _poll_telegram(self, session: MarketplaceSession) -> None:
        if self._telegram is None or not self._pending_by_telegram_msg:
            return

        updates = await self._telegram.get_updates(offset=self._telegram_update_offset, timeout=0)
        if updates:
            logger.debug("Telegram: received %d update(s), %d pending", len(updates), len(self._pending_by_telegram_msg))

        for update in updates:
            self._telegram_update_offset = update.update_id + 1
            if not update.text:
                logger.debug("Telegram: skipped update %d (no text)", update.update_id)
                continue

            pending_key, pending = self._match_pending_telegram_reply(update)
            if pending is None:
                logger.debug(
                    "Telegram: skipped update %d (reply_to=%s, no matching pending)",
                    update.update_id,
                    update.reply_to_message_id,
                )
                continue

            try:
                draft = self._seller_input.generate_reply(
                    pending.ctx,
                    update.text.strip(),
                )
                await session.send_message(pending.marketplace_chat_id, draft.text)
                self._store.record_outbound(pending.marketplace_chat_id, draft.text)
                del self._pending_by_telegram_msg[pending_key]
                logger.info(
                    "Replied to %s after seller input via Telegram",
                    pending.marketplace_chat_id,
                )
            except Exception:
                logger.exception(
                    "Failed to handle Telegram reply for chat %s",
                    pending.marketplace_chat_id,
                )

    def _match_pending_telegram_reply(
        self,
        update: TelegramUpdate,
    ) -> tuple[int | None, PendingSellerInput | None]:
        if update.reply_to_message_id is not None:
            pending = self._pending_by_telegram_msg.get(update.reply_to_message_id)
            if pending is not None:
                return update.reply_to_message_id, pending

        if len(self._pending_by_telegram_msg) == 1:
            pending_key = next(iter(self._pending_by_telegram_msg))
            logger.info(
                "Telegram: treating plain message as reply to pending chat %s",
                self._pending_by_telegram_msg[pending_key].marketplace_chat_id,
            )
            return pending_key, self._pending_by_telegram_msg[pending_key]

        return None, None

    def _buyer_message_ready(self, chat: ChatDetail) -> bool:
        for message in reversed(chat.messages):
            if message.sender != MessageSender.BUYER:
                continue
            if message.age_seconds is not None:
                return message.age_seconds >= self._reply_delay_seconds
            logger.warning(
                "Chat %s buyer message missing age_seconds; processing anyway",
                chat.summary.chat_id,
            )
            return True
        return False

    async def _process_chat_summary(self, session: MarketplaceSession, summary: ChatSummary) -> None:
        chat_id = summary.chat_id
        buyer_name = summary.buyer_name or "(unknown)"
        logger.info("Processing chat %s (buyer=%s)", chat_id, buyer_name)

        if chat_id in self._pending_marketplace_chat_ids():
            logger.debug("Chat %s waiting on seller Telegram reply; skipping", chat_id)
            return

        try:
            logger.info("Chat %s: fetching thread", chat_id)
            chat = await session.get_chat(chat_id)
            logger.info("Chat %s: thread fetched (%d messages)", chat_id, len(chat.messages))
        except Exception:
            logger.exception("Failed to fetch chat %s", chat_id)
            return

        if not chat.listing_url:
            logger.warning("Chat %s has no listing URL; skipping", chat_id)
            return

        try:
            logger.info("Chat %s: fetching listing %s", chat_id, chat.listing_url)
            listing = await session.get_listing(chat.listing_url)
            logger.info(
                "Chat %s: listing fetched (title=%r, price=%s)",
                chat_id,
                listing.title or "(none)",
                listing.price or "(none)",
            )
        except Exception:
            logger.exception("Failed to fetch listing for chat %s", chat_id)
            return

        decision = self._store.should_allow_agentic_response(chat_id, chat.messages)
        if not decision.allowed:
            logger.info("Chat %s: store gate denied (%s)", chat_id, decision.reason)
            return
        logger.info("Chat %s: store gate allowed", chat_id)

        if not self._buyer_message_ready(chat):
            logger.debug(
                "Chat %s: buyer message not ready (min age %ss); skipping",
                chat_id,
                self._reply_delay_seconds,
            )
            return
        logger.info("Chat %s: buyer message ready for reply", chat_id)

        logger.info("Chat %s: building reply context", chat_id)
        ctx = build_reply_context(chat, listing, agent_config=self._agent_config)
        if not ctx.messages or ctx.messages[-1].sender != "buyer":
            logger.debug("Chat %s: latest message not from buyer; skipping", chat_id)
            return

        try:
            logger.info("Chat %s: classifying latest buyer message", chat_id)
            classification = await asyncio.to_thread(
                classify_message,
                ctx,
                config=self._agent_config,
            )
            action = _ACTION_MAP[MessageAction(classification.action)]
            logger.info(
                "Chat %s: classification result action=%s (mapped=%s)",
                chat_id,
                classification.action,
                action.value,
            )
        except Exception:
            logger.exception("Agent decision failed for chat %s", chat_id)
            return

        logger.info("Chat %s: acting on %s", chat_id, action.value)
        await self._act(session, chat_id, ctx, action, classification)

    async def _act(
        self,
        session: MarketplaceSession,
        chat_id: str,
        ctx: ReplyContext,
        action: AgentAction,
        classification: ClassificationResult,
    ) -> None:
        if action == AgentAction.WAIT:
            logger.debug("Chat %s action WAIT; skipping", chat_id)
            return

        if action == AgentAction.REPLY:
            try:
                logger.info("Chat %s: generating auto-reply", chat_id)
                draft = await asyncio.to_thread(self._responder.generate_reply, ctx)
                logger.info("Chat %s: sending auto-reply (%d chars)", chat_id, len(draft.text))
                await session.send_message(chat_id, draft.text)
                self._store.record_outbound(chat_id, draft.text)
                logger.info("Chat %s: auto-reply sent", chat_id)
            except Exception:
                logger.exception("Auto-reply failed for chat %s", chat_id)
            return

        if action == AgentAction.NEED_SELLER_INPUT:
            try:
                logger.info("Chat %s: requesting seller input via Telegram", chat_id)
                summary = self._summarizer.summarize(ctx, classification=classification)
                notify_text = _format_telegram_notification(
                    AgentAction.NEED_SELLER_INPUT,
                    summary.summary_text,
                    footer="Reply to this message with your answer.",
                )
                message_id = await self._notify(notify_text)
                if message_id is not None:
                    self._pending_by_telegram_msg[message_id] = PendingSellerInput(
                        marketplace_chat_id=chat_id,
                        ctx=ctx,
                        classification=classification,
                    )
                logger.info("Chat %s: seller input requested (%s)", chat_id, classification.question)
            except Exception:
                logger.exception("Seller input handoff failed for chat %s", chat_id)
            return

        if action == AgentAction.HAND_OFF:
            try:
                logger.info("Chat %s: handing off to seller and blacklisting", chat_id)
                summary = self._summarizer.summarize(ctx, classification=classification)
                await self._notify(
                    _format_telegram_notification(AgentAction.HAND_OFF, summary.summary_text)
                )
                self._store.blacklist_chat(chat_id, reason="hand_off")
                logger.info("Chat %s: handoff complete", chat_id)
            except Exception:
                logger.exception("Hand-off failed for chat %s", chat_id)
            return

    async def _poll_facebook(self, session: MarketplaceSession) -> None:
        logger.info("Polling Facebook inbox")
        try:
            chats = await session.list_chats()
        except Exception:
            logger.exception("Failed to list chats")
            return

        candidates = [
            chat
            for chat in chats
            if chat.unread and chat.latest_message_sender == MessageSender.BUYER
        ]
        if self._only_chat_id is not None:
            candidates = [chat for chat in candidates if chat.chat_id == self._only_chat_id]
        logger.info(
            "Inbox: %d chats, %d unread buyer candidates%s",
            len(chats),
            len(candidates),
            f" (only {self._only_chat_id})" if self._only_chat_id else "",
        )

        for summary in candidates:
            await self._process_chat_summary(session, summary)

    async def run_once(self, session: MarketplaceSession) -> None:
        logger.debug("Starting poll cycle")
        await self._poll_telegram(session)
        await self._poll_facebook(session)
        logger.debug("Poll cycle complete")

    async def run_forever(self, session: MarketplaceSession, poll_interval_seconds: float) -> None:
        import asyncio

        iteration = 0
        while True:
            iteration += 1
            logger.info("Poll iteration %d starting", iteration)
            await self.run_once(session)
            logger.info("Poll iteration %d complete; sleeping %.1fs", iteration, poll_interval_seconds)
            await asyncio.sleep(poll_interval_seconds)
