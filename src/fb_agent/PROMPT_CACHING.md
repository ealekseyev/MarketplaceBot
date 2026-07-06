# Prompt caching analysis

Assessment of how well `fb_agent` is structured for LLM prompt / context caching, and where token waste comes from today.

## Current state

**No LLM prompt caching is implemented.**

`llm.py` sends a plain `messages` array with no cache markers, prefix splitting, or reuse across subagent calls. The only caching in the repo that touches agent inputs indirectly:

- `listing_cache` — SQLite for scraped Marketplace listings (browser layer, not LLM)
- `lru_cache` on `prompt_templates.load_prompts()` — loads YAML once per process, does not affect token billing

## Calls per buyer message

| Path | LLM calls |
|------|-----------|
| `auto_reply` | Classifier → Responder (2) |
| `need_seller_input` | Classifier → Handoff summarizer (2), then Seller-input responder when seller replies on Telegram (3 total) |
| `hand_off` | Classifier → Handoff summarizer (2) |

Regex hand-off heuristics (phone, pickup time, meetup) skip the classifier LLM entirely — real savings on those messages.

## What each call sends

### Classifier

- **System:** static rules (`classifier.intro`, `classifier.actions`) + listing blurb + pickup + optional stored facts + optional firm-pricing note
- **User:** prior conversation (formatted as `Buyer:` / `Seller:` lines) + latest buyer message

### Responder (`auto_reply`)

- **System:** identity + **current time** + play-dumb + listing + pickup + negotiation rules + output format
- **Messages:** full chat as user/assistant turns

### Handoff summarizer (`need_seller_input` / `hand_off`)

- **System:** handoff intro + listing + buyer name + buyer question + classifier note + **full conversation embedded in instructions**
- **User:** static one-liner

### Seller-input responder

- **System:** same large block as responder (identity, time, listing, pickup, negotiation) + seller's factual answer
- **Messages:** full chat as user/assistant turns

## Cache hit rate today: ~0%

Providers that cache identical prefixes (OpenAI automatic cache on 1024+ token prefixes, Anthropic `cache_control`, etc.) need a **stable prefix** across requests. This architecture breaks that in several places.

### 1. `current_time` in responder system prompt (high impact)

`_current_time_blurb()` is injected near the top of the responder and seller-input system prompts. It changes every request, so the system blob never shares a stable prefix — even for the same chat seconds apart.

### 2. Monolithic system messages (high impact)

Static rules (`prompts.yaml`), semi-static listing data, and dynamic bits are concatenated into one `system` string. Cache-friendly layout is:

```
static rules → per-listing context → dynamic tail
```

ideally as separate message blocks, with dynamic content last.

### 3. Duplication across subagents (medium impact)

The same listing blurb is rebuilt independently in classifier, responder, handoff, and seller-input. The same conversation appears in:

- classifier user prompt (`Buyer: …` / `Seller: …` lines)
- responder chat turns (user/assistant roles)
- handoff system prompt (conversation embedded again)

No sharing between calls.

### 4. Full history re-sent every turn (medium impact)

`format_chat_messages()` sends the entire thread on each new buyer message. Correct for reply quality; expensive for tokens. No incremental append-only pattern.

## What's fine

- Static YAML blocks (`classifier.actions`, negotiation rules, identity) are good cache candidates **if** split out and placed before dynamic content.
- Per-listing context is stable within a thread — could cache across classifier + responder for the same item.
- Marketplace chats are usually short, so absolute cost may still be low unless polling many chats continuously.

## Rough token waste (example: 6-message thread, one listing, `auto_reply`)

| Segment | ~Tokens |
|---------|---------|
| Classifier system (rules + listing) | ~1.5k |
| Classifier user (conversation) | ~0.4k |
| Responder system (rules + listing + time + negotiation) | ~2.0k |
| Responder conversation turns | ~0.6k |
| **Total input per event** | **~4.5k** |

Redundant overlap:

- ~1–1.5k tokens of static rules duplicated across calls
- ~200–800 tokens listing duplicated
- ~300–600+ tokens conversation duplicated in two formats

With good prefix caching on a single listing thread, **30–50%** of input token cost might be recoverable. Today: **~0%**.

## Severity summary

| Issue | Severity |
|-------|----------|
| No cache API / prefix splitting in `llm.py` | High |
| `current_time` early in responder system | High |
| Classifier + responder = 2 calls with overlapping context | Medium |
| Handoff puts conversation in system, not user | Medium |
| Seller-input rebuilds full responder system + seller answer | Medium |
| Long `negotiation.with_price` block in every reply call | Low–medium (cacheable if prefix stable) |

## Recommended improvements (priority order)

1. **Move `current_time` out of the cached prefix** — inject only when the buyer asks about timing, or put it in the last user message.
2. **Split system prompts:** static `prompts.yaml` block (cacheable) → listing block (per-listing cacheable) → dynamic tail.
3. **Use provider cache markers** in `llm.py` (OpenAI automatic on 1024+ token prefixes; Anthropic explicit `cache_control`).
4. **Consider classify + reply in one call** for confident `auto_reply` cases, or skip classifier when heuristics match.
5. **Track conversation prefix per chat** so only new turns are appended (harder with chat-completions format).

## Bottom line

Extracting prompts to `prompts.yaml` helps **editing**; runtime assembly still rebuilds everything fresh per call. Fine for testing and low volume; worth fixing for 24/7 operation across many listings.
