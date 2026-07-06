from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ChatMessageInput:
    sender: str
    text: str
    sent_at: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "sender": self.sender,
            "text": self.text,
            "sent_at": self.sent_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ChatMessageInput:
        return cls(
            sender=str(data["sender"]),
            text=str(data["text"]),
            sent_at=data.get("sent_at") if data.get("sent_at") is None else str(data["sent_at"]),
        )


@dataclass(slots=True)
class ListingInput:
    title: str | None = None
    description: str | None = None
    price: str | None = None
    condition: str | None = None
    location_city: str | None = None
    location_state: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "title": self.title,
            "description": self.description,
            "price": self.price,
            "condition": self.condition,
            "location_city": self.location_city,
            "location_state": self.location_state,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ListingInput:
        return cls(
            title=data.get("title") if data.get("title") is None else str(data["title"]),
            description=data.get("description") if data.get("description") is None else str(data["description"]),
            price=data.get("price") if data.get("price") is None else str(data["price"]),
            condition=data.get("condition") if data.get("condition") is None else str(data["condition"]),
            location_city=data.get("location_city") if data.get("location_city") is None else str(data["location_city"]),
            location_state=data.get("location_state") if data.get("location_state") is None else str(data["location_state"]),
        )


@dataclass(slots=True)
class ReplyContext:
    chat_id: str
    buyer_name: str | None
    messages: list[ChatMessageInput]
    listing: ListingInput
    seller_name: str = "Dennis"

    def to_dict(self) -> dict[str, object]:
        return {
            "chat_id": self.chat_id,
            "buyer_name": self.buyer_name,
            "messages": [message.to_dict() for message in self.messages],
            "listing": self.listing.to_dict(),
            "seller_name": self.seller_name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ReplyContext:
        messages = data.get("messages") or []
        listing = data.get("listing") or {}
        return cls(
            chat_id=str(data["chat_id"]),
            buyer_name=data.get("buyer_name") if data.get("buyer_name") is None else str(data["buyer_name"]),
            messages=[ChatMessageInput.from_dict(message) for message in messages],
            listing=ListingInput.from_dict(listing),
            seller_name=str(data.get("seller_name", "Dennis")),
        )


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

    def to_dict(self) -> dict[str, str | None]:
        return {
            "action": self.action,
            "reason": self.reason,
            "question": self.question,
            "model": self.model,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ClassificationResult:
        return cls(
            action=str(data["action"]),
            reason=str(data["reason"]),
            question=data.get("question") if data.get("question") is None else str(data["question"]),
            model=data.get("model") if data.get("model") is None else str(data["model"]),
        )


@dataclass(slots=True)
class HandoffSummary:
    listing_title: str | None
    listing_price: str | None
    buyer_name: str | None
    buyer_question: str | None
    summary_text: str
    model: str | None = None
