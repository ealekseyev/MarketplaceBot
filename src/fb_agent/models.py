from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ChatMessageInput:
    sender: str
    text: str
    sent_at: str | None = None


@dataclass(slots=True)
class ListingInput:
    title: str | None = None
    description: str | None = None
    price: str | None = None
    condition: str | None = None
    location_city: str | None = None
    location_state: str | None = None


@dataclass(slots=True)
class ReplyContext:
    chat_id: str
    buyer_name: str | None
    messages: list[ChatMessageInput]
    listing: ListingInput
    seller_name: str = "Dennis"


@dataclass(slots=True)
class ReplyDraft:
    text: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(slots=True)
class ClassificationResult:
    action: str
    reason: str
    question: str | None = None
    model: str | None = None


@dataclass(slots=True)
class HandoffSummary:
    listing_title: str | None
    listing_price: str | None
    buyer_name: str | None
    buyer_question: str | None
    summary_text: str
    model: str | None = None
