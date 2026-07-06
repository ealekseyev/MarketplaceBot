from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .database import Database

LISTING_CACHE_TTL_SECONDS = 6 * 60 * 60


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ListingCache:
    """SQLite-backed listing payload cache with lazy expiry."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, listing_id: str) -> dict[str, Any] | None:
        row = self._db.get_listing_row(listing_id)
        if row is None:
            return None

        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at <= _utc_now():
            self._db.delete_listing(listing_id)
            return None

        return json.loads(row["data"])

    def put(self, listing_id: str, payload: dict[str, Any]) -> None:
        expires_at = _utc_now() + timedelta(seconds=LISTING_CACHE_TTL_SECONDS)
        self._db.upsert_listing(listing_id, json.dumps(payload), expires_at.isoformat())
