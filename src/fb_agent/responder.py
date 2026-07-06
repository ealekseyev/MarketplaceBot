from __future__ import annotations

from .config import AgentConfig
from .llm import chat_completion
from .models import ReplyContext, ReplyDraft
from .prompts import build_completion_messages


class MarketplaceResponder:
    """Generate buyer replies via an OpenAI-compatible LLM."""

    def __init__(self, config: AgentConfig | None = None) -> None:
        self._config = config or AgentConfig.from_env()

    @property
    def config(self) -> AgentConfig:
        return self._config

    def generate_reply(self, ctx: ReplyContext) -> ReplyDraft:
        ctx = ReplyContext(
            chat_id=ctx.chat_id,
            buyer_name=ctx.buyer_name,
            messages=ctx.messages,
            listing=ctx.listing,
            seller_name=ctx.seller_name or self._config.seller_name,
        )
        messages = build_completion_messages(ctx, self._config.profile)
        text, usage = chat_completion(self._config, messages)
        return ReplyDraft(
            text=text,
            model=self._config.model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
