from __future__ import annotations

from fb_agent import AgentConfig, ChatMessageInput, ListingInput, ReplyContext
from fb_marketplace import ChatDetail, ChatMessage, ListingDetail, MessageSender


def message_to_input(message: ChatMessage) -> ChatMessageInput:
    if message.sender == MessageSender.SELLER:
        sender = "seller"
    elif message.sender == MessageSender.BUYER:
        sender = "buyer"
    else:
        sender = "buyer"
    sent_at = message.sent_at.isoformat() if message.sent_at else None
    return ChatMessageInput(sender=sender, text=message.text, sent_at=sent_at)


def listing_to_input(listing: ListingDetail) -> ListingInput:
    return ListingInput(
        title=listing.title,
        description=listing.description,
        price=listing.price,
        condition=listing.condition,
        location_city=listing.location_city,
        location_state=listing.location_state,
    )


def build_reply_context(
    chat: ChatDetail,
    listing: ListingDetail,
    *,
    agent_config: AgentConfig,
) -> ReplyContext:
    return ReplyContext(
        chat_id=chat.summary.chat_id,
        buyer_name=chat.buyer_name,
        messages=[message_to_input(message) for message in chat.messages],
        listing=listing_to_input(listing),
        seller_name=agent_config.seller_name,
    )
