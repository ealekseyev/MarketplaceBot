from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .models import ChatMessageInput, ListingInput, ReplyContext
from .profile import SellerProfile
from .prompt_templates import render_prompt


def parse_price_amount(price: str | None) -> float | None:
    if not price:
        return None
    match = re.search(r"\$?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", price)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def listing_price_is_firm(listing: ListingInput) -> bool:
    description = listing.description or ""
    return bool(
        re.search(r"\bfirm\b", description, re.I)
        or re.search(r"\bnon[\s-]?negotiable\b", description, re.I)
    )


def _identity_blurb(seller_name: str) -> str:
    return render_prompt("shared.identity", seller_name=seller_name)


def _play_dumb_blurb() -> str:
    return render_prompt("shared.play_dumb")


def _current_time_blurb(now: datetime | None = None) -> str:
    current = now or datetime.now().astimezone()
    return render_prompt(
        "shared.current_time",
        current_time_formatted=current.strftime("%A, %B %-d, %Y at %-I:%M %p %Z"),
        current_time_iso=current.isoformat(),
    )


def _listing_blurb(listing: ListingInput) -> str:
    parts = [
        f"Title: {listing.title or 'Unknown'}",
        f"Price: {listing.price or 'Unknown'}",
        f"Condition: {listing.condition or 'Unknown'}",
    ]
    if listing.location_city or listing.location_state:
        city = listing.location_city or "?"
        state = listing.location_state or "?"
        parts.append(f"Location: {city}, {state}")
    if listing.description:
        parts.append(f"Description: {listing.description}")
    return "Listing:\n" + "\n".join(parts)


def _pickup_blurb(pickup_location: str | None) -> str | None:
    if not pickup_location:
        return None
    return render_prompt("shared.pickup", pickup_location=pickup_location)


def stored_facts_blurb(stored_facts: list[str] | None) -> str | None:
    if not stored_facts:
        return None
    facts_lines = "\n".join(f"- {fact}" for fact in stored_facts)
    return render_prompt("shared.stored_facts", facts_lines=facts_lines)


def _negotiation_blurb(listing: ListingInput, profile: SellerProfile) -> str:
    amount = parse_price_amount(listing.price)
    first_pct = profile.first_discount_pct
    max_pct = profile.max_discount_pct

    if listing_price_is_firm(listing):
        price_label = listing.price or (f"${amount:.2f}" if amount is not None else "the listed price")
        return render_prompt("negotiation.firm", price_label=price_label)

    if amount is None:
        return render_prompt(
            "negotiation.unknown_price",
            first_pct=first_pct,
            max_pct=max_pct,
        )

    first_price = round(amount * (1 - first_pct / 100), 2)
    floor_price = round(amount * (1 - max_pct / 100), 2)
    return render_prompt(
        "negotiation.with_price",
        listed_price=listing.price,
        amount=amount,
        first_pct=first_pct,
        max_pct=max_pct,
        first_price=first_price,
        floor_price=floor_price,
    )


def build_system_prompt(ctx: ReplyContext, profile: SellerProfile | None = None) -> str:
    seller_profile = profile or SellerProfile(seller_name=ctx.seller_name)
    sections = [
        _identity_blurb(ctx.seller_name),
        _current_time_blurb(),
        _play_dumb_blurb(),
        _listing_blurb(ctx.listing),
    ]
    pickup = _pickup_blurb(seller_profile.pickup_location)
    if pickup:
        sections.append(pickup)
    sections.extend(
        [
            _negotiation_blurb(ctx.listing, seller_profile),
            render_prompt("responder.output_format"),
        ]
    )
    return "\n\n".join(sections)


def format_chat_messages(ctx: ReplyContext) -> list[dict[str, str]]:
    """OpenAI-style messages for chat history (user/assistant turns)."""
    formatted: list[dict[str, str]] = []
    buyer_label = ctx.buyer_name or "Buyer"

    for message in ctx.messages:
        role = "assistant" if message.sender == "seller" else "user"
        if role == "user":
            content = f"{buyer_label}: {message.text}"
        else:
            content = message.text
        formatted.append({"role": role, "content": content})

    if not formatted or formatted[-1]["role"] != "user":
        formatted.append(
            {
                "role": "user",
                "content": render_prompt("chat.no_new_message", buyer_label=buyer_label),
            }
        )

    return formatted


def build_completion_messages(ctx: ReplyContext, profile: SellerProfile | None = None) -> list[dict[str, Any]]:
    return [{"role": "system", "content": build_system_prompt(ctx, profile)}, *format_chat_messages(ctx)]
