from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable


DEFAULT_DB_PATH = Path("./data/fb-bot.sqlite")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id TEXT PRIMARY KEY NOT NULL,
    blacklisted INTEGER NOT NULL DEFAULT 0,
    latest_outbound_text TEXT
);
"""


def _default_db_path() -> Path:
    return Path(os.environ.get("FB_STORE_PATH", DEFAULT_DB_PATH))


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


class ChatStore:
    """SQLite persistence for chat blacklist and latest bot outbound message."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ChatStore:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def is_allowed(self, chat_id: str) -> bool:
        return not self.is_blacklisted(chat_id)

    def blacklist_chat(self, chat_id: str, *, reason: str = "manual") -> None:
        """Permanently skip a chat. Reason is for callers only; not stored."""
        _ = reason
        self._conn.execute(
            """
            INSERT INTO chats (chat_id, blacklisted)
            VALUES (?, 1)
            ON CONFLICT(chat_id) DO UPDATE SET blacklisted = 1
            """,
            (chat_id,),
        )
        self._conn.commit()

    def is_blacklisted(self, chat_id: str) -> bool:
        row = self._conn.execute(
            "SELECT blacklisted FROM chats WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        return bool(row and row["blacklisted"])

    def record_outbound(self, chat_id: str, text: str) -> None:
        """Record the latest bot-sent message for a chat."""
        self._conn.execute(
            """
            INSERT INTO chats (chat_id, latest_outbound_text)
            VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET latest_outbound_text = excluded.latest_outbound_text
            """,
            (chat_id, text),
        )
        self._conn.commit()

    def log_outbound(self, message: OutboundMessage) -> None:
        self.record_outbound(message.chat_id, message.text)

    def get_last_outbound(self, chat_id: str) -> OutboundMessage | None:
        row = self._conn.execute(
            "SELECT latest_outbound_text FROM chats WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        if row is None or not row["latest_outbound_text"]:
            return None
        return OutboundMessage(chat_id=chat_id, text=row["latest_outbound_text"])

    def has_logged_outbound(self, chat_id: str, text: str) -> bool:
        row = self._conn.execute(
            "SELECT latest_outbound_text FROM chats WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        return bool(row and row["latest_outbound_text"] == text)

    def should_allow_agentic_response(
        self,
        chat_id: str,
        messages: Sequence[ChatMessageLike],
    ) -> AgenticAccessDecision:
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
