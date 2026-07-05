from __future__ import annotations

from typing import Any

from .classifier import _format_conversation
from .config import AgentConfig
from .llm import chat_completion
from .models import ClassificationResult, HandoffSummary, ReplyContext
from .profile import SellerProfile
from .prompt_templates import render_prompt
from .prompts import _listing_blurb


def _latest_buyer_message(ctx: ReplyContext) -> str | None:
    for message in reversed(ctx.messages):
        if message.sender == "buyer":
            return message.text.strip() or None
    return None


def _buyer_question(
    ctx: ReplyContext,
    *,
    classification: ClassificationResult | None = None,
) -> str | None:
    if classification and classification.question:
        return classification.question
    return _latest_buyer_message(ctx)


def build_handoff_system_prompt(
    ctx: ReplyContext,
    profile: SellerProfile,
    *,
    classification: ClassificationResult | None = None,
) -> str:
    buyer_question = _buyer_question(ctx, classification=classification)
    sections = [
        render_prompt("handoff.intro"),
        _listing_blurb(ctx.listing),
    ]
    if ctx.buyer_name:
        sections.append(render_prompt("handoff.buyer_name", buyer_name=ctx.buyer_name))
    if buyer_question:
        sections.append(render_prompt("handoff.buyer_question", buyer_question=buyer_question))
    if classification and classification.reason:
        sections.append(
            render_prompt("handoff.classifier_note", classifier_reason=classification.reason)
        )
    sections.append(
        render_prompt(
            "handoff.instructions",
            conversation=_format_conversation(ctx.messages, ctx),
        )
    )
    return "\n\n".join(sections)


def build_handoff_messages(
    ctx: ReplyContext,
    profile: SellerProfile,
    *,
    classification: ClassificationResult | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": build_handoff_system_prompt(ctx, profile, classification=classification),
        },
        {
            "role": "user",
            "content": render_prompt("handoff.user"),
        },
    ]


class HandoffSummarizer:
    """Summarize conversations for Telegram handoff notifications."""

    def __init__(self, config: AgentConfig | None = None) -> None:
        self._config = config or AgentConfig.from_env()

    @property
    def config(self) -> AgentConfig:
        return self._config

    def summarize(
        self,
        ctx: ReplyContext,
        *,
        classification: ClassificationResult | None = None,
    ) -> HandoffSummary:
        ctx = ReplyContext(
            chat_id=ctx.chat_id,
            buyer_name=ctx.buyer_name,
            messages=ctx.messages,
            listing=ctx.listing,
            seller_name=ctx.seller_name or self._config.seller_name,
        )
        messages = build_handoff_messages(
            ctx,
            self._config.profile,
            classification=classification,
        )
        text, _usage = chat_completion(self._config, messages, temperature=0.3)
        return HandoffSummary(
            listing_title=ctx.listing.title,
            listing_price=ctx.listing.price,
            buyer_name=ctx.buyer_name,
            buyer_question=_buyer_question(ctx, classification=classification),
            summary_text=text.strip(),
            model=self._config.model,
        )
