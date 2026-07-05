from __future__ import annotations

from typing import Any

from .config import AgentConfig
from .llm import chat_completion
from .models import ReplyContext, ReplyDraft
from .profile import SellerProfile
from .prompts import (
    _current_time_blurb,
    _identity_blurb,
    _listing_blurb,
    _negotiation_blurb,
    _pickup_blurb,
    _play_dumb_blurb,
    format_chat_messages,
)


def _stored_facts_blurb(stored_facts: list[str] | None) -> str | None:
    if not stored_facts:
        return None
    lines = "\n".join(f"- {fact}" for fact in stored_facts)
    return f"Stored seller facts (confirmed by the human seller):\n{lines}"


def build_seller_input_system_prompt(
    ctx: ReplyContext,
    profile: SellerProfile,
    seller_answer: str,
    *,
    stored_facts: list[str] | None = None,
) -> str:
    sections = [
        _identity_blurb(ctx.seller_name),
        _current_time_blurb(),
        _play_dumb_blurb(),
        _listing_blurb(ctx.listing),
    ]
    pickup = _pickup_blurb(profile.pickup_location)
    if pickup:
        sections.append(pickup)
    facts = _stored_facts_blurb(stored_facts)
    if facts:
        sections.append(facts)
    sections.extend(
        [
            _negotiation_blurb(ctx.listing, profile),
            (
                "The human seller just provided the factual answer below. "
                "Write a buyer-facing reply that weaves this answer naturally into the conversation.\n"
                f"Seller's answer: {seller_answer.strip()}\n"
                "Rules:\n"
                "- Use ONLY facts from the seller's answer, listing, profile, stored facts, and prior conversation.\n"
                "- Do NOT invent, infer, or guess details beyond what the seller provided.\n"
                "- Keep the same casual, friendly tone as a normal Marketplace text.\n"
                "- Always rephrase the seller's answer into your own words for the buyer; never copy it verbatim.\n"
                "- Answer the buyer's latest question directly; do not over-explain.\n"
                "- If the buyer also asked about price or pickup, follow the negotiation and pickup rules above.\n"
                "- Reply with ONLY the message text you would send to the buyer. "
                "No quotes, no labels, no explanation."
            ),
        ]
    )
    return "\n\n".join(sections)


def build_seller_input_messages(
    ctx: ReplyContext,
    profile: SellerProfile,
    seller_answer: str,
    *,
    stored_facts: list[str] | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": build_seller_input_system_prompt(
                ctx,
                profile,
                seller_answer,
                stored_facts=stored_facts,
            ),
        },
        *format_chat_messages(ctx),
    ]


class SellerInputResponder:
    """Generate buyer replies after the human seller provides missing facts."""

    def __init__(self, config: AgentConfig | None = None) -> None:
        self._config = config or AgentConfig.from_env()

    @property
    def config(self) -> AgentConfig:
        return self._config

    def generate_reply(
        self,
        ctx: ReplyContext,
        seller_answer: str,
        *,
        stored_facts: list[str] | None = None,
    ) -> ReplyDraft:
        ctx = ReplyContext(
            chat_id=ctx.chat_id,
            buyer_name=ctx.buyer_name,
            messages=ctx.messages,
            listing=ctx.listing,
            seller_name=ctx.seller_name or self._config.seller_name,
        )
        messages = build_seller_input_messages(
            ctx,
            self._config.profile,
            seller_answer,
            stored_facts=stored_facts,
        )
        text, usage = chat_completion(self._config, messages)
        return ReplyDraft(
            text=text,
            model=self._config.model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
