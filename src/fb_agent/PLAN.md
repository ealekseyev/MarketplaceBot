# fb_agent plan

LLM layer for Marketplace buyer replies. No Playwright, no DB — receives structured chat + listing data from `main.py`.

## Steps

| Step | Status | Purpose |
|------|--------|---------|
| 1. Handoff classifier | **Later** | Decide if buyer needs human (meetup scheduling, serious buyer). → Telegram |
| 2. Auto-reply generator | **Now** | Friendly reply + Q&A + negotiation within rules |

## Step 2 flow (implemented)

```
ReplyContext (buyer_name, messages[], listing)
       │
       ▼
build_system_prompt()  ── identity, play-dumb rules, listing, negotiation
       │
       ▼
format chat history as OpenAI messages
       │
       ▼
POST {base_url}/chat/completions  (OpenAI-compatible)
       │
       ▼
ReplyDraft { text }
```

## Step 1 flow (future)

```
ReplyContext
       │
       ▼
classify_handoff()  ── separate prompt or structured output
       │
       ├── hand_off → fb_telegram, skip reply
       └── continue → generate_reply()
```

Signals for handoff: wants to meet in person, asks for phone/call, complex scheduling, high-value negotiation edge cases.

## Integration (main loop)

```python
if not store.is_allowed(chat_id) or store.is_blacklisted(chat_id):
    continue
if latest_message.sender != "buyer":
    continue

detail = await session.get_chat(chat_id)
listing = await session.get_listing(detail.listing["id"])

# Step 1 (later): action = await agent.classify_handoff(ctx)
action = AgentAction.REPLY

if action == AgentAction.REPLY:
    draft = await responder.generate_reply(ctx)
    await session.send_message(chat_id, draft.text)
    store.log_outbound(...)
```

## Config

| Env / field | Default |
|-------------|---------|
| `OPENAI_BASE_URL` | `http://10.0.30.33:8080/v1` |
| `OPENAI_MODEL` | `qwen3.6-27b-mtp` |
| `OPENAI_API_KEY` | `local` (unused by local server) |
| `AGENT_SELLER_NAME` | seller display name in prompts |

## Negotiation rules (in system prompt)

- Parse listing price from context.
- If buyer negotiates: first counter = **5% off** listing price.
- May go up to **10% off** if buyer pushes back.
- **Never below 10% off** — hold firm or deflect.

## Module layout

```
fb_agent/
  PLAN.md          this file
  config.py        AgentConfig
  models.py        ReplyContext, ReplyDraft, input types
  prompts.py       system + message formatting
  llm.py           OpenAI-compatible HTTP client
  responder.py     MarketplaceResponder.generate_reply()
  agent.py           AgentAction, decide_action (stub)
```
