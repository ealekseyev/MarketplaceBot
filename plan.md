## Goal

Build a Facebook Marketplace assistant for one seller account. The current phase is extraction only. It should gather enough inbox, thread, and listing context to support later decision-making, logging, human-override detection, and LLM-based replies.

## Chosen Stack

- Python 3.11+
- Playwright for browser automation against Facebook web UI
- Dataclasses and standard library types for models
- No database yet
- No LLM integration yet
- No autonomous reply logic yet

## Current Scope

Implement a base extraction layer with functions that can:

1. Open Facebook Marketplace or Messenger using a persistent logged-in browser profile.
2. List chats with metadata including:
   - Facebook-native chat ID
   - chat URL
   - whether the chat appears unread
   - whether the latest visible message appears to be from the buyer or seller
   - latest message preview
   - how long ago the latest visible message arrived, when detectable
   - buyer name when detectable
   - listing name and listing URL when detectable
3. Fetch one chat by chat ID and return:
   - thread metadata
   - entire visible chat history after scrolling upward until older messages stop loading
   - listing link
   - listing name
4. Fetch one listing by URL and return:
   - listing title
   - description
   - price text when detectable
   - location text when detectable
   - canonical URL
5. Provide deterministic helpers that make later reply-eligibility logic easy, without sending messages.

## Design Notes

- Use a persistent Chromium profile so Facebook login survives restarts.
- Keep selectors and DOM heuristics isolated in one module because Facebook changes markup often.
- Prefer deterministic code for message direction, unread detection, thread identity, and timestamp parsing.
- Keep the scraper read-only for now.
- Expose a small CLI for manually dumping inbox, chat, and listing JSON during development.

## Important Constraints

- Facebook does not provide a clean official personal Marketplace automation API for this use case.
- This implementation relies on browser automation and DOM heuristics.
- Some fields are best-effort until tested against the live account.
- No attempt is made yet to distinguish bot-written seller messages from human-written seller messages. The extraction layer only returns raw message data needed for that later step.

## Next Phase After This Scaffold

1. Validate selectors against the real account.
2. Add a local state store for thread metadata and known outbound bot messages.
3. Add human-override detection.
4. Add the 2-minute delayed response scheduler.
5. Add listing-aware prompt assembly and OpenAI-compatible LLM calls.
6. Add Telegram alerting for meetup intent.
