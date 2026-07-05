from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from .models import MessageSender


def normalize_facebook_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.scheme:
        return f"https://www.facebook.com{url}"
    return url


def normalize_listing_url(url: str | None) -> str | None:
    """Return a canonical marketplace item URL without tracking query params."""
    if not url:
        return None
    stripped = url.strip()
    if re.fullmatch(r"\d+", stripped):
        return f"https://www.facebook.com/marketplace/item/{stripped}"
    normalized = normalize_facebook_url(stripped)
    if not normalized:
        return None
    item_id = extract_listing_id(normalized)
    if item_id:
        return f"https://www.facebook.com/marketplace/item/{item_id}"
    return normalized


def extract_chat_id(url: str | None) -> str | None:
    normalized = normalize_facebook_url(url)
    if not normalized:
        return None

    parsed = urlparse(normalized)
    message_match = re.search(r"/messages/t/([^/?#]+)", parsed.path)
    if message_match:
        return message_match.group(1)

    thread_id = parse_qs(parsed.query).get("thread_id")
    if thread_id:
        return thread_id[0]

    return None


def build_chat_url(chat_id: str) -> str:
    return f"https://www.facebook.com/messages/t/{chat_id}"


def extract_listing_id(url: str | None) -> str | None:
    normalized = normalize_facebook_url(url)
    if not normalized:
        return None
    match = re.search(r"/marketplace/item/(\d+)", urlparse(normalized).path)
    return match.group(1) if match else None


def parse_listing_location(text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return None, None
    cleaned = " ".join(text.split())
    cleaned = re.sub(r"\s*·\s*Location is approximate\s*$", "", cleaned, flags=re.IGNORECASE).strip()
    match = re.search(r" in ([^,]+),\s*([A-Z]{2})\s*$", cleaned)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    match = re.search(r"^([^,]+),\s*([A-Z]{2})$", cleaned)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return None, None


def guess_sender_from_preview(
    preview: str | None,
    buyer_name: str | None = None,
    *,
    unread: bool = False,
) -> MessageSender:
    if unread:
        return MessageSender.BUYER
    return MessageSender.UNKNOWN


def parse_price_numbers(text: str | None) -> list[float]:
    if not text:
        return []
    return [float(value.replace(",", "")) for value in re.findall(r"\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", text)]


def parse_marketplace_threads_from_graphql(body: str) -> list[dict[str, Any]]:
    threads: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in re.finditer(r'"thread_fbid":"(\d+)"', body):
        thread_id = match.group(1)
        if thread_id in seen:
            continue
        seen.add(thread_id)
        chunk = body[max(0, match.start() - 4000) : match.end() + 800]
        short_names = re.findall(r'"short_name":"([^"]*)"', chunk)
        snippets = re.findall(r'"snippet":"((?:\\.|[^"\\])*)"', chunk)
        titles = re.findall(r'"marketplace_listing_title":"([^"]*)"', chunk)
        unread_counts = re.findall(r'"unread_count":(\d+)', chunk)
        snippet = _decode_graphql_string(snippets[-1]) if snippets else None
        listing_item_id = _extract_messageable_item_id(_messageable_item_chunk(chunk, thread_id))
        threads.append(
            {
                "thread_fbid": thread_id,
                "short_name": short_names[-1] if short_names else None,
                "snippet": snippet,
                "listing_title": titles[-1] if titles else None,
                "listing_item_id": listing_item_id,
                "unread_count": int(unread_counts[-1]) if unread_counts else 0,
            }
        )
    return threads


def match_graphql_thread(
    threads: list[dict[str, Any]],
    buyer_name: str | None,
    preview: str | None,
) -> dict[str, Any] | None:
    short_name = (buyer_name or "").split(" · ", 1)[0].strip().lower()
    if not short_name:
        return None

    candidates = [thread for thread in threads if (thread.get("short_name") or "").lower() == short_name]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    preview_lower = (preview or "").lower()
    for thread in candidates:
        snippet = (thread.get("snippet") or "").lower()
        if snippet and (snippet in preview_lower or preview_lower in snippet):
            return thread
    return candidates[0]


def _messageable_item_chunk(chunk: str, thread_id: str) -> str:
    thread_key_match = re.search(
        rf'"thread_key":\{{"thread_fbid":"{re.escape(thread_id)}"\}}',
        chunk,
    )
    if not thread_key_match:
        return chunk
    before = chunk[: thread_key_match.start()]
    messageable_matches = list(
        re.finditer(
            r'"messageable_item":\{"__typename":"GroupCommerceProductItem"',
            before,
        )
    )
    if not messageable_matches:
        return chunk
    return chunk[messageable_matches[-1].start() : thread_key_match.end()]


def _extract_messageable_item_id(item_chunk: str) -> str | None:
    match = re.search(
        r'"primary_listing_photo":\{"__typename":"ProductImage","image":\{.*?\},"id":"\d+"\},"id":"(\d+)"',
        item_chunk,
        re.DOTALL,
    )
    if match:
        return match.group(1)

    messageable_match = re.search(
        r'"messageable_item":\{"__typename":"GroupCommerceProductItem"',
        item_chunk,
    )
    if not messageable_match:
        return None
    scoped = item_chunk[messageable_match.start() : messageable_match.start() + 6000]
    photo_id: str | None = None
    photo_start = scoped.find('"primary_listing_photo":')
    if photo_start >= 0:
        photo_id_match = re.search(r'"id":"(\d+)"', scoped[photo_start:])
        if photo_id_match:
            photo_id = photo_id_match.group(1)
    for item_id in reversed(re.findall(r'"id":"(\d+)"', scoped)):
        if item_id != photo_id:
            return item_id
    return None


def _decode_graphql_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value.replace('\\"', '"')
