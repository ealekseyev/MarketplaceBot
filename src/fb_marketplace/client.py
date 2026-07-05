from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import replace
from datetime import datetime
from typing import Any

from playwright.async_api import (
    BrowserContext,
    Error as PlaywrightError,
    Locator,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from .helpers import (
    build_chat_url,
    extract_chat_id,
    extract_listing_id,
    guess_sender_from_preview,
    match_graphql_thread,
    normalize_facebook_url,
    normalize_listing_url,
    parse_listing_location,
    parse_marketplace_threads_from_graphql,
)
from .listing_cache import ListingCache
from .models import ChatDetail, ChatMessage, ChatSummary, ListingDetail, MessageSender, SessionConfig
from .timeparse import age_seconds, first_timestamp_in_text, parse_relative_timestamp

logger = logging.getLogger(__name__)

_LISTING_PAGE_READY_JS = r"""
() => {
  if (!/\/marketplace\/item\/\d+/.test(window.location.pathname || '')) {
    return false;
  }
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const text = document.body?.innerText || '';
  if (/no longer available/i.test(text)) {
    return true;
  }
  const hasH1 = Array.from(document.querySelectorAll('h1')).some(visible);
  const hasPrice = /\$[\d,]+/.test(text);
  const hasDetails = text.includes('Details');
  return hasH1 && (hasPrice || hasDetails);
}
"""

_LISTING_SCRAPE_JS = r"""
() => {
  const clean = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const inMainPanel = (el) => {
    const rect = el.getBoundingClientRect();
    const minX = Math.min(900, window.innerWidth * 0.25);
    return visible(el) && rect.x >= minX;
  };
  const prominentH1 = (el) => {
    const rect = el.getBoundingClientRect();
    return visible(el) && rect.width > 80;
  };

  const titleNode = Array.from(document.querySelectorAll('h1')).find(inMainPanel)
    || Array.from(document.querySelectorAll('h1')).find(prominentH1);
  const title = titleNode ? clean(titleNode.textContent) : null;

  const lines = (document.body?.innerText || '')
    .split('\n')
    .map(clean)
    .filter(Boolean);

  const priceFromLines = lines.find((line) => /^\$[\d,]+(?:\.\d{2})?$/.test(line)) || null;

  let condition = null;
  let description = null;
  let locationLine = null;

  const detailsIndex = lines.findIndex((line) => line === 'Details');
  if (detailsIndex >= 0) {
    for (let index = detailsIndex + 1; index < lines.length; index += 1) {
      const line = lines[index];
      if (line === 'Condition') {
        continue;
      }
      if (/^Used - /i.test(line) || /^(Like new|New|Fair|Good)$/i.test(line)) {
        if (!condition) {
          condition = line;
        }
        continue;
      }
      if (/Location is approximate$/i.test(line) || / · Location is approximate$/i.test(line)) {
        locationLine = line.replace(/ · Location is approximate$/i, '').trim();
        break;
      }
      if (line === 'Seller information' || line === 'Seller details') {
        break;
      }
      if (!description && line !== title && !/^Listed /i.test(line) && !/^\$/.test(line)) {
        description = line;
      }
    }
  }

  const listedLine = lines.find((line) => /^Listed .+ in .+, [A-Z]{2}$/i.test(line));
  const listedLocation = listedLine
    ? (listedLine.match(/ in (.+)$/i) || [])[1] || null
    : null;

  const sellerLink = Array.from(document.querySelectorAll('a[href*="/marketplace/profile/"]'))
    .filter((anchor) => visible(anchor) && inMainPanel(anchor))
    .map((anchor) => clean(anchor.textContent))
    .find((text) => text && text !== 'Seller details')
    || Array.from(document.querySelectorAll('a[href*="/marketplace/profile/"]'))
      .filter(visible)
      .map((anchor) => clean(anchor.textContent))
      .find((text) => text && text !== 'Seller details');

  return {
    title,
    description,
    condition,
    priceText: priceFromLines,
    locationLine: locationLine || listedLocation,
    sellerName: sellerLink || null,
  };
}
"""


_CONVERSATION_LINK_SELECTOR = 'a[href*="/messages/t/"], a[href*="thread_id="]'
_LISTING_LINK_SELECTOR = 'a[href*="/marketplace/item/"]'
_HEADING_SELECTOR = 'h1, h2, h3, [role="heading"]'


class FacebookMarketplaceClient:
    def __init__(self, config: SessionConfig) -> None:
        self._config = config
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._listing_cache: ListingCache | None = None

    def _get_listing_cache(self) -> ListingCache:
        if self._listing_cache is None:
            self._listing_cache = ListingCache()
        return self._listing_cache

    async def __aenter__(self) -> "FacebookMarketplaceClient":
        await self.start()
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()

    async def start(self) -> None:
        if self._context is not None:
            return

        playwright: Playwright | None = None
        context: BrowserContext | None = None
        try:
            playwright = await async_playwright().start()
            assert playwright is not None
            browser_type = playwright.chromium
            context = await browser_type.launch_persistent_context(
                self._config.user_data_dir,
                channel=self._config.browser_channel,
                headless=self._config.headless,
                slow_mo=self._config.slow_mo_ms,
            )
            assert context is not None
            page = context.pages[0] if context.pages else await context.new_page()
            page.set_default_timeout(self._config.timeout_ms)
        except PlaywrightError as exc:
            if context is not None:
                await context.close()
            if playwright is not None:
                await playwright.stop()
            message = str(exc)
            if "Opening in existing browser session" in message:
                raise RuntimeError(
                    f"Browser profile is already in use: {self._config.user_data_dir}. Close the existing Chromium/Facebook bot window, then rerun the command."
                ) from exc
            if "ERR_TOO_MANY_REDIRECTS" in message:
                raise RuntimeError(
                    "Facebook redirected the session before inbox load. Use valid Facebook credentials in .env or rerun with --headful and complete the login flow."
                ) from exc
            raise
        except Exception:
            if context is not None:
                await context.close()
            if playwright is not None:
                await playwright.stop()
            raise

        self._playwright = playwright
        self._context = context
        self._page = page

    async def close(self) -> None:
        if self._listing_cache is not None:
            self._listing_cache.close()
            self._listing_cache = None
        if self._page is not None:
            try:
                await self._page.goto("about:blank", wait_until="commit", timeout=2_000)
            except PlaywrightError:
                pass
        if self._context is not None:
            await self._context.close()
            self._context = None
            self._page = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def list_chats(self, limit: int | None = None) -> list[ChatSummary]:
        logger.info("list_chats: start (limit=%s)", limit)
        page = await self._goto_inbox()
        graphql_bodies: list[str] = []

        async def capture_graphql(response: Any) -> None:
            if "/api/graphql" not in response.url:
                return
            try:
                graphql_bodies.append(await response.text())
            except PlaywrightError:
                return

        page.on("response", capture_graphql)
        try:
            if not graphql_bodies:
                await page.reload(wait_until="domcontentloaded")
            await self._wait_for_inbox(page)
            await page.wait_for_timeout(2_000)
            if limit:
                await self._scroll_inbox_to_load_chats(page, limit)
        finally:
            page.remove_listener("response", capture_graphql)

        graphql_threads = parse_marketplace_threads_from_graphql("\n".join(graphql_bodies))
        logger.debug(
            "list_chats: captured %d graphql response(s), parsed %d thread(s)",
            len(graphql_bodies),
            len(graphql_threads),
        )
        raw_rows = await page.evaluate(
            r"""
            () => {
              const isBoldText = (node) => {
                if (!node) return false;
                if (node.tagName === 'STRONG' || node.tagName === 'B') return true;
                if (node.closest('strong, b')) return true;
                const style = window.getComputedStyle(node);
                const weight = parseInt(style.fontWeight, 10);
                return style.fontWeight === 'bold' || (!Number.isNaN(weight) && weight >= 600);
              };
              const rowIsBold = (row) => {
                const nodes = row.querySelectorAll('span, div[dir="auto"], strong, b');
                for (const node of nodes) {
                  const text = (node.textContent || '').trim();
                  if (!text || text.length > 200) continue;
                  if (isBoldText(node)) return true;
                }
                return false;
              };
              const isChatButton = (row) => {
                const rect = row.getBoundingClientRect();
                const rowText = (row.textContent || '').trim();
                return rect.x > 200 && rect.width > 200 && rect.height >= 40 && rowText.length > 10;
              };
              const findInboxScroller = () => {
                const candidates = Array.from(document.querySelectorAll('div, section, main, ul')).filter((node) => {
                  const style = window.getComputedStyle(node);
                  const rect = node.getBoundingClientRect();
                  const hasThreads = node.querySelector('a[href*="/messages/t/"]')
                    || Array.from(node.querySelectorAll('div[role="button"][tabindex="0"]')).some(isChatButton);
                  const isScrollable = ['auto', 'scroll', 'overlay'].includes(style.overflowY)
                    || node.scrollHeight > node.clientHeight + 20;
                  return hasThreads && isScrollable && rect.width > 200 && rect.height > 100;
                });
                candidates.sort((a, b) => b.scrollHeight - a.scrollHeight);
                return candidates[0] || null;
              };

              const root = findInboxScroller() || document;

              const anchors = Array.from(root.querySelectorAll('a[href*="/messages/t/"], a[href*="thread_id="]'));
              const anchorRows = anchors
                .filter((anchor) => /\/messages\/t\/[^/?#]+/.test(anchor.getAttribute('href') || '') || /thread_id=([^&#]+)/.test(anchor.getAttribute('href') || ''))
                .map((anchor, index) => {
                  const row = anchor.closest('[role="row"], [role="listitem"], li, section, article') || anchor;
                  const rect = row.getBoundingClientRect();
                  if (rect.x < 200 || rect.width < 200) {
                    return null;
                  }
                  const listingAnchor = row.querySelector('a[href*="/marketplace/item/"]');
                  const textParts = Array.from(row.querySelectorAll('span, div[dir="auto"], strong'))
                    .map((node) => (node.textContent || '').trim())
                    .filter(Boolean)
                    .filter((text, partIndex, all) => all.indexOf(text) === partIndex);
                  return {
                    index,
                    href: anchor.href,
                    anchorText: (anchor.textContent || '').trim(),
                    rowText: (row.textContent || '').trim(),
                    textParts,
                    rowHtml: row.innerHTML || '',
                    ariaLabel: row.getAttribute('aria-label') || anchor.getAttribute('aria-label') || '',
                    listingHref: listingAnchor ? listingAnchor.href : '',
                    listingName: listingAnchor ? (listingAnchor.textContent || listingAnchor.getAttribute('aria-label') || '').trim() : '',
                    x: rect.x,
                    y: rect.y,
                    width: rect.width,
                    height: rect.height,
                    isBold: rowIsBold(row),
                    source: 'anchor',
                  };
                })
                .filter(Boolean);

              const buttonRows = Array.from(root.querySelectorAll('div[role="button"][tabindex="0"]'))
                .map((row, index) => {
                  const rect = row.getBoundingClientRect();
                  const rowText = (row.textContent || '').trim();
                  const listingAnchor = row.querySelector('a[href*="/marketplace/item/"]');
                  const textParts = Array.from(row.querySelectorAll('span, div[dir="auto"], strong'))
                    .map((node) => (node.textContent || '').trim())
                    .filter(Boolean)
                    .filter((text, partIndex, all) => all.indexOf(text) === partIndex);
                  return {
                    index,
                    href: '',
                    anchorText: rowText,
                    rowText,
                    textParts,
                    rowHtml: row.innerHTML || '',
                    ariaLabel: row.getAttribute('aria-label') || '',
                    listingHref: listingAnchor ? listingAnchor.href : '',
                    listingName: listingAnchor ? (listingAnchor.textContent || listingAnchor.getAttribute('aria-label') || '').trim() : '',
                    x: rect.x,
                    y: rect.y,
                    width: rect.width,
                    height: rect.height,
                    isBold: rowIsBold(row),
                    source: 'button',
                  };
                })
                .filter((row) => row.x > 200 && row.width > 200 && row.height >= 40 && row.rowText.length > 10);

              return [...anchorRows, ...buttonRows]
                .sort((a, b) => (a.y || a.index) - (b.y || b.index));
            }
            """
        )

        logger.info("list_chats: extracted %d inbox row(s) from DOM", len(raw_rows))
        now = None
        summaries: list[ChatSummary] = []
        seen_chat_ids: set[str] = set()
        for row in raw_rows:
            row_text = _clean_text(row.get("rowText"))
            text_parts = [_clean_text(part) for part in row.get("textParts", []) if _clean_text(part)]
            chat_id = extract_chat_id(row.get("href"))
            buyer_name, listing_name, preview = _guess_summary_text_fields(text_parts, row_text)
            listing_url = normalize_listing_url(row.get("listingHref"))
            graphql_thread = match_graphql_thread(graphql_threads, buyer_name, preview)
            if graphql_thread:
                chat_id = graphql_thread["thread_fbid"]
                listing_name = listing_name or graphql_thread.get("listing_title")
                item_id = graphql_thread.get("listing_item_id")
                if item_id and not listing_url:
                    listing_url = f"https://www.facebook.com/marketplace/item/{item_id}"
            elif not chat_id and row.get("source") == "button":
                chat_id = _marketplace_row_chat_id(int(row.get("index") or 0), row_text)
            if not chat_id or chat_id in seen_chat_ids:
                continue

            seen_chat_ids.add(chat_id)
            listing_name = _clean_text(row.get("listingName")) or listing_name
            if _is_system_chat(buyer_name, preview):
                continue
            latest_label, latest_at = first_timestamp_in_text(
                "\n".join(filter(None, [row.get("ariaLabel"), *text_parts, row_text])),
                now=now,
            )
            unread = bool(row.get("isBold"))
            sender = guess_sender_from_preview(preview, buyer_name, unread=unread)

            summaries.append(
                ChatSummary(
                    chat_id=chat_id,
                    chat_url=normalize_facebook_url(row.get("href")) or build_chat_url(chat_id),
                    unread=unread,
                    latest_message_sender=sender,
                    latest_message_preview=preview,
                    latest_message_label=latest_label,
                    latest_message_at=latest_at,
                    latest_message_age_seconds=age_seconds(latest_at),
                    buyer_name=buyer_name,
                    listing_name=listing_name,
                    listing_url=listing_url,
                    raw_text_parts=text_parts,
                )
            )

        result = summaries[:limit] if limit else summaries
        logger.info("list_chats: built %d chat summary(ies)", len(result))
        return result

    async def get_chat(self, chat_id: str) -> ChatDetail:
        logger.info("get_chat: start (chat_id=%s)", chat_id)
        page = self._require_page()
        if chat_id.startswith("mp_row_"):
            logger.debug("get_chat: navigating via marketplace row click (chat_id=%s)", chat_id)
            summary = await self._summary_for_marketplace_row_chat(chat_id)
            await self._click_marketplace_row_chat(page, chat_id)
        else:
            chat_url = build_chat_url(chat_id)
            logger.debug("get_chat: navigating to %s", chat_url)
            summary = ChatSummary(
                chat_id=chat_id,
                chat_url=chat_url,
                unread=False,
                latest_message_sender=MessageSender.UNKNOWN,
            )
            await self._open_url_with_auth(page, chat_url)
        await page.wait_for_timeout(2_000)
        logger.debug("get_chat: waiting for chat UI")
        await self._wait_for_chat(page)

        logger.debug("get_chat: scrolling thread to start")
        await self._scroll_thread_to_start(page)

        buyer_name, listing_name, listing_url = await self._extract_thread_metadata(page)
        logger.debug(
            "get_chat: metadata buyer=%r listing=%r url=%s",
            buyer_name,
            listing_name,
            listing_url or "(none)",
        )
        messages = await self._extract_messages(page)
        logger.info("get_chat: extracted %d message(s) for chat_id=%s", len(messages), chat_id)

        updated_summary = replace(
            summary,
            buyer_name=buyer_name or summary.buyer_name,
            listing_name=listing_name or summary.listing_name,
            listing_url=listing_url or summary.listing_url,
        )

        return ChatDetail(
            summary=updated_summary,
            buyer_name=buyer_name or summary.buyer_name,
            listing_name=listing_name or summary.listing_name,
            listing_url=listing_url or summary.listing_url,
            messages=messages,
        )

    async def get_listing(self, listing_url: str) -> ListingDetail:
        normalized_url = normalize_listing_url(listing_url)
        if normalized_url is None:
            raise ValueError("listing_url must be non-empty")

        listing_id = extract_listing_id(normalized_url)
        if listing_id:
            cached = self._get_listing_cache().get(listing_id)
            if cached is not None:
                logger.info(
                    "get_listing: cache hit for %s (title=%r)",
                    listing_id,
                    cached.title,
                )
                return cached
            logger.debug("get_listing: cache miss for %s", listing_id)

        page = self._require_page()
        logger.info("get_listing: navigating to %s", normalized_url)
        await self._open_url_with_auth(page, normalized_url, wait_until="commit")
        if not _is_marketplace_listing_url(page.url, normalized_url):
            logger.debug("get_listing: URL mismatch after auth; retrying goto (current=%s)", page.url)
            await self._safe_goto(page, normalized_url, wait_until="commit")
            await page.wait_for_timeout(1_000)
        logger.debug("get_listing: waiting for listing page ready")
        await self._wait_for_listing(page)

        raw = await page.evaluate(_LISTING_SCRAPE_JS)
        logger.info(
            "get_listing: scraped title=%r price=%s",
            raw.get("title"),
            raw.get("priceText") or "(none)",
        )

        location_city, location_state = parse_listing_location(raw.get("locationLine"))

        detail = ListingDetail(
            url=normalized_url,
            title=raw.get("title"),
            description=raw.get("description"),
            price=raw.get("priceText"),
            condition=raw.get("condition"),
            seller_name=raw.get("sellerName"),
            location_city=location_city,
            location_state=location_state,
        )
        if listing_id:
            self._get_listing_cache().put(listing_id, detail)
            logger.debug("get_listing: cached %s", listing_id)
        return detail

    async def get_chat_listing(self, chat_id: str) -> ListingDetail | None:
        detail = await self.get_chat(chat_id)
        if not detail.listing_url:
            return None
        return await self.get_listing(detail.listing_url)

    async def send_message(self, chat_id: str, text: str) -> None:
        stripped = _clean_text(text)
        if not stripped:
            raise ValueError("text must be non-empty")

        logger.info("send_message: start (chat_id=%s, chars=%d)", chat_id, len(stripped))
        page = self._require_page()
        logger.debug("send_message: navigating to chat")
        await self._navigate_to_chat(page, chat_id)
        await self._wait_for_chat(page)

        composer = await self._pick_composer(page)
        logger.debug("send_message: composer found")
        await composer.click()
        await composer.fill(stripped)
        cleared = await self._submit_composer_message(page, composer)
        if cleared:
            logger.info("send_message: message sent (composer cleared)")
            return
        if await self._message_visible_from_you(page, stripped):
            logger.info("send_message: message sent (verified in thread)")
            return
        logger.error("send_message: failed to confirm delivery for chat_id=%s", chat_id)
        raise RuntimeError(
            "Could not send the message. The composer still contains text and the sent message was not found in the thread."
        )

    async def _navigate_to_chat(self, page: Page, chat_id: str) -> None:
        if chat_id.startswith("mp_row_"):
            await self._click_marketplace_row_chat(page, chat_id)
            return
        if f"/messages/t/{chat_id}" not in page.url:
            await self._open_url_with_auth(page, build_chat_url(chat_id))
            await page.wait_for_timeout(2_000)

    async def _pick_composer(self, page: Page) -> Locator:
        loc = page.locator('[role="textbox"]')
        count = await loc.count()
        best: Locator | None = None
        best_y = -1.0
        for index in range(count):
            box = loc.nth(index)
            if not await box.is_visible():
                continue
            rect = await box.bounding_box()
            if not rect or rect["width"] <= 100 or rect["height"] <= 20:
                continue
            aria = (await box.get_attribute("aria-label") or "").lower()
            if "write to" in aria:
                return box
            if rect["y"] > best_y:
                best_y = rect["y"]
                best = box
        if best is None:
            raise RuntimeError("Could not find the message composer in the current chat view.")
        return best

    async def _submit_composer_message(self, page: Page, composer: Locator) -> bool:
        await composer.press("Enter")
        await page.wait_for_timeout(1_500)
        if not _clean_text(await composer.inner_text()):
            return True

        for selector in ('[aria-label="Send"]', '[aria-label*="Send"][role="button"]'):
            button = page.locator(selector).last
            if await button.count() > 0 and await button.is_visible():
                await button.click()
                await page.wait_for_timeout(1_500)
                if not _clean_text(await composer.inner_text()):
                    return True

        await composer.press("Control+Enter")
        await page.wait_for_timeout(1_500)
        return not _clean_text(await composer.inner_text())

    async def _message_visible_from_you(self, page: Page, text: str) -> bool:
        await page.wait_for_timeout(2_000)
        return bool(
            await page.evaluate(
                r"""
                (text) => {
                  const needle = (text || '').trim().toLowerCase();
                  const nodes = Array.from(
                    document.querySelectorAll('div[data-message-id][data-scope="messages_table"][aria-roledescription="message"]')
                  );
                  for (const node of nodes) {
                    const label = (node.getAttribute('aria-label') || '').toLowerCase();
                    const body = (node.innerText || '').toLowerCase();
                    if (label.includes('by you') && (label.includes(needle) || body.includes(needle))) {
                      return true;
                    }
                  }
                  return false;
                }
                """,
                text,
            )
        )

    async def _summary_for_chat(self, chat_id: str) -> ChatSummary:
        try:
            for summary in await self.list_chats():
                if summary.chat_id == chat_id:
                    return summary
        except RuntimeError:
            pass
        return ChatSummary(
            chat_id=chat_id,
            chat_url=build_chat_url(chat_id),
            unread=False,
            latest_message_sender=MessageSender.UNKNOWN,
        )

    async def _summary_for_marketplace_row_chat(self, chat_id: str) -> ChatSummary:
        for summary in await self.list_chats():
            if summary.chat_id == chat_id:
                return summary
        return ChatSummary(
            chat_id=chat_id,
            chat_url=self._config.marketplace_inbox_url,
            unread=False,
            latest_message_sender=MessageSender.UNKNOWN,
        )

    async def _click_marketplace_row_chat(self, page: Page, chat_id: str) -> None:
        await self._goto_inbox()
        row_index = _marketplace_row_index(chat_id)
        if row_index is None:
            raise RuntimeError(f"Invalid Marketplace row chat id: {chat_id}")

        clicked = await page.evaluate(
            r"""
            (rowIndex) => {
              const rows = Array.from(document.querySelectorAll('div[role="button"][tabindex="0"]'))
                .map((row, index) => {
                  const rect = row.getBoundingClientRect();
                  const rowText = (row.textContent || '').trim();
                  return { row, index, rect, rowText };
                })
                .filter(({ rect, rowText }) => rect.x > 200 && rect.width > 200 && rect.height >= 40 && rowText.length > 10);
              const match = rows.find((item) => item.index === rowIndex);
              if (!match) {
                return false;
              }
              match.row.click();
              return true;
            }
            """,
            row_index,
        )
        if not clicked:
            raise RuntimeError(f"Could not find Marketplace row for chat id: {chat_id}")
        await page.wait_for_timeout(2_000)

    async def _goto_inbox(self) -> Page:
        page = self._require_page()
        if not _is_marketplace_inbox_url(page.url):
            await self._open_marketplace_inbox(page)
        return page

    async def _open_marketplace_inbox(self, page: Page) -> None:
        await self._open_url_with_auth(page, self._config.marketplace_inbox_url)

    async def _open_url_with_auth(
        self,
        page: Page,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
    ) -> None:
        logger.debug("_open_url_with_auth: goto %s", url)
        await self._safe_goto(page, url, wait_until=wait_until)
        await page.wait_for_timeout(1_000)

        if await self._is_login_page(page):
            logger.debug("_open_url_with_auth: login page detected; authenticating")
            if self._config.manual_login:
                await self._wait_for_manual_login(page)
            else:
                await self._authenticate(page)
            await self._safe_goto(page, url, wait_until=wait_until)
            await page.wait_for_timeout(1_000)

        if await self._is_login_page(page):
            logger.debug("_open_url_with_auth: still on login page; retrying auth")
            if self._config.manual_login:
                await self._wait_for_manual_login(page)
            else:
                await self._authenticate(page)
            await self._safe_goto(page, url, wait_until=wait_until)
            await page.wait_for_timeout(1_000)

        if await self._is_login_page(page):
            raise RuntimeError(
                "Facebook is still showing the login page after authentication. Check the credentials in .env or any challenge Facebook is requiring."
            )

        if await self._is_checkpoint_page(page):
            logger.debug("_open_url_with_auth: checkpoint page detected")
            await self._fail_or_pause_for_auth_failure(
                page,
                "Facebook requested extra verification after login. This scaffold does not handle checkpoint or two-factor flows yet.",
            )
        logger.debug("_open_url_with_auth: ready at %s", page.url)

    async def _wait_for_manual_login(self, page: Page) -> None:
        if self._config.headless:
            raise RuntimeError("Manual login requires a visible browser. Rerun with --headful.")

        print("Manual login required.")
        print("Complete Facebook login/CAPTCHA in the browser window. The script will continue once login is detected.")

        while True:
            if await self._has_facebook_session_cookie(page):
                return
            if await self._is_checkpoint_page(page) or await self._is_login_page(page):
                await page.wait_for_timeout(self._config.manual_login_check_interval_ms)
                continue
            return

    async def _has_facebook_session_cookie(self, page: Page) -> bool:
        cookies = await page.context.cookies("https://www.facebook.com")
        cookie_names = {cookie.get("name") for cookie in cookies}
        return "c_user" in cookie_names and "xs" in cookie_names

    async def _authenticate(self, page: Page) -> None:
        if not self._config.facebook_email or not self._config.facebook_password:
            raise RuntimeError(
                "Facebook login is required, but no credentials were configured. Add FACEBOOK_EMAIL and FACEBOOK_PASSWORD to .env or SessionConfig."
            )

        if not await self._is_login_page(page):
            await self._safe_goto(page, self._config.facebook_login_url)

        email_input = page.locator('input[name="email"]')
        password_input = page.locator('input[name="pass"]')
        login_button = page.locator(
            'button[name="login"], input[name="login"], [type="submit"], '
            'div[aria-label="Log In"][role="button"], div[aria-label="Log in"][role="button"], '
            '[role="button"]:has-text("Log in"), [role="button"]:has-text("Log In")'
        )

        try:
            await email_input.first.wait_for(state="visible")
            await password_input.first.wait_for(state="visible")
        except PlaywrightTimeoutError as exc:
            raise RuntimeError("Facebook login form did not appear when authentication was needed.") from exc

        await self._dismiss_cookie_banner(page)
        await email_input.first.fill(self._config.facebook_email)
        await password_input.first.fill(self._config.facebook_password)

        if not await self._submit_login_form(page, password_input, login_button):
            raise RuntimeError(
                "Could not submit the Facebook login form. The login button may be blocked, hidden, or Facebook changed the page structure."
            )

        await self._wait_for_post_login_transition(page)

        if await self._is_checkpoint_page(page):
            await self._fail_or_pause_for_auth_failure(
                page,
                "Facebook requested extra verification after submitting credentials. Two-factor and checkpoint flows are not implemented yet.",
            )

    async def _fail_or_pause_for_auth_failure(self, page: Page, message: str) -> None:
        if self._config.pause_on_auth_failure and not self._config.headless:
            print(message)
            print("Leaving browser open for inspection. Press Ctrl+C in this terminal when done.")
            while True:
                await page.wait_for_timeout(60_000)
        raise RuntimeError(message)

    async def _submit_login_form(
        self,
        page: Page,
        password_input: Locator,
        login_button: Locator,
    ) -> bool:
        button_count = await login_button.count()
        if button_count > 0:
            button = login_button.first
            for force in (False, True):
                try:
                    await button.scroll_into_view_if_needed()
                    await button.click(force=force, timeout=3_000)
                    return True
                except PlaywrightError:
                    continue

        try:
            await password_input.first.press("Enter", timeout=3_000)
            return True
        except PlaywrightError:
            pass

        submitted = await page.evaluate(
            """
            () => {
              const email = document.querySelector('input[name="email"]');
              const form = email?.closest('form') || document.querySelector('form');
              if (!form) {
                return false;
              }
              if (typeof form.requestSubmit === 'function') {
                form.requestSubmit();
                return true;
              }
              form.submit();
              return true;
            }
            """
        )
        return bool(submitted)

    async def _wait_for_post_login_transition(self, page: Page) -> None:
        for _ in range(20):
            await page.wait_for_timeout(500)
            if await self._is_checkpoint_page(page):
                return
            if not await self._is_login_page(page):
                return

    async def _dismiss_cookie_banner(self, page: Page) -> None:
        selectors = [
            'button:has-text("Allow all cookies")',
            'button:has-text("Accept all")',
            'button:has-text("Accept All")',
            'button:has-text("Allow essential and optional cookies")',
            '[aria-label="Allow all cookies"]',
            '[aria-label="Accept all"]',
        ]
        for selector in selectors:
            locator = page.locator(selector)
            if await locator.count() == 0:
                continue
            try:
                await locator.first.click(timeout=2_000)
                await page.wait_for_timeout(500)
                return
            except PlaywrightError:
                continue

    async def _is_login_page(self, page: Page) -> bool:
        if "login" in page.url or "recover" in page.url:
            return True
        return await self._has_any_selector(
            page,
            [
                'input[name="email"]',
                'input[name="pass"]',
                'button[name="login"]',
            ],
        )

    async def _is_checkpoint_page(self, page: Page) -> bool:
        lower_url = page.url.lower()
        if "checkpoint" in lower_url or "two_step" in lower_url or "approvals" in lower_url:
            return True
        body_text = _clean_text(await page.locator("body").inner_text())
        lowered = body_text.lower()
        return any(
            marker in lowered
            for marker in (
                "enter the code",
                "i'm not a robot",
                "not a robot",
                "two-factor authentication",
                "check your notifications",
                "approve this login",
            )
        )

    async def _has_any_selector(self, page: Page, selectors: list[str]) -> bool:
        for selector in selectors:
            locator = page.locator(selector)
            if await locator.count() > 0:
                return True
        return False

    async def _safe_goto(
        self,
        page: Page,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
    ) -> None:
        timeout = self._config.timeout_ms
        try:
            await page.goto(url, wait_until=wait_until, timeout=timeout)
        except PlaywrightTimeoutError:
            if wait_until != "domcontentloaded":
                raise
            logger.info(
                "_safe_goto: timeout waiting for domcontentloaded on %s; retrying with commit",
                url,
            )
            try:
                await page.goto(url, wait_until="commit", timeout=timeout)
            except PlaywrightError as exc:
                if "ERR_ABORTED" not in str(exc):
                    raise
                await page.wait_for_timeout(1_000)
        except PlaywrightError as exc:
            if "ERR_ABORTED" not in str(exc):
                raise
            await page.wait_for_timeout(1_000)

    async def _wait_for_inbox(self, page: Page) -> None:
        logger.debug("_wait_for_inbox: waiting for inbox thread rows")
        for attempt in range(2):
            try:
                await page.wait_for_function(
                    r"""
                    () => {
                      const hasThreadAnchor = Array.from(document.querySelectorAll('a[href*="/messages/t/"]'))
                        .some((anchor) => /\/messages\/t\/[^/?#]+/.test(anchor.getAttribute('href') || ''));
                      const hasMarketplaceButtonRow = Array.from(document.querySelectorAll('div[role="button"][tabindex="0"]'))
                        .some((row) => {
                          const rect = row.getBoundingClientRect();
                          const rowText = (row.textContent || '').trim();
                          return rect.x > 200 && rect.width > 200 && rect.height >= 40 && rowText.length > 10;
                        });
                      return hasThreadAnchor || hasMarketplaceButtonRow;
                    }
                    """,
                    timeout=5_000,
                )
                logger.debug("_wait_for_inbox: inbox ready (attempt %d)", attempt + 1)
                return
            except PlaywrightTimeoutError:
                logger.debug("_wait_for_inbox: timeout on attempt %d", attempt + 1)
                if await self._is_login_page(page) or await self._is_checkpoint_page(page):
                    raise RuntimeError(
                        "Could not find chat links because Facebook is showing login or verification."
                    )
                if attempt == 0:
                    await page.reload(wait_until="domcontentloaded")
                    await page.wait_for_timeout(2_000)

    async def _scroll_inbox_to_load_chats(self, page: Page, target_count: int, max_passes: int = 20) -> None:
        await page.evaluate(
            r"""
            () => {
              document.querySelectorAll('[data-fb-bot-inbox-scroll="true"]').forEach((node) => {
                node.removeAttribute('data-fb-bot-inbox-scroll');
              });
              const isChatButton = (row) => {
                const rect = row.getBoundingClientRect();
                const rowText = (row.textContent || '').trim();
                return rect.x > 200 && rect.width > 200 && rect.height >= 40 && rowText.length > 10;
              };
              const candidates = Array.from(document.querySelectorAll('div, section, main')).filter((node) => {
                const style = window.getComputedStyle(node);
                const hasThreads = node.querySelector('a[href*="/messages/t/"]') || Array.from(node.querySelectorAll('div[role="button"][tabindex="0"]')).some(isChatButton);
                return hasThreads && ['auto', 'scroll'].includes(style.overflowY) && node.scrollHeight > node.clientHeight + 50;
              });
              candidates.sort((a, b) => b.scrollHeight - a.scrollHeight);
              if (candidates[0]) {
                candidates[0].setAttribute('data-fb-bot-inbox-scroll', 'true');
              }
            }
            """
        )
        scroller = page.locator('[data-fb-bot-inbox-scroll="true"]').first
        if await scroller.count() == 0:
            return

        previous_count = -1
        stable_passes = 0
        for _ in range(max_passes):
            current_count = await page.evaluate(
                r"""
                () => {
                  const anchorCount = Array.from(document.querySelectorAll('a[href*="/messages/t/"]'))
                    .filter((anchor) => /\/messages\/t\/[^/?#]+/.test(anchor.getAttribute('href') || ''))
                    .length;
                  const buttonCount = Array.from(document.querySelectorAll('div[role="button"][tabindex="0"]'))
                    .filter((row) => {
                      const rect = row.getBoundingClientRect();
                      const rowText = (row.textContent || '').trim();
                      return rect.x > 200 && rect.width > 200 && rect.height >= 40 && rowText.length > 10;
                    })
                    .length;
                  return Math.max(anchorCount, buttonCount);
                }
                """
            )
            if current_count >= target_count:
                return
            if current_count == previous_count:
                stable_passes += 1
                if stable_passes >= 3:
                    return
            else:
                stable_passes = 0
            previous_count = current_count
            await scroller.evaluate("(el) => { el.scrollTop = el.scrollHeight; }")
            await page.wait_for_timeout(self._config.scroll_pause_ms)

    async def _wait_for_listing(self, page: Page) -> None:
        logger.debug("_wait_for_listing: waiting for listing page signals")
        try:
            await page.wait_for_function(
                _LISTING_PAGE_READY_JS,
                timeout=self._config.timeout_ms,
            )
            logger.debug("_wait_for_listing: listing page ready")
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                "Could not load the listing page. Confirm the listing URL is valid and the profile has access to it."
            ) from exc

    async def _wait_for_chat(self, page: Page) -> None:
        logger.debug("_wait_for_chat: waiting for chat UI signals")
        try:
            await page.wait_for_function(
                r"""
                () => {
                  if (document.querySelector('div[data-message-id][data-scope="messages_table"][aria-roledescription="message"]')) {
                    return true;
                  }
                  const textbox = document.querySelector('[role="textbox"]');
                  if (textbox) {
                    const rect = textbox.getBoundingClientRect();
                    if (rect.width > 100 && rect.height > 20) {
                      return true;
                    }
                  }
                  const listing = document.querySelector('a[href*="/marketplace/item/"]');
                  if (listing) {
                    const rect = listing.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                      return true;
                    }
                  }
                  return false;
                }
                """,
                timeout=self._config.timeout_ms,
            )
            logger.debug("_wait_for_chat: chat UI ready")
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                "Could not load the chat thread. Confirm the chat ID is valid and the profile has access to it."
            ) from exc

    async def _extract_listing_link(self, page: Page) -> tuple[str | None, str | None]:
        raw = await page.evaluate(
            r"""
            () => {
              const links = Array.from(document.querySelectorAll('a[href*="/marketplace/item/"]'))
                .map((anchor) => {
                  const rect = anchor.getBoundingClientRect();
                  return {
                    href: anchor.href,
                    text: (anchor.textContent || '').trim(),
                    width: rect.width,
                    height: rect.height,
                    x: rect.x,
                  };
                })
                .filter((link) => link.width > 0 && link.height > 0 && link.x > 200);
              links.sort((a, b) => a.x - b.x);
              return links[0] || null;
            }
            """
        )
        if not raw:
            return None, None
        href = normalize_listing_url(raw.get("href"))
        title = _clean_text(raw.get("text"))
        if title:
            title = re.sub(r"^Marketplace", "", title).strip()
            title = re.sub(r"\$[\d,]+(?:\.\d{2})?\s*-\s*", "", title).strip()
            title = re.sub(r"View buyer.*$", "", title, flags=re.IGNORECASE).strip()
        return href, title or None

    async def _extract_thread_metadata(self, page: Page) -> tuple[str | None, str | None, str | None]:
        raw = await page.evaluate(
            r"""
            () => {
              const convo = Array.from(document.querySelectorAll('[aria-label^="Conversation titled"]'))
                .map((node) => ({
                  label: node.getAttribute('aria-label') || '',
                  rect: node.getBoundingClientRect(),
                }))
                .filter((item) => item.rect.width > 0 && item.rect.height > 0)
                .sort((a, b) => a.rect.x - b.rect.x)[0];
              return { conversationLabel: convo?.label || null };
            }
            """
        )
        buyer_name: str | None = None
        listing_name: str | None = None
        label = _clean_text(raw.get("conversationLabel"))
        if label.lower().startswith("conversation titled "):
            title = label[len("Conversation titled ") :].strip()
            if " · " in title:
                buyer_name, listing_name = [part.strip() for part in title.split(" · ", 1)]
            else:
                buyer_name = title or None

        listing_url, listing_from_link = await self._extract_listing_link(page)
        listing_name = listing_name or listing_from_link
        return buyer_name, listing_name, listing_url

    async def _scroll_thread_to_start(self, page: Page, max_passes: int = 30) -> None:
        try:
            scroller = await self._ensure_thread_scroller(page)
        except (PlaywrightError, RuntimeError):
            return
        last_height = -1
        stable_passes = 0
        for _ in range(max_passes):
            try:
                await scroller.evaluate("(el) => { el.scrollTop = 0; }")
                await page.wait_for_timeout(self._config.scroll_pause_ms)
                next_metrics = await scroller.evaluate(
                    "(el) => ({ top: el.scrollTop, height: el.scrollHeight })"
                )
            except PlaywrightError:
                return
            if next_metrics["top"] == 0 and next_metrics["height"] == last_height:
                stable_passes += 1
                if stable_passes >= 2:
                    break
            else:
                stable_passes = 0
            last_height = next_metrics["height"]

    async def _ensure_thread_scroller(self, page: Page) -> Locator:
        await page.evaluate(
            """
            () => {
              document.querySelectorAll('[data-fb-bot-thread-scroll="true"]').forEach((node) => {
                node.removeAttribute('data-fb-bot-thread-scroll');
              });
              let candidates = Array.from(document.querySelectorAll('div, section, main')).filter((node) => {
                const style = window.getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return ['auto', 'scroll'].includes(style.overflowY)
                  && node.scrollHeight > node.clientHeight + 100
                  && rect.height > 250
                  && rect.width > 250;
              });
              candidates.sort((a, b) => b.clientHeight - a.clientHeight);

              if (!candidates[0]) {
                candidates = Array.from(document.querySelectorAll('div, section, main')).filter((node) => {
                  const rect = node.getBoundingClientRect();
                  const textLength = (node.innerText || '').trim().length;
                  const hasMessageLikeNode = node.querySelector('[aria-label*="Message sent"], [aria-label*="message sent"], [aria-label*="sent"], [aria-label*="Sent"]');
                  return rect.height > 200
                    && rect.width > 300
                    && rect.width < window.innerWidth * 0.85
                    && textLength > 20
                    && hasMessageLikeNode;
                });
                candidates.sort((a, b) => {
                  const aRect = a.getBoundingClientRect();
                  const bRect = b.getBoundingClientRect();
                  return (bRect.height * bRect.width) - (aRect.height * aRect.width);
                });
              }

              if (candidates[0]) {
                candidates[0].setAttribute('data-fb-bot-thread-scroll', 'true');
              }
            }
            """
        )
        locator = page.locator('[data-fb-bot-thread-scroll="true"]').first
        count = await locator.count()
        if count == 0:
            raise RuntimeError("Could not identify the thread scroller in the current chat view.")
        return locator

    async def _extract_messages(self, page: Page) -> list[ChatMessage]:
        raw_messages = await page.evaluate(
            r"""
            () => {
              const root = document.querySelector('[data-fb-bot-thread-scroll="true"]') || document;
              const selector = 'div[data-message-id][data-scope="messages_table"][aria-roledescription="message"]';
              let all = Array.from(root.querySelectorAll(selector));
              if (!all.length && root !== document) {
                all = Array.from(document.querySelectorAll(selector));
              }

              const seenIds = new Set();
              const entries = [];
              for (const node of all) {
                const messageId = node.getAttribute('data-message-id');
                if (!messageId || seenIds.has(messageId)) {
                  continue;
                }
                seenIds.add(messageId);
                const text = (node.innerText || '').trim();
                const ariaLabel = node.getAttribute('aria-label') || '';
                if ((!text && !ariaLabel) || text.length > 4000) {
                  continue;
                }
                const rect = node.getBoundingClientRect();
                const timeNode = node.querySelector('time');
                entries.push({
                  text,
                  ariaLabel,
                  messageId,
                  timestampLabel: timeNode?.getAttribute('datetime') || timeNode?.textContent?.trim() || null,
                  y: rect.y,
                });
              }
              entries.sort((a, b) => a.y - b.y);
              return entries;
            }
            """
        )

        messages: list[ChatMessage] = []
        seen_message_ids: set[str] = set()
        for item in raw_messages:
            message_id = item.get("messageId")
            if message_id and message_id in seen_message_ids:
                continue

            aria_label = item.get("ariaLabel")
            inner_text = _clean_text(item.get("text"))
            parsed_aria = _parse_message_aria_label(aria_label)
            if parsed_aria and parsed_aria["skip"]:
                continue
            if _is_system_message(inner_text, aria_label):
                continue

            text = parsed_aria["text"] if parsed_aria else inner_text
            if not text:
                continue

            timestamp_label = parsed_aria["timestamp_label"] if parsed_aria else item.get("timestampLabel")
            if not timestamp_label:
                timestamp_label, parsed_time = _parse_message_timestamp(aria_label)
            else:
                timestamp_label, parsed_time = _parse_message_timestamp(timestamp_label)

            sender = parsed_aria["sender"] if parsed_aria else MessageSender.BUYER
            if message_id:
                seen_message_ids.add(message_id)

            messages.append(
                ChatMessage(
                    sender=sender,
                    text=text,
                    message_id=message_id,
                    timestamp_label=timestamp_label,
                    sent_at=parsed_time,
                    age_seconds=age_seconds(parsed_time),
                )
            )

        return messages

    def _require_page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Client has not been started")
        return self._page


async def _text_from_first(page: Page, selectors: list[str]) -> str | None:
    for selector in selectors:
        locator = page.locator(selector)
        count = await locator.count()
        if count == 0:
            continue
        try:
            text = _clean_text(await locator.first.inner_text())
        except PlaywrightError:
            continue
        if text:
            return text
    return None


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split())


def _message_text_from_aria_label(value: str | None) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    if ":" not in cleaned:
        return cleaned
    return _clean_text(cleaned.rsplit(":", 1)[-1])


_METADATA_ONLY_AT_LABEL = re.compile(r"^At [^,]+, [^:]+$")


def _normalize_message_aria_label(value: str | None) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    return re.sub(r"^Enter,\s*", "", cleaned, flags=re.IGNORECASE).strip()


def _is_metadata_only_aria_label(normalized: str) -> bool:
    return bool(_METADATA_ONLY_AT_LABEL.match(normalized))


def _sender_from_aria_name(sender_label: str) -> MessageSender:
    label = _clean_text(sender_label)
    if label.lower() == "you":
        return MessageSender.SELLER
    return MessageSender.BUYER


def _skip_aria_parse(timestamp_label: str | None = None) -> dict[str, Any]:
    return {
        "skip": True,
        "text": "",
        "sender": MessageSender.UNKNOWN,
        "timestamp_label": timestamp_label,
    }


def _finish_aria_parse(timestamp: str, sender_label: str, text: str | None, *, force_buyer: bool = False) -> dict[str, Any]:
    timestamp_label = _clean_text(timestamp)
    parsed_text = _clean_text(text)
    if not parsed_text or _is_system_message(parsed_text):
        return _skip_aria_parse(timestamp_label)

    sender = MessageSender.BUYER if force_buyer else _sender_from_aria_name(sender_label)
    return {
        "skip": False,
        "text": parsed_text,
        "sender": sender,
        "timestamp_label": timestamp_label,
    }


def _is_system_message(text: str, aria_label: str | None = None) -> bool:
    normalized = _normalize_message_aria_label(aria_label)
    if normalized:
        if _is_metadata_only_aria_label(normalized):
            return True
        if re.search(r"^Message sent .+ by\s*$", normalized, flags=re.IGNORECASE):
            return True

    cleaned = _clean_text(text)
    if not cleaned:
        return False

    lowered = cleaned.lower()
    if cleaned.endswith("started this chat."):
        return True
    if cleaned.endswith("is waiting for your response."):
        return True
    if "send a quick response" in lowered:
        return True
    if "view buyer profile" in lowered:
        return True
    if "view seller profile" in lowered:
        return True
    if "to help identify and reduce scams" in lowered:
        return True
    if "rate this person" in lowered:
        return True
    if "rate seller" in lowered:
        return True
    if "rate buyer" in lowered:
        return True
    if "you can now message and call each other" in lowered:
        return True
    if lowered == "facebook marketplace assistant":
        return True
    if re.search(r"joined facebook in \d{4}", lowered):
        return True
    return False


def _normalize_messenger_timestamp_label(label: str | None) -> str | None:
    if not label:
        return label
    cleaned = _clean_text(label)
    cleaned = re.sub(
        r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\d)",
        r"\1 at \2",
        cleaned,
        flags=re.IGNORECASE,
    )
    return re.sub(r"([0-9])([ap]m)\b", r"\1 \2", cleaned, flags=re.IGNORECASE)


def _parse_message_timestamp(label: str | None) -> tuple[str | None, datetime | None]:
    normalized = _normalize_messenger_timestamp_label(label)
    return first_timestamp_in_text(normalized)


def _parse_message_aria_label(value: str | None) -> dict[str, Any] | None:
    cleaned = _normalize_message_aria_label(value)
    if not cleaned:
        return None

    if re.search(r"^Message sent .+ by\s*$", cleaned, flags=re.IGNORECASE):
        return _skip_aria_parse()
    if _is_metadata_only_aria_label(cleaned):
        return _skip_aria_parse()

    at_match = re.match(
        r"^At (?P<timestamp>.+?), (?P<sender>.*?): (?P<text>.*)$",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if at_match:
        return _finish_aria_parse(
            at_match.group("timestamp"),
            at_match.group("sender"),
            at_match.group("text"),
        )

    sent_match = re.match(
        r"^Message sent (?P<timestamp>.+?) by (?P<sender>[^:]*)(?:: (?P<text>.*))?$",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if sent_match:
        return _finish_aria_parse(
            sent_match.group("timestamp"),
            sent_match.group("sender"),
            sent_match.group("text"),
        )

    received_match = re.match(
        r"^Message received (?P<timestamp>.+?) from (?P<sender>[^:]*)(?:: (?P<text>.*))?$",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if received_match:
        return _finish_aria_parse(
            received_match.group("timestamp"),
            received_match.group("sender"),
            received_match.group("text"),
            force_buyer=True,
        )

    return None


def _is_system_chat(buyer_name: str | None, preview: str | None) -> bool:
    if not buyer_name:
        return False
    lowered = buyer_name.lower()
    if lowered == "facebook marketplace assistant":
        return True
    if lowered.startswith("you can now message and call each other"):
        return True
    return False


def _is_marketplace_inbox_url(url: str) -> bool:
    return "/marketplace/inbox" in url


def _is_marketplace_listing_url(current_url: str, listing_url: str) -> bool:
    item_id = extract_listing_id(listing_url)
    if item_id is None:
        return "/marketplace/item/" in current_url
    return f"/marketplace/item/{item_id}" in current_url


def _marketplace_row_chat_id(row_index: int, row_text: str) -> str:
    digest = hashlib.sha1(row_text.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"mp_row_{row_index}_{digest}"


def _marketplace_row_index(chat_id: str) -> int | None:
    parts = chat_id.split("_")
    if len(parts) < 4 or parts[0] != "mp" or parts[1] != "row":
        return None
    try:
        return int(parts[2])
    except ValueError:
        return None


_DAY_ABBREV = re.compile(r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)$", re.IGNORECASE)
_COMPACT_RELATIVE = re.compile(r"^\d+[a-z]+$", re.IGNORECASE)


def _is_inbox_timestamp_label(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return True
    if _DAY_ABBREV.match(cleaned):
        return True
    if _COMPACT_RELATIVE.match(cleaned):
        return True
    if parse_relative_timestamp(cleaned) is not None:
        return True
    return False


def _guess_summary_text_fields(text_parts: list[str], row_text: str) -> tuple[str | None, str | None, str | None]:
    lines = [line.strip() for line in text_parts if line.strip()]
    if not lines:
        lines = [line.strip() for line in row_text.splitlines() if line.strip()]
    normalized: list[str] = []
    for line in lines:
        if not normalized or normalized[-1] != line:
            normalized.append(line)

    if not normalized:
        return None, None, None

    meaningful = [line for line in normalized if len(line) > 1 or line == "?"]
    if not meaningful:
        return None, None, None

    buyer_name = meaningful[0].split(" · ", 1)[0].strip()
    listing_name = None
    preview = next(
        (
            line
            for line in meaningful
            if (line.lower().startswith("you:") or ":" in line) and not _is_inbox_timestamp_label(line)
        ),
        None,
    )
    if preview is None:
        candidates = [line for line in meaningful[1:] if not _is_inbox_timestamp_label(line)]
        preview = candidates[-1] if candidates else None
    return buyer_name or None, listing_name or None, preview or None
