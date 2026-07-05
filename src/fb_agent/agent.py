from __future__ import annotations

from enum import Enum

from .classifier import MessageAction, MessageClassifier
from .config import AgentConfig
from .models import ClassificationResult, ReplyContext


class AgentAction(str, Enum):
    REPLY = "reply"
    NEED_SELLER_INPUT = "need_seller_input"
    HAND_OFF = "hand_off"
    WAIT = "wait"


_ACTION_MAP = {
    MessageAction.AUTO_REPLY: AgentAction.REPLY,
    MessageAction.NEED_SELLER_INPUT: AgentAction.NEED_SELLER_INPUT,
    MessageAction.HAND_OFF: AgentAction.HAND_OFF,
}


def classify_message(
    ctx: ReplyContext,
    *,
    config: AgentConfig | None = None,
    stored_facts: list[str] | None = None,
) -> ClassificationResult:
    return MessageClassifier(config).classify(ctx, stored_facts=stored_facts)


def decide_action(
    ctx: ReplyContext,
    *,
    config: AgentConfig | None = None,
    stored_facts: list[str] | None = None,
) -> AgentAction:
    """Decide whether to auto-reply, ask the seller, hand off, or wait."""
    if not ctx.messages or ctx.messages[-1].sender != "buyer":
        return AgentAction.WAIT

    result = classify_message(ctx, config=config, stored_facts=stored_facts)
    return _ACTION_MAP[MessageAction(result.action)]
