from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import ListingDetail

DEFAULT_DB_PATH = Path("./data/fb-listings.sqlite")
LISTING_CACHE_TTL_SECONDS = 6 * 60 * 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    listing_id TEXT PRIMARY KEY NOT NULL,
    data TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""


def _default_db_path() -> Path:
    return Path(os.environ.get("FB_LISTING_CACHE_PATH", DEFAULT_DB_PATH))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ListingCache:
    """Internal SQLite cache for scraped marketplace listing data."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ListingCache:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def get(self, listing_id: str) -> ListingDetail | None:
        row = self._conn.execute(
            "SELECT data, expires_at FROM listings WHERE listing_id = ?",
            (listing_id,),
        ).fetchone()
        if row is None:
            return None

        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at <= _utc_now():
            self._conn.execute(
                "DELETE FROM listings WHERE listing_id = ?",
                (listing_id,),
            )
            self._conn.commit()
            return None

        payload = json.loads(row["data"])
        return ListingDetail.from_dict(payload)

    def put(self, listing_id: str, detail: ListingDetail) -> None:
        expires_at = _utc_now() + timedelta(seconds=LISTING_CACHE_TTL_SECONDS)
        self._conn.execute(
            """
            INSERT INTO listings (listing_id, data, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(listing_id) DO UPDATE SET
                data = excluded.data,
                expires_at = excluded.expires_at
            """,
            (listing_id, json.dumps(detail.to_dict()), expires_at.isoformat()),
        )
        self._conn.commit()
