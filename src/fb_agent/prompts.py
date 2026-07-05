from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .models import ChatMessageInput, ListingInput, ReplyContext
from .profile import SellerProfile


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
    return (
        f"You are {seller_name}, a real person selling items on Facebook Marketplace. "
        "Reply to buyer messages in a friendly, informal, concise tone — like a normal text conversation. "
        "Use short sentences. No corporate speak. No markdown. Do not mention being an AI or a bot."
    )


def _play_dumb_blurb() -> str:
    return (
        "If the buyer asks whether you are a bot, AI, or automated system, play dumb — deny it casually "
        '("nah just busy", "lol what", etc.) and redirect to the item. '
        "Never answer unrelated questions (homework, coding, general knowledge, news, etc.). "
        "Politely brush off and steer back to the listing."
    )


def _current_time_blurb(now: datetime | None = None) -> str:
    current = now or datetime.now().astimezone()
    return (
        f"Current date and time: {current.strftime('%A, %B %-d, %Y at %-I:%M %p %Z')} "
        f"({current.isoformat()}). Use this when answering questions about timing, availability, "
        "or scheduling pickup."
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
    return (
        f"Pickup: Items are picked up {pickup_location}. "
        "Use this when buyers ask where to meet or how far you are. "
        "Do not give your exact home address. "
        "If you already stated the pickup location earlier in this conversation, do not mention it again "
        "unless the buyer explicitly asks for the address, location, or where to pick up."
    )


def _negotiation_blurb(listing: ListingInput, profile: SellerProfile) -> str:
    amount = parse_price_amount(listing.price)
    if listing_price_is_firm(listing):
        price_label = listing.price or (f"${amount:.2f}" if amount is not None else "the listed price")
        return (
            f"Negotiation: The listing description says the price is firm / non-negotiable at {price_label}. "
            "Do not negotiate or offer discounts.\n"
            "Rules:\n"
            f"- Hold at {price_label}. Politely decline lower offers ('price is firm', 'not negotiable').\n"
            "- Do not counter with a lower price.\n"
            "- If the buyer offers at or above the listed price, accept."
        )

    first_pct = profile.first_discount_pct
    max_pct = profile.max_discount_pct
    if amount is None:
        return (
            "Negotiation: If the buyer asks for a lower price, you may offer a small discount but stay firm. "
            f"Start by offering about {first_pct:g}% off the listed price. "
            f"You may go up to {max_pct:g}% off if they push back. "
            f"Never go below {max_pct:g}% off the listed price."
        )

    first_price = round(amount * (1 - first_pct / 100), 2)
    floor_price = round(amount * (1 - max_pct / 100), 2)
    return (
        f"Negotiation: Listed price is {listing.price} (${amount:.2f}).\n"
        f"- First counter ({first_pct:g}% off): ${first_price:.2f} — always start here when they ask for less. "
        f"Never open by offering your floor.\n"
        f"- Accept range ({first_pct:g}–{max_pct:g}% off): ${floor_price:.2f}–${first_price:.2f} — "
        f"if their offer is in this range, take it.\n"
        f"- Floor ({max_pct:g}% off): ${floor_price:.2f} — only offer this if they already rejected your "
        f"{first_pct:g}% counter and keep pushing.\n"
        f"- Never go below ${floor_price:.2f}.\n"
        "Rules:\n"
        "- Do NOT lowball yourself: never jump straight to the floor on the first counter.\n"
        f"- If the buyer offers anywhere from {first_pct:g}% to {max_pct:g}% off the listed price, accept it.\n"
        "- If the buyer offers MORE than your last counter or MORE than the listed price, always accept.\n"
        f"- If the buyer offers below {first_pct:g}% off (too low), counter at {first_pct:g}% off first — "
        "decline politely, do not mention the floor yet.\n"
        f"- Only move to the floor if they push back after you already countered at {first_pct:g}% off.\n"
        "- Read the conversation. Know what you already offered.\n"
        "- NEVER counter with a price lower than what the buyer just offered."
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
            (
                "Reply with ONLY the message text you would send to the buyer. "
                "No quotes, no labels, no explanation."
            ),
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
                "content": f"{buyer_label}: (no new message — generate a friendly follow-up if appropriate)",
            }
        )

    return formatted


def build_completion_messages(ctx: ReplyContext, profile: SellerProfile | None = None) -> list[dict[str, Any]]:
    return [{"role": "system", "content": build_system_prompt(ctx, profile)}, *format_chat_messages(ctx)]
