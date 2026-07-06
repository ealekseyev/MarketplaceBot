from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable

from .database import Database


def _is_seller(sender: object) -> bool:
    if hasattr(sender, "value"):
        return str(getattr(sender, "value")).lower() == "seller"
    return str(sender).lower() == "seller"


def _is_buyer(sender: object) -> bool:
    if hasattr(sender, "value"):
        return str(getattr(sender, "value")).lower() == "buyer"
    return str(sender).lower() == "buyer"


@runtime_checkable
class ChatMessageLike(Protocol):
    sender: str | object
    text: str


@dataclass(frozen=True)
class OutboundMessage:
    chat_id: str
    text: str


@dataclass(frozen=True)
class AgenticAccessDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class ConsumedTelegramReply:
    chat_id: str
    pending_context: str
    pending_classification: str


class ChatPolicy:
    """Chat blacklist, outbound log, reply gate, and Telegram pending state."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def is_allowed(self, chat_id: str) -> bool:
        return not self.is_blacklisted(chat_id)

    def blacklist_chat(self, chat_id: str, *, reason: str = "manual") -> None:
        """Permanently skip a chat. Reason is for callers only; not stored."""
        _ = reason
        self._db.upsert_blacklisted(chat_id)

    def is_blacklisted(self, chat_id: str) -> bool:
        row = self._db.get_chat_row(chat_id)
        return bool(row and row["blacklisted"])

    def record_outbound(self, chat_id: str, text: str) -> None:
        self._db.upsert_latest_outbound(chat_id, text)

    def log_outbound(self, message: OutboundMessage) -> None:
        self.record_outbound(message.chat_id, message.text)

    def get_last_outbound(self, chat_id: str) -> OutboundMessage | None:
        row = self._db.get_chat_row(chat_id)
        if row is None or not row["latest_outbound_text"]:
            return None
        return OutboundMessage(chat_id=chat_id, text=row["latest_outbound_text"])

    def has_logged_outbound(self, chat_id: str, text: str) -> bool:
        row = self._db.get_chat_row(chat_id)
        return bool(row and row["latest_outbound_text"] == text)

    def has_waiting_telegram(self) -> bool:
        return self._db.count_waiting_telegram() > 0

    def mark_waiting_telegram(
        self,
        chat_id: str,
        message_id: int,
        context_json: str,
        classification_json: str,
    ) -> None:
        self._db.set_pending_telegram(chat_id, message_id, context_json, classification_json)

    def consume_telegram_reply(
        self,
        telegram_message_id: int | None,
    ) -> ConsumedTelegramReply | None:
        conn = self._db.conn
        with conn:
            if telegram_message_id is not None:
                row = self._db.get_chat_row_by_telegram_message_id(telegram_message_id)
            else:
                waiting = self._db.list_waiting_telegram_rows()
                row = waiting[0] if len(waiting) == 1 else None

            if row is None or not row["pending_context"] or not row["pending_classification"]:
                return None

            chat_id = row["chat_id"]
            conn.execute(
                """
                UPDATE chats SET
                    waiting_telegram = 0,
                    telegram_message_id = NULL,
                    pending_context = NULL,
                    pending_classification = NULL
                WHERE chat_id = ?
                """,
                (chat_id,),
            )

        return ConsumedTelegramReply(
            chat_id=chat_id,
            pending_context=row["pending_context"],
            pending_classification=row["pending_classification"],
        )

    def should_allow_agentic_response(
        self,
        chat_id: str,
        messages: Sequence[ChatMessageLike],
    ) -> AgenticAccessDecision:
        row = self._db.get_chat_row(chat_id)
        if row is not None and row["waiting_telegram"]:
            return AgenticAccessDecision(False, "waiting_telegram")

        if self.is_blacklisted(chat_id):
            return AgenticAccessDecision(False, "blacklisted")

        if not messages:
            return AgenticAccessDecision(False, "no_messages")

        latest = messages[-1]
        if _is_seller(latest.sender):
            return AgenticAccessDecision(False, "latest_sender_seller")

        if not _is_buyer(latest.sender):
            return AgenticAccessDecision(False, "latest_sender_not_buyer")

        latest_seller: ChatMessageLike | None = None
        for message in reversed(messages):
            if _is_seller(message.sender):
                latest_seller = message
                break

        if latest_seller is None:
            return AgenticAccessDecision(True, "new_chat")

        outbound = self.get_last_outbound(chat_id)
        if outbound is None or latest_seller.text != outbound.text:
            reason = "human_override" if outbound is None else "seller_message_mismatch"
            self.blacklist_chat(chat_id, reason=reason)
            return AgenticAccessDecision(False, reason)

        return AgenticAccessDecision(True, "awaiting_buyer_reply")
