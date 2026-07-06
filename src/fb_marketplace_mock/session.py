from __future__ import annotations

import logging
import re

from fb_marketplace.helpers import normalize_facebook_url, normalize_listing_url
from fb_marketplace.models import ChatDetail, ChatSummary, ListingDetail, SessionConfig

from .client import FacebookMarketplaceClient, ListingCacheLike

logger = logging.getLogger(__name__)


def _normalize_listing_reference(listing_url_or_id: str) -> str:
    stripped = listing_url_or_id.strip()
    if re.fullmatch(r"\d+", stripped):
        return f"https://www.facebook.com/marketplace/item/{stripped}"
    normalized = normalize_listing_url(stripped) or normalize_facebook_url(stripped)
    if normalized is None:
        raise ValueError(f"Invalid listing reference: {listing_url_or_id!r}")
    return normalized


class MarketplaceSession:
    """Thin async wrapper over mock FacebookMarketplaceClient."""

    def __init__(
        self,
        config: SessionConfig,
        *,
        listing_cache: ListingCacheLike | None = None,
    ) -> None:
        self._client = FacebookMarketplaceClient(config, listing_cache=listing_cache)

    async def __aenter__(self) -> MarketplaceSession:
        logger.debug("MarketplaceSession: starting mock client")
        await self._client.start()
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()

    async def close(self) -> None:
        logger.debug("MarketplaceSession: closing mock client")
        await self._client.close()

    async def list_chats(self, limit: int | None = None) -> list[ChatSummary]:
        logger.debug("MarketplaceSession.list_chats(limit=%s)", limit)
        return await self._client.list_chats(limit=limit)

    async def get_chat(self, chat_id: str) -> ChatDetail:
        logger.debug("MarketplaceSession.get_chat(chat_id=%s)", chat_id)
        return await self._client.get_chat(chat_id)

    async def get_listing(self, listing_url_or_id: str) -> ListingDetail:
        logger.debug("MarketplaceSession.get_listing(%r)", listing_url_or_id)
        url = _normalize_listing_reference(listing_url_or_id)
        return await self._client.get_listing(url)

    async def send_message(self, chat_id: str, text: str) -> None:
        logger.debug("MarketplaceSession.send_message(chat_id=%s, chars=%d)", chat_id, len(text))
        return await self._client.send_message(chat_id, text)
