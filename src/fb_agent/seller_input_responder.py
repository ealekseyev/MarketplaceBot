from __future__ import annotations

from typing import Any

from .config import AgentConfig
from .llm import chat_completion
from .models import ReplyContext, ReplyDraft
from .profile import SellerProfile
from .prompt_templates import render_prompt
from .prompts import (
    _current_time_blurb,
    _identity_blurb,
    _listing_blurb,
    _negotiation_blurb,
    _pickup_blurb,
    _play_dumb_blurb,
    format_chat_messages,
    stored_facts_blurb,
)


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
    facts = stored_facts_blurb(stored_facts)
    if facts:
        sections.append(facts)
    sections.extend(
        [
            _negotiation_blurb(ctx.listing, profile),
            render_prompt("seller_input.task", seller_answer=seller_answer.strip()),
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
