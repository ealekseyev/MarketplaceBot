from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class MessageSender(StrEnum):
    BUYER = "buyer"
    SELLER = "seller"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class SessionConfig:
    user_data_dir: str
    headless: bool = True
    browser_channel: str | None = None
    slow_mo_ms: int = 0
    timeout_ms: int = 15_000
    scroll_pause_ms: int = 750
    facebook_email: str | None = None
    facebook_password: str | None = None
    facebook_home_url: str = "https://www.facebook.com/"
    facebook_login_url: str = "https://www.facebook.com/login"
    marketplace_inbox_url: str = "https://www.facebook.com/marketplace/inbox"


@dataclass(slots=True)
class ChatSummary:
    chat_id: str
    chat_url: str
    unread: bool
    latest_message_sender: MessageSender
    latest_message_preview: str | None = None
    latest_message_label: str | None = None
    latest_message_at: datetime | None = None
    latest_message_age_seconds: int | None = None
    buyer_name: str | None = None
    listing_name: str | None = None
    listing_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ChatMessage:
    sender: MessageSender
    text: str
    message_id: str | None = None
    timestamp_label: str | None = None
    sent_at: datetime | None = None
    age_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ListingDetail:
    url: str
    canonical_url: str | None = None
    title: str | None = None
    description: str | None = None
    price_text: str | None = None
    location_text: str | None = None
    seller_notes: str | None = None
    raw_metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ChatDetail:
    summary: ChatSummary
    buyer_name: str | None = None
    listing_name: str | None = None
    listing_url: str | None = None
    messages: list[ChatMessage] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
