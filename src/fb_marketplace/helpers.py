from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from .models import MessageSender


def normalize_facebook_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.scheme:
        return f"https://www.facebook.com{url}"
    return url


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


def guess_sender_from_preview(preview: str | None, buyer_name: str | None = None) -> MessageSender:
    if not preview:
        return MessageSender.UNKNOWN

    cleaned = preview.strip().lower()
    if cleaned.startswith("you:"):
        return MessageSender.SELLER

    if buyer_name and cleaned.startswith(f"{buyer_name.strip().lower()}:"):
        return MessageSender.BUYER

    return MessageSender.UNKNOWN


def parse_price_numbers(text: str | None) -> list[float]:
    if not text:
        return []
    return [float(value.replace(",", "")) for value in re.findall(r"\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", text)]
