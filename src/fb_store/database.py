from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path("./data/fb-bot.sqlite")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id TEXT PRIMARY KEY NOT NULL,
    blacklisted INTEGER NOT NULL DEFAULT 0,
    latest_outbound_text TEXT,
    waiting_telegram INTEGER NOT NULL DEFAULT 0,
    telegram_message_id INTEGER,
    pending_context TEXT,
    pending_classification TEXT
);
CREATE INDEX IF NOT EXISTS idx_chats_telegram_message_id ON chats(telegram_message_id) WHERE waiting_telegram = 1;
CREATE TABLE IF NOT EXISTS listings (
    listing_id TEXT PRIMARY KEY NOT NULL,
    data TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""

_CHAT_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("waiting_telegram", "INTEGER NOT NULL DEFAULT 0"),
    ("telegram_message_id", "INTEGER"),
    ("pending_context", "TEXT"),
    ("pending_classification", "TEXT"),
)


def _default_db_path() -> Path:
    return Path(os.environ.get("FB_STORE_PATH", DEFAULT_DB_PATH))


class Database:
    """SQLite connection and thin CRUD for chats and listings."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate_chats()
        self._conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _migrate_chats(self) -> None:
        existing = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(chats)")
        }
        for column, definition in _CHAT_MIGRATIONS:
            if column not in existing:
                self._conn.execute(f"ALTER TABLE chats ADD COLUMN {column} {definition}")

    def get_chat_row(self, chat_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM chats WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()

    def get_chat_row_by_telegram_message_id(self, telegram_message_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT * FROM chats
            WHERE telegram_message_id = ? AND waiting_telegram = 1
            """,
            (telegram_message_id,),
        ).fetchone()

    def count_waiting_telegram(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM chats WHERE waiting_telegram = 1",
        ).fetchone()
        return int(row["n"]) if row is not None else 0

    def list_waiting_telegram_rows(self) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT * FROM chats WHERE waiting_telegram = 1",
            ).fetchall()
        )

    def upsert_blacklisted(self, chat_id: str) -> None:
        self._conn.execute(
            """
            INSERT INTO chats (chat_id, blacklisted)
            VALUES (?, 1)
            ON CONFLICT(chat_id) DO UPDATE SET blacklisted = 1
            """,
            (chat_id,),
        )
        self._conn.commit()

    def upsert_latest_outbound(self, chat_id: str, text: str) -> None:
        self._conn.execute(
            """
            INSERT INTO chats (chat_id, latest_outbound_text)
            VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET latest_outbound_text = excluded.latest_outbound_text
            """,
            (chat_id, text),
        )
        self._conn.commit()

    def set_pending_telegram(
        self,
        chat_id: str,
        message_id: int,
        context_json: str,
        classification_json: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO chats (
                chat_id, waiting_telegram, telegram_message_id,
                pending_context, pending_classification
            )
            VALUES (?, 1, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                waiting_telegram = 1,
                telegram_message_id = excluded.telegram_message_id,
                pending_context = excluded.pending_context,
                pending_classification = excluded.pending_classification
            """,
            (chat_id, message_id, context_json, classification_json),
        )
        self._conn.commit()

    def clear_pending_telegram(self, chat_id: str) -> None:
        self._conn.execute(
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
        self._conn.commit()

    def get_listing_row(self, listing_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT data, expires_at FROM listings WHERE listing_id = ?",
            (listing_id,),
        ).fetchone()

    def upsert_listing(self, listing_id: str, data: str, expires_at: str) -> None:
        self._conn.execute(
            """
            INSERT INTO listings (listing_id, data, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(listing_id) DO UPDATE SET
                data = excluded.data,
                expires_at = excluded.expires_at
            """,
            (listing_id, data, expires_at),
        )
        self._conn.commit()

    def delete_listing(self, listing_id: str) -> None:
        self._conn.execute(
            "DELETE FROM listings WHERE listing_id = ?",
            (listing_id,),
        )
        self._conn.commit()
