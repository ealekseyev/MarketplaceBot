# MarketplaceSession SDK

Thin async wrapper over `FacebookMarketplaceClient`. Import from `fb_marketplace`.

## Implemented today

| Symbol | Status |
|--------|--------|
| `FacebookMarketplaceClient` | Playwright client with persistent Chromium profile |
| `MarketplaceSession` | SDK wrapper with listing id normalization |
| `SessionConfig` | Browser + auth settings |
| `list_chats(limit?)` | Marketplace inbox rows → `list[ChatSummary]` |
| `get_chat(chat_id)` | Full thread after scroll-up → `ChatDetail` |
| `get_listing(listing_url_or_id)` | Listing page scrape → `ListingDetail` (accepts URL or numeric id) |
| `get_chat_listing(chat_id)` | Convenience on client: chat → listing URL → `ListingDetail \| None` |

Context manager supported: `async with MarketplaceSession(config) as session`.

No message sending yet. CLI: `fb-marketplace inbox|chat|listing`.

## Usage

```python
import asyncio
from fb_marketplace import SessionConfig, MarketplaceSession, facebook_credentials_from_env

async def main() -> None:
    email, password = facebook_credentials_from_env(".env")
    config = SessionConfig(
        user_data_dir="./.browser-profile",
        facebook_email=email,
        facebook_password=password,
        manual_login=True,
        headless=False,
    )
    async with MarketplaceSession(config) as session:
        for chat in await session.list_chats(limit=20):
            if chat.unread and chat.latest_message_sender == "buyer":
                detail = await session.get_chat(chat.chat_id)
                listing = await session.get_listing(chat.listing_url) if chat.listing_url else None
                print(chat.buyer_name, detail.messages[-1].text, listing.title if listing else None)

asyncio.run(main())
```

## Return shapes

### `ChatSummary`

Inbox row metadata. `to_dict()` returns a stable JSON shape.

| Field | Type | Notes |
|-------|------|-------|
| `chat_id` | `str` | FB thread id or synthetic `mp_row_*` |
| `chat_url` | `str` | Direct thread URL |
| `unread` | `bool` | Bold preview in inbox |
| `latest_message_sender` | `"buyer" \| "seller" \| "unknown"` | From preview heuristics |
| `latest_message_preview` | `str \| None` | |
| `latest_message_at` | `datetime \| None` | Parsed when detectable |
| `buyer_name` | `str \| None` | |
| `listing_name` | `str \| None` | |
| `listing_url` | `str \| None` | |

`to_dict()` keys: `chat_id`, `chat_url`, `buyer_name`, `latest_message` (`sender`, `sent_at`, `read_by_me`, `preview`), `listing` (`id`, `url`, `name`).

### `ChatDetail`

| Field | Type | Notes |
|-------|------|-------|
| `summary` | `ChatSummary` | Base inbox fields |
| `buyer_name` | `str \| None` | From thread header |
| `listing_name` | `str \| None` | |
| `listing_url` | `str \| None` | |
| `messages` | `list[ChatMessage]` | Full visible history |

Each `ChatMessage`: `sender`, `text`, `message_id?`, `sent_at?`, `age_seconds?`.

`to_dict()` keys: `chat_id`, `chat_url`, `buyer_name`, `listing`, `messages`.

### `ListingDetail`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `str \| None` | From URL |
| `url` | `str` | |
| `title` | `str \| None` | |
| `description` | `str \| None` | |
| `price` | `str \| None` | e.g. `$700` |
| `condition` | `str \| None` | e.g. `Used - Good` |
| `seller_name` | `str \| None` | |
| `location` | `{city, state}` | |

## Notes

- Read-only extraction layer; DOM heuristics break when Facebook changes markup.
- `MessageSender.SELLER` does not distinguish bot vs human seller messages — that belongs in `fb_store`.
- Install: `pip install -e ./src/fb_marketplace`.
