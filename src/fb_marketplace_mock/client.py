from __future__ import annotations

import logging
from typing import Any, Protocol

from fb_marketplace.helpers import extract_listing_id, normalize_listing_url
from fb_marketplace.models import ChatDetail, ChatSummary, ListingDetail, SessionConfig

from .store import MockStore

logger = logging.getLogger(__name__)


class ListingCacheLike(Protocol):
    def get(self, listing_id: str) -> dict[str, Any] | None: ...

    def put(self, listing_id: str, payload: dict[str, Any]) -> None: ...


class FacebookMarketplaceClient:
    """Thin async delegate over MockStore."""

    def __init__(
        self,
        config: SessionConfig,
        *,
        listing_cache: ListingCacheLike | None = None,
    ) -> None:
        self._config = config
        self._store = MockStore()
        self._listing_cache = listing_cache

    async def __aenter__(self) -> FacebookMarketplaceClient:
        await self.start()
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()

    async def start(self) -> None:
        logger.debug("Mock FacebookMarketplaceClient started (db=%s)", self._store.db_path)

    async def close(self) -> None:
        self._store.close()
        logger.debug("Mock FacebookMarketplaceClient closed")

    async def list_chats(self, limit: int | None = None) -> list[ChatSummary]:
        logger.info("list_chats: start (limit=%s)", limit)
        return self._store.list_chats(limit=limit)

    async def get_chat(self, chat_id: str) -> ChatDetail:
        logger.info("get_chat: start (chat_id=%s)", chat_id)
        return self._store.get_chat(chat_id)

    async def get_listing(self, listing_url: str) -> ListingDetail:
        normalized_url = normalize_listing_url(listing_url)
        if normalized_url is None:
            raise ValueError("listing_url must be non-empty")

        listing_id = extract_listing_id(normalized_url)
        if listing_id and self._listing_cache is not None:
            cached = self._listing_cache.get(listing_id)
            if cached is not None:
                detail = ListingDetail.from_dict(cached)
                logger.info("get_listing: cache hit for %s (title=%r)", listing_id, detail.title)
                return detail

        detail = self._store.get_listing(normalized_url)
        if listing_id and self._listing_cache is not None:
            self._listing_cache.put(listing_id, detail.to_dict())
        return detail

    async def send_message(self, chat_id: str, text: str) -> None:
        logger.info("send_message: start (chat_id=%s, chars=%d)", chat_id, len(text))
        self._store.send_seller_message(chat_id, text)

    async def mark_read(self, chat_id: str) -> None:
        self._store.mark_read(chat_id)
