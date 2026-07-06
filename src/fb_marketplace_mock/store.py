from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from fb_marketplace.helpers import build_chat_url, extract_listing_id, normalize_listing_url
from fb_marketplace.models import (
    ChatDetail,
    ChatMessage,
    ChatSummary,
    ListingDetail,
    MessageSender,
)
from fb_marketplace.timeparse import age_seconds

DEFAULT_DB_PATH = Path("/tmp/fb-bot-mock-marketplace.sqlite")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    listing_id TEXT PRIMARY KEY NOT NULL,
    title TEXT,
    description TEXT,
    price TEXT,
    condition TEXT,
    seller_name TEXT,
    location_city TEXT,
    location_state TEXT
);

CREATE TABLE IF NOT EXISTS chats (
    chat_id TEXT PRIMARY KEY NOT NULL,
    listing_id TEXT NOT NULL,
    buyer_name TEXT NOT NULL,
    unread INTEGER NOT NULL DEFAULT 1,
    latest_message_sender TEXT NOT NULL DEFAULT 'buyer',
    latest_message_preview TEXT,
    FOREIGN KEY (listing_id) REFERENCES listings(listing_id)
);

CREATE TABLE IF NOT EXISTS messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    sender TEXT NOT NULL,
    text TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id);
"""


def _default_db_path() -> Path:
    return Path(os.environ.get("FB_MOCK_MARKETPLACE_DB", DEFAULT_DB_PATH))


def _parse_sent_at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


class MockStore:
    """SQLite-backed mock Facebook Marketplace state."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def close(self) -> None:
        self._conn.close()

    def seed(self, listings: list[dict[str, str]]) -> int:
        inserted = 0
        for item in listings:
            listing_id = item["listing_id"]
            row = self._conn.execute(
                "SELECT 1 FROM listings WHERE listing_id = ?",
                (listing_id,),
            ).fetchone()
            if row is not None:
                continue
            self._conn.execute(
                """
                INSERT INTO listings (
                    listing_id, title, description, price, condition,
                    seller_name, location_city, location_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    listing_id,
                    item.get("title"),
                    item.get("description"),
                    item.get("price"),
                    item.get("condition"),
                    item.get("seller_name"),
                    item.get("location_city"),
                    item.get("location_state"),
                ),
            )
            inserted += 1
        self._conn.commit()
        return inserted

    def list_listings(self) -> list[ListingDetail]:
        rows = self._conn.execute(
            "SELECT * FROM listings ORDER BY listing_id"
        ).fetchall()
        return [self._row_to_listing(row) for row in rows]

    def get_listing(self, listing_url_or_id: str) -> ListingDetail:
        listing_id = extract_listing_id(listing_url_or_id) or listing_url_or_id.strip()
        row = self._conn.execute(
            "SELECT * FROM listings WHERE listing_id = ?",
            (listing_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Listing not found: {listing_id}")
        return self._row_to_listing(row)

    def list_chats(self, *, limit: int | None = None) -> list[ChatSummary]:
        query = "SELECT * FROM chats ORDER BY chat_id DESC"
        if limit is not None:
            query += f" LIMIT {int(limit)}"
        rows = self._conn.execute(query).fetchall()
        return [self._row_to_summary(row) for row in rows]

    def list_inbox_chats(self, *, limit: int | None = None) -> list[ChatSummary]:
        query = """
            SELECT * FROM chats
            WHERE unread = 1 AND latest_message_sender = 'buyer'
            ORDER BY chat_id DESC
        """
        if limit is not None:
            query += f" LIMIT {int(limit)}"
        rows = self._conn.execute(query).fetchall()
        return [self._row_to_summary(row) for row in rows]

    def get_chat(self, chat_id: str) -> ChatDetail:
        row = self._conn.execute(
            "SELECT * FROM chats WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Chat not found: {chat_id}")

        listing_row = self._conn.execute(
            "SELECT title FROM listings WHERE listing_id = ?",
            (row["listing_id"],),
        ).fetchone()
        listing_name = listing_row["title"] if listing_row else None
        listing_url = normalize_listing_url(row["listing_id"])

        summary = self._row_to_summary(row, listing_name=listing_name, listing_url=listing_url)
        messages = self._messages_for_chat(chat_id)

        return ChatDetail(
            summary=summary,
            buyer_name=row["buyer_name"],
            listing_name=listing_name,
            listing_url=listing_url,
            messages=messages,
        )

    def send_seller_message(self, chat_id: str, text: str) -> None:
        stripped = text.strip()
        if not stripped:
            raise ValueError("text must be non-empty")

        row = self._conn.execute(
            "SELECT 1 FROM chats WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Chat not found: {chat_id}")

        sent_at = _now_iso()
        self._conn.execute(
            """
            INSERT INTO messages (chat_id, sender, text, sent_at)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, MessageSender.SELLER.value, stripped, sent_at),
        )
        self._conn.execute(
            """
            UPDATE chats
            SET unread = 0,
                latest_message_sender = ?,
                latest_message_preview = ?
            WHERE chat_id = ?
            """,
            (MessageSender.SELLER.value, stripped, chat_id),
        )
        self._conn.commit()

    def add_buyer_message(
        self,
        listing_id: str,
        buyer_name: str,
        text: str,
    ) -> str:
        stripped = text.strip()
        if not stripped:
            raise ValueError("text must be non-empty")

        listing_row = self._conn.execute(
            "SELECT 1 FROM listings WHERE listing_id = ?",
            (listing_id,),
        ).fetchone()
        if listing_row is None:
            raise KeyError(f"Listing not found: {listing_id}")

        chat_row = self._conn.execute(
            "SELECT chat_id FROM chats WHERE listing_id = ? AND buyer_name = ?",
            (listing_id, buyer_name),
        ).fetchone()

        if chat_row is None:
            chat_id = self._next_chat_id()
            self._conn.execute(
                """
                INSERT INTO chats (
                    chat_id, listing_id, buyer_name, unread,
                    latest_message_sender, latest_message_preview
                ) VALUES (?, ?, ?, 1, ?, ?)
                """,
                (chat_id, listing_id, buyer_name, MessageSender.BUYER.value, stripped),
            )
        else:
            chat_id = chat_row["chat_id"]
            self._conn.execute(
                """
                UPDATE chats
                SET unread = 1,
                    latest_message_sender = ?,
                    latest_message_preview = ?
                WHERE chat_id = ?
                """,
                (MessageSender.BUYER.value, stripped, chat_id),
            )

        sent_at = _now_iso()
        self._conn.execute(
            """
            INSERT INTO messages (chat_id, sender, text, sent_at)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, MessageSender.BUYER.value, stripped, sent_at),
        )
        self._conn.commit()
        return chat_id

    def _next_chat_id(self) -> str:
        row = self._conn.execute(
            """
            SELECT COALESCE(MAX(CAST(chat_id AS INTEGER)), 100000)
            FROM chats
            WHERE chat_id GLOB '[0-9]*'
            """
        ).fetchone()
        return str(int(row[0]) + 1)

    def _messages_for_chat(self, chat_id: str) -> list[ChatMessage]:
        rows = self._conn.execute(
            """
            SELECT message_id, sender, text, sent_at
            FROM messages
            WHERE chat_id = ?
            ORDER BY message_id
            """,
            (chat_id,),
        ).fetchall()

        messages: list[ChatMessage] = []
        for row in rows:
            sent_at = _parse_sent_at(row["sent_at"])
            messages.append(
                ChatMessage(
                    sender=MessageSender(row["sender"]),
                    text=row["text"],
                    message_id=str(row["message_id"]),
                    sent_at=sent_at,
                    age_seconds=age_seconds(sent_at),
                )
            )
        return messages

    def _row_to_listing(self, row: sqlite3.Row) -> ListingDetail:
        url = normalize_listing_url(row["listing_id"]) or ""
        return ListingDetail(
            url=url,
            title=row["title"],
            description=row["description"],
            price=row["price"],
            condition=row["condition"],
            seller_name=row["seller_name"],
            location_city=row["location_city"],
            location_state=row["location_state"],
        )

    def _row_to_summary(
        self,
        row: sqlite3.Row,
        *,
        listing_name: str | None = None,
        listing_url: str | None = None,
    ) -> ChatSummary:
        if listing_url is None:
            listing_url = normalize_listing_url(row["listing_id"])
        if listing_name is None:
            listing_row = self._conn.execute(
                "SELECT title FROM listings WHERE listing_id = ?",
                (row["listing_id"],),
            ).fetchone()
            listing_name = listing_row["title"] if listing_row else None

        latest_msg = self._conn.execute(
            """
            SELECT sent_at FROM messages
            WHERE chat_id = ?
            ORDER BY message_id DESC
            LIMIT 1
            """,
            (row["chat_id"],),
        ).fetchone()
        latest_at = _parse_sent_at(latest_msg["sent_at"]) if latest_msg else None

        return ChatSummary(
            chat_id=row["chat_id"],
            chat_url=build_chat_url(row["chat_id"]),
            unread=bool(row["unread"]),
            latest_message_sender=MessageSender(row["latest_message_sender"]),
            latest_message_preview=row["latest_message_preview"],
            latest_message_at=latest_at,
            latest_message_age_seconds=age_seconds(latest_at),
            buyer_name=row["buyer_name"],
            listing_name=listing_name,
            listing_url=listing_url,
        )
