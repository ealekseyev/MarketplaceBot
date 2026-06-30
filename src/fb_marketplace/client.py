from __future__ import annotations
from dataclasses import replace
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

from .helpers import build_chat_url, extract_chat_id, guess_sender_from_preview, normalize_facebook_url
from .models import ChatDetail, ChatMessage, ChatSummary, ListingDetail, MessageSender, SessionConfig
from .timeparse import age_seconds, first_timestamp_in_text


_CONVERSATION_LINK_SELECTOR = 'a[href*="/messages/t/"], a[href*="thread_id="]'
_LISTING_LINK_SELECTOR = 'a[href*="/marketplace/item/"]'
_HEADING_SELECTOR = 'h1, h2, h3, [role="heading"]'


class FacebookMarketplaceClient:
    def __init__(self, config: SessionConfig) -> None:
        self._config = config
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

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
            await self._open_marketplace_inbox(page)
        except PlaywrightError as exc:
            if context is not None:
                await context.close()
            if playwright is not None:
                await playwright.stop()
            message = str(exc)
            if "ERR_TOO_MANY_REDIRECTS" in message:
                raise RuntimeError(
                    "Facebook redirected the session before inbox load. Use valid Facebook credentials in .env or rerun with --headful and complete the login flow."
                ) from exc
            raise

        self._playwright = playwright
        self._context = context
        self._page = page

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None
            self._page = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def list_chats(self) -> list[ChatSummary]:
        page = await self._goto_inbox()
        await self._wait_for_inbox(page)
        raw_rows = await page.evaluate(
            """
            () => {
              const anchors = Array.from(document.querySelectorAll('a[href*="/messages/t/"], a[href*="thread_id="]'));
              const isVisible = (el) => {
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
              };
              return anchors
                .filter(isVisible)
                .map((anchor) => {
                  const row = anchor.closest('[role="row"], [role="listitem"], li, section, article, div') || anchor;
                  const rect = row.getBoundingClientRect();
                  return {
                    href: anchor.href,
                    anchorText: (anchor.textContent || '').trim(),
                    rowText: (row.textContent || '').trim(),
                    rowHtml: row.innerHTML || '',
                    ariaLabel: row.getAttribute('aria-label') || anchor.getAttribute('aria-label') || '',
                    x: rect.x,
                    y: rect.y,
                    width: rect.width,
                    height: rect.height,
                  };
                })
                .filter((item) => item.width > 120 && item.height > 24)
                .sort((a, b) => a.y - b.y);
            }
            """
        )

        now = None
        summaries: list[ChatSummary] = []
        seen_chat_ids: set[str] = set()
        for row in raw_rows:
            chat_id = extract_chat_id(row.get("href"))
            if not chat_id or chat_id in seen_chat_ids:
                continue

            seen_chat_ids.add(chat_id)
            row_text = _clean_text(row.get("rowText"))
            buyer_name, listing_name, preview = _guess_summary_text_fields(row_text)
            latest_label, latest_at = first_timestamp_in_text(
                "\n".join(filter(None, [row.get("ariaLabel"), row_text])),
                now=now,
            )
            unread = _looks_unread(row.get("ariaLabel"), row_text, row.get("rowHtml"))
            sender = guess_sender_from_preview(preview, buyer_name)

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
                )
            )

        return summaries

    async def get_chat(self, chat_id: str) -> ChatDetail:
        page = self._require_page()
        summary = await self._summary_for_chat(chat_id)
        await page.goto(build_chat_url(chat_id), wait_until="domcontentloaded")
        await self._wait_for_chat(page)

        await self._scroll_thread_to_start(page)

        buyer_name = await _text_from_first(page, [_HEADING_SELECTOR])
        listing_url, listing_name = await self._extract_listing_link(page)
        messages = await self._extract_messages(page)

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
        page = self._require_page()
        normalized_url = normalize_facebook_url(listing_url)
        if normalized_url is None:
            raise ValueError("listing_url must be non-empty")

        await page.goto(normalized_url, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle")

        raw = await page.evaluate(
            r"""
            () => {
              const meta = (selector) => document.querySelector(selector)?.getAttribute('content') || null;
              const text = (selector) => document.querySelector(selector)?.textContent?.trim() || null;
              const canonical = document.querySelector('link[rel="canonical"]')?.getAttribute('href') || null;
              const bodyText = document.body?.innerText || '';
              const priceMatch = bodyText.match(/\$\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?/);
              return {
                title: meta('meta[property="og:title"]') || text('h1'),
                description: meta('meta[property="og:description"]'),
                canonicalUrl: canonical,
                priceText: priceMatch ? priceMatch[0] : null,
                locationText: text('[data-testid="marketplace_pdp_location"]') || null,
              };
            }
            """
        )

        return ListingDetail(
            url=normalized_url,
            canonical_url=raw.get("canonicalUrl"),
            title=raw.get("title"),
            description=raw.get("description"),
            price_text=raw.get("priceText"),
            location_text=raw.get("locationText"),
            raw_metadata={
                key: value
                for key, value in raw.items()
                if isinstance(value, str) and value
            },
        )

    async def get_chat_listing(self, chat_id: str) -> ListingDetail | None:
        detail = await self.get_chat(chat_id)
        if not detail.listing_url:
            return None
        return await self.get_listing(detail.listing_url)

    async def _summary_for_chat(self, chat_id: str) -> ChatSummary:
        for summary in await self.list_chats():
            if summary.chat_id == chat_id:
                return summary
        return ChatSummary(
            chat_id=chat_id,
            chat_url=build_chat_url(chat_id),
            unread=False,
            latest_message_sender=MessageSender.UNKNOWN,
        )

    async def _goto_inbox(self) -> Page:
        page = self._require_page()
        if not page.url.startswith(self._config.marketplace_inbox_url):
            await self._open_marketplace_inbox(page)
        return page

    async def _open_marketplace_inbox(self, page: Page) -> None:
        await page.goto(self._config.facebook_home_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(1_000)

        if await self._is_login_page(page):
            await self._authenticate(page)

        await page.goto(self._config.marketplace_inbox_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(1_000)

        if await self._is_login_page(page):
            await self._authenticate(page)
            await page.goto(self._config.marketplace_inbox_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(1_000)

        if await self._is_login_page(page):
            raise RuntimeError(
                "Facebook is still showing the login page after authentication. Check the credentials in .env or any challenge Facebook is requiring."
            )

        if await self._is_checkpoint_page(page):
            raise RuntimeError(
                "Facebook requested extra verification after login. This scaffold does not handle checkpoint or two-factor flows yet."
            )

    async def _authenticate(self, page: Page) -> None:
        if not self._config.facebook_email or not self._config.facebook_password:
            raise RuntimeError(
                "Facebook login is required, but no credentials were configured. Add FACEBOOK_EMAIL and FACEBOOK_PASSWORD to .env or SessionConfig."
            )

        if not await self._is_login_page(page):
            await page.goto(self._config.facebook_login_url, wait_until="domcontentloaded")

        email_input = page.locator('input[name="email"]')
        password_input = page.locator('input[name="pass"]')
        login_button = page.locator('button[name="login"], input[name="login"], [type="submit"]')

        try:
            await email_input.first.wait_for(state="visible")
            await password_input.first.wait_for(state="visible")
        except PlaywrightTimeoutError as exc:
            raise RuntimeError("Facebook login form did not appear when authentication was needed.") from exc

        await email_input.first.fill(self._config.facebook_email)
        await password_input.first.fill(self._config.facebook_password)
        await login_button.first.click()
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2_000)

        if await self._is_checkpoint_page(page):
            raise RuntimeError(
                "Facebook requested extra verification after submitting credentials. Two-factor and checkpoint flows are not implemented yet."
            )

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

    async def _wait_for_inbox(self, page: Page) -> None:
        try:
            await page.wait_for_selector(_CONVERSATION_LINK_SELECTOR)
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                "Could not find chat links in Marketplace inbox. Confirm Facebook is logged in and the inbox page loaded."
            ) from exc

    async def _wait_for_chat(self, page: Page) -> None:
        try:
            await page.wait_for_selector(f"{_HEADING_SELECTOR}, {_LISTING_LINK_SELECTOR}")
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                "Could not load the chat thread. Confirm the chat ID is valid and the profile has access to it."
            ) from exc

    async def _extract_listing_link(self, page: Page) -> tuple[str | None, str | None]:
        locator = page.locator(_LISTING_LINK_SELECTOR)
        count = await locator.count()
        if count == 0:
            return None, None

        link = locator.first
        href = normalize_facebook_url(await link.get_attribute("href"))
        title = _clean_text(await link.inner_text())
        return href, title or None

    async def _scroll_thread_to_start(self, page: Page, max_passes: int = 30) -> None:
        scroller = await self._ensure_thread_scroller(page)
        last_height = -1
        stable_passes = 0
        for _ in range(max_passes):
            metrics = await scroller.evaluate(
                "(el) => ({ top: el.scrollTop, height: el.scrollHeight })"
            )
            await scroller.evaluate("(el) => { el.scrollTop = 0; }")
            await page.wait_for_timeout(self._config.scroll_pause_ms)
            next_metrics = await scroller.evaluate(
                "(el) => ({ top: el.scrollTop, height: el.scrollHeight })"
            )
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
              const candidates = Array.from(document.querySelectorAll('div, section, main')).filter((node) => {
                const style = window.getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return ['auto', 'scroll'].includes(style.overflowY)
                  && node.scrollHeight > node.clientHeight + 100
                  && rect.height > 250
                  && rect.width > 250;
              });
              candidates.sort((a, b) => b.clientHeight - a.clientHeight);
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
        await self._ensure_thread_scroller(page)
        raw_messages = await page.evaluate(
            """
            () => {
              const scroller = document.querySelector('[data-fb-bot-thread-scroll="true"]');
              if (!scroller) {
                return [];
              }
              const viewportMidpoint = window.innerWidth / 2;
              const all = Array.from(scroller.querySelectorAll('div, li, article, section'));
              const entries = [];
              for (const node of all) {
                const text = (node.innerText || '').trim();
                if (!text || text.length > 4000) {
                  continue;
                }
                const rect = node.getBoundingClientRect();
                if (rect.width < 20 || rect.height < 12 || rect.width > window.innerWidth * 0.9) {
                  continue;
                }
                const childHasSameText = Array.from(node.children).some((child) => {
                  const childText = (child.innerText || '').trim();
                  const childRect = child.getBoundingClientRect();
                  return childText === text && childRect.width > 20 && childRect.height > 12;
                });
                if (childHasSameText) {
                  continue;
                }
                const timeNode = node.querySelector('time');
                entries.push({
                  text,
                  ariaLabel: node.getAttribute('aria-label') || '',
                  messageId: node.getAttribute('id') || node.getAttribute('data-message-id') || null,
                  timestampLabel: timeNode?.getAttribute('datetime') || timeNode?.textContent?.trim() || null,
                  x: rect.x,
                  y: rect.y,
                  width: rect.width,
                  height: rect.height,
                  side: rect.left + rect.width / 2 >= viewportMidpoint ? 'seller' : 'buyer',
                });
              }
              entries.sort((a, b) => a.y - b.y);
              return entries;
            }
            """
        )

        messages: list[ChatMessage] = []
        seen_keys: set[tuple[str, str | None, str]] = set()
        for item in raw_messages:
            text = _clean_text(item.get("text"))
            if not text:
                continue
            timestamp_label = item.get("timestampLabel")
            if not timestamp_label:
                timestamp_label, parsed_time = first_timestamp_in_text(item.get("ariaLabel"))
            else:
                _, parsed_time = first_timestamp_in_text(timestamp_label)

            sender = MessageSender.SELLER if item.get("side") == "seller" else MessageSender.BUYER
            key = (text, timestamp_label, sender.value)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            messages.append(
                ChatMessage(
                    sender=sender,
                    text=text,
                    message_id=item.get("messageId"),
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


def _guess_summary_text_fields(row_text: str) -> tuple[str | None, str | None, str | None]:
    lines = [line.strip() for line in row_text.splitlines() if line.strip()]
    normalized: list[str] = []
    for line in lines:
        if not normalized or normalized[-1] != line:
            normalized.append(line)

    if not normalized:
        return None, None, None

    buyer_name = normalized[0]
    listing_name = normalized[1] if len(normalized) >= 3 else None
    preview = normalized[-1] if len(normalized) >= 2 else normalized[0]
    return buyer_name or None, listing_name or None, preview or None


def _looks_unread(aria_label: str | None, row_text: str | None, row_html: str | None) -> bool:
    haystacks = [value.lower() for value in (aria_label, row_text, row_html) if value]
    return any(
        token in haystack
        for haystack in haystacks
        for token in ("unread", "new message", "new messages")
    )
