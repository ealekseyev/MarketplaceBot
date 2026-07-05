from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any

from .config import AgentConfig
from .llm import LLMError, chat_completion
from .models import ChatMessageInput, ClassificationResult, ReplyContext
from .profile import SellerProfile
from .prompt_templates import render_prompt
from .prompts import _listing_blurb, _pickup_blurb, listing_price_is_firm, stored_facts_blurb

_CLASSIFIER_TEMPERATURE = 0.1
_VALID_ACTIONS = frozenset({"auto_reply", "need_seller_input", "hand_off"})

_HAND_OFF_PATTERNS = (
    re.compile(r"\b(call|phone|text)\s+me\b", re.I),
    re.compile(r"\b(phone|cell|mobile)\s*(#|number)?\b", re.I),
    re.compile(r"\bvideo\s+call\b", re.I),
    re.compile(r"\bwhat\s+time\b", re.I),
    re.compile(r"\bwhen\b.*\b(pick\s*up|pickup|meet|come\s+(by|get)|grab)\b", re.I),
    re.compile(r"\b(pick\s*up|pickup|meet)\b.*\b(when|today|tomorrow|tonight)\b", re.I),
    re.compile(r"\bcan\s+(we|i)\s+meet\b", re.I),
    re.compile(r"\bmeet\s*up\b", re.I),
    re.compile(r"\bschedule\b.*\b(pick\s*up|pickup|meet)\b", re.I),
)


class MessageAction(str, Enum):
    AUTO_REPLY = "auto_reply"
    NEED_SELLER_INPUT = "need_seller_input"
    HAND_OFF = "hand_off"


def _split_latest_buyer(ctx: ReplyContext) -> tuple[list[ChatMessageInput], str]:
    latest_index: int | None = None
    for index in range(len(ctx.messages) - 1, -1, -1):
        if ctx.messages[index].sender == "buyer":
            latest_index = index
            break
    if latest_index is None:
        raise ValueError("ReplyContext has no buyer message to classify")
    prior = ctx.messages[:latest_index]
    latest = ctx.messages[latest_index].text.strip()
    return prior, latest


def _heuristic_action(message: str) -> MessageAction | None:
    for pattern in _HAND_OFF_PATTERNS:
        if pattern.search(message):
            return MessageAction.HAND_OFF
    return None


def _format_conversation(messages: list[ChatMessageInput], ctx: ReplyContext) -> str:
    if not messages:
        return "(no prior messages)"
    buyer_label = ctx.buyer_name or "Buyer"
    seller_label = ctx.seller_name
    lines: list[str] = []
    for message in messages:
        label = seller_label if message.sender == "seller" else buyer_label
        lines.append(f"{label}: {message.text}")
    return "\n".join(lines)


def build_classifier_system_prompt(
    ctx: ReplyContext,
    profile: SellerProfile,
    *,
    stored_facts: list[str] | None = None,
) -> str:
    sections = [
        render_prompt("classifier.intro"),
        _listing_blurb(ctx.listing),
    ]
    pickup = _pickup_blurb(profile.pickup_location)
    if pickup:
        sections.append(pickup)
    facts = stored_facts_blurb(stored_facts)
    if facts:
        sections.append(facts)
    if listing_price_is_firm(ctx.listing):
        sections.append(render_prompt("classifier.firm_pricing_note"))
    sections.append(render_prompt("classifier.actions"))
    return "\n\n".join(sections)


def build_classifier_user_prompt(ctx: ReplyContext, latest_message: str) -> str:
    prior_messages, _latest = _split_latest_buyer(ctx)
    buyer_label = ctx.buyer_name or "Buyer"
    return render_prompt(
        "classifier.user",
        prior_conversation=_format_conversation(prior_messages, ctx),
        buyer_label=buyer_label,
        latest_message=latest_message,
    )


def build_classifier_messages(
    ctx: ReplyContext,
    profile: SellerProfile,
    *,
    stored_facts: list[str] | None = None,
) -> list[dict[str, str]]:
    _, latest = _split_latest_buyer(ctx)
    return [
        {
            "role": "system",
            "content": build_classifier_system_prompt(ctx, profile, stored_facts=stored_facts),
        },
        {"role": "user", "content": build_classifier_user_prompt(ctx, latest)},
    ]


def build_classifier_prompt(
    ctx: ReplyContext,
    profile: SellerProfile,
    *,
    stored_facts: list[str] | None = None,
) -> str:
    """Full classifier prompt for debugging (system + user turns)."""
    parts = build_classifier_messages(ctx, profile, stored_facts=stored_facts)
    return "\n\n--- USER ---\n\n".join(message["content"] for message in parts)


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise LLMError(f"Classifier did not return JSON: {text!r}")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise LLMError(f"Classifier JSON must be an object: {parsed!r}")
    return parsed


def _parse_classification(text: str) -> ClassificationResult:
    payload = _extract_json_object(text)
    action = str(payload.get("action", "")).strip().lower()
    if action not in _VALID_ACTIONS:
        raise LLMError(f"Classifier returned invalid action {action!r}: {payload!r}")

    reason = str(payload.get("reason", "")).strip()
    if not reason:
        raise LLMError(f"Classifier returned empty reason: {payload!r}")

    question = payload.get("question")
    if question is not None:
        question = str(question).strip() or None

    return ClassificationResult(action=action, reason=reason, question=question)


class MessageClassifier:
    """Decide if a buyer message can be auto-replied or needs seller input."""

    def __init__(self, config: AgentConfig | None = None) -> None:
        self._config = config or AgentConfig.from_env()

    @property
    def config(self) -> AgentConfig:
        return self._config

    def classify(
        self,
        ctx: ReplyContext,
        *,
        stored_facts: list[str] | None = None,
    ) -> ClassificationResult:
        _, latest = _split_latest_buyer(ctx)

        heuristic = _heuristic_action(latest)
        if heuristic is MessageAction.HAND_OFF:
            return ClassificationResult(
                action=MessageAction.HAND_OFF.value,
                reason="Buyer message requires human handoff (scheduling or direct contact).",
                question=None,
                model=self._config.model,
            )

        messages = build_classifier_messages(ctx, self._config.profile, stored_facts=stored_facts)
        text, _usage = chat_completion(
            self._config,
            messages,
            temperature=_CLASSIFIER_TEMPERATURE,
        )
        result = _parse_classification(text)
        result.model = self._config.model
        return result
