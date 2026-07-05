# Module architecture

Split the monolith into four pip-installable packages under `src/`, orchestrated by `src/main.py`.

## Packages

| Package | Responsibility | Depends on |
|---------|----------------|------------|
| `fb_marketplace` | Playwright extraction, `MarketplaceSession` SDK, CLI | playwright |
| `fb_store` | Persistence: allow/deny lists, outbound message log, human-override blacklist | stdlib or sqlite |
| `fb_agent` | LLM reply logic, reply eligibility, hand-off to human | fb_store, LLM client |
| `fb_telegram` | Notify seller (interested buyers, hand-offs, errors) | telegram bot API |

## Install layout

Monorepo with workspace-style editable installs:

```
fb-bot/
  pyproject.toml          # root meta or workspace config
  src/
    fb_marketplace/
    fb_agent/
    fb_telegram/
    fb_store/
    main.py               # bot runner / orchestrator
```

Each package gets its own `pyproject.toml` (or one root `[tool.setuptools.packages.find]` listing all four). Dev install:

```bash
pip install -e ./src/fb_marketplace
pip install -e ./src/fb_store
pip install -e ./src/fb_agent
pip install -e ./src/fb_telegram
# or: pip install -e .  once root pyproject declares all packages
```

Root `main.py` depends on all four; individual packages must not import each other circularly.

## Boundaries

```
fb_marketplace  ──reads FB──►  (no writes to FB yet except future send_message)
       ▲
       │ poll / send
       │
    main.py  ◄──►  fb_store  (state, logs, blacklist)
       │
       ├──►  fb_agent  (decide reply vs hand-off; no Playwright)
       └──►  fb_telegram  (alerts only; no FB access)
```

- **fb_marketplace**: browser session, scrape, future send. No LLM, no DB, no Telegram.
- **fb_store**: single source of truth for chat policy and message history. No browser, no LLM.
- **fb_agent**: pure decision + prompt assembly from store + marketplace data. No I/O except LLM API.
- **fb_telegram**: outbound notifications only. No scraping, no reply generation.

## Data flow (steady state)

```
┌─────────────┐
│  main loop  │  every N seconds
└──────┬──────┘
       │ list_chats()
       ▼
┌─────────────┐     denied/blacklisted     ┌──────────┐
│  fb_store   │ ◄──────────────────────────│ skip chat│
│ is_allowed? │                            └──────────┘
└──────┬──────┘
       │ allowed + unread buyer message
       ▼
┌─────────────┐     get_chat + get_listing
│ fb_marketplace
└──────┬──────┘
       ▼
┌─────────────┐     reply / hand_off / wait
│  fb_agent   │
└──────┬──────┘
       │ hand_off                          │ auto_reply (after delay)
       ▼                                   ▼
┌─────────────┐                     send_message()
│ fb_telegram │                     log outbound → fb_store
└─────────────┘
```

1. Poll inbox via `MarketplaceSession.list_chats`.
2. `fb_store` filters: allow list, deny list, blacklist, already-replied threads.
3. For eligible chats: fetch thread + listing context.
4. `fb_agent` decides: auto-reply, defer (2-min window), or hand off to human.
5. On auto-reply: `send_message` → log message id/text in `fb_store`.
6. On hand-off or high intent (meetup): `fb_telegram` alerts seller.

## Human interject detection

```
Seller sends message in FB UI (not via bot)
       │
       ▼
Poll detects new seller message not in fb_store outbound log
       │
       ▼
fb_store.blacklist_chat(chat_id, reason="human_override")
       │
       ▼
fb_agent skips chat; optional fb_telegram ping ("you took over chat X")
```

Detection compares `ChatMessage` with `sender=seller` against logged bot outbound messages. Unlogged seller messages ⇒ human took over ⇒ permanent blacklist for that chat (until manual reset in store).

## Current vs future

| Area | Now | Future |
|------|-----|--------|
| Packages | `fb_marketplace` only | + `fb_store`, `fb_agent`, `fb_telegram` |
| Entry point | `fb-marketplace` CLI, test scripts | `python -m main` or `fb-bot run` |
| FB I/O | Read: inbox, thread, listing | + `send_message` |
| State | None | SQLite/file store in `fb_store` |
| Replies | None | LLM via `fb_agent`, 2-min delay |
| Alerts | None | Telegram via `fb_telegram` |
| Human override | Raw seller messages exposed | `fb_store` blacklist on mismatch |

## `src/main.py` (orchestrator)

Minimal loop:

1. Load config (.env: FB creds, Telegram token, OpenAI key, poll interval).
2. Open `MarketplaceSession` + store + agent + telegram clients.
3. Run poll loop; on shutdown, close session.

No business logic in `main.py` — wire modules only.
