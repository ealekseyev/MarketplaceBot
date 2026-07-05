# Messenger Chat History Research

## Approach
direct navigation to https://www.facebook.com/messages/t/{chat_id}

## Per-chat results
### chat_2131486027397586 (`2131486027397586`)
- URL: https://www.facebook.com/messages/t/2131486027397586
- Loaded: True
- Messages: 2 real, 2 system
- Strategy counts: `{"aria_message": 4, "data_message_id": 4, "role_row": 0, "role_listitem": 0, "unique_entries": 8}`
- Sample real messages:
  - [seller] (None) Enter, Message sent Thursday 8:28am by Shawn: Do you know what it's out of? Like a duster or charger? Thanks 🤙🏼
  - [seller] (None) Enter, Message sent Thursday 8:28am by Shawn

## System message patterns to filter

- `Enter, Message sent Thursday 2:38pm by Shawn: Shawn is waiting for your response.`
- `Enter, Message sent Thursday 8:28am by Shawn: Shawn started this chat.`

## Recommended client.py changes (not implemented)

- Skip list_chats/inbox in get_chat for numeric thread IDs; goto build_chat_url(chat_id) from any page.
- Use aria-label nodes matching 'Message sent|received' as primary message selector (same as _extract_messages).
- Parse sender from aria-label: 'Message sent {ts} by You:' -> seller, '... by {name}:' -> buyer; 'Message received {ts} from {name}:' -> buyer.
- Use horizontal position (centerX >= viewport/2) as fallback sender when aria-label missing.
- Sort messages by getBoundingClientRect().y ascending for chronological order.
- Scroll thread scroller to scrollTop=0 repeatedly until scrollHeight stabilizes before extraction.
- Filter system messages by text/aria patterns listed in aggregateSystemPatterns.
- _parse_message_aria_label should also handle 'Message received ... from ...' pattern (currently only sent).
