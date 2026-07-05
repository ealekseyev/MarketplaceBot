# fb-bot

Monorepo for a Facebook Marketplace inbox bot: browser extraction, chat policy, LLM replies, and Telegram seller alerts.

## Stack

- Python 3.11+
- Playwright (`fb_marketplace`)
- OpenAI-compatible LLM (`fb_agent`)

## Packages

| Package | Path | Role |
|---------|------|------|
| `fb-marketplace` | `src/fb_marketplace` | Playwright extraction, `MarketplaceSession` SDK, CLI |
| `fb-store` | `src/fb_store` | Chat policy, outbound logs, blacklist |
| `fb-agent` | `src/fb_agent` | Classify, auto-reply, seller-input, handoff summaries |
| `fb-telegram` | `src/fb_telegram` | Seller notifications and seller-input replies |

See [plan-modules.md](plan-modules.md) for architecture and data flow.

## Install

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ./src/fb_marketplace -e ./src/fb_store -e ./src/fb_agent -e ./src/fb_telegram -e .
playwright install chromium
```

The root `fb-bot` package wires the orchestrator (`main.py`) and depends on the four packages above.

## Facebook login (browser profile)

Facebook auth is **not** configured through `.env`. The bot uses a persistent Chromium profile directory; you log in once in a real browser window and the session is saved there.

Create a profile with:

```bash
python scripts/create_browser_profile.py --name seller1
```

Or point at a specific directory:

```bash
python scripts/create_browser_profile.py --profile-dir ./.browser-profile
```

The script opens Facebook, waits for you to complete login/CAPTCHA/checkpoint manually, verifies Marketplace inbox access, then saves the profile when you press Enter.

Reuse that same `--user-data-dir` for all later commands. No Facebook username or password is required in `.env`.

Optional: pass `--use-env-credentials` to `create_browser_profile.py` if you still want to try auto-fill from env vars, but manual login is the supported path.

## Configuration

### `.env`

Used for Telegram and LLM settings only.

```dotenv
# Telegram (required when running with --telegram)
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=your_numeric_chat_id

# LLM — local OpenAI-compatible server (default)
LLM_PROVIDER=local
LLM_BASE_URL=http://127.0.0.1:8080/v1
LLM_API_KEY=local
LLM_MODEL=qwen3.6-27b-mtp

# Or OpenAI / compatible hosted API
# LLM_PROVIDER=openai
# LLM_BASE_URL=https://api.openai.com/v1
# LLM_API_KEY=sk-...
# LLM_MODEL=gpt-4.1-mini
```

Telegram setup details: [src/fb_telegram/TELEGRAM_SETUP.md](src/fb_telegram/TELEGRAM_SETUP.md)

### Seller profile and prompts

Edit these without changing Python code:

- `src/fb_agent/agent.yaml` — seller name, pickup area, negotiation percentages
- `src/fb_agent/prompts.yaml` — system prompts for classifier, responder, handoff, seller-input

Override paths with `FB_AGENT_PROFILE` and `FB_AGENT_PROMPTS` if needed.

## Run the bot

Poll Marketplace inbox, classify buyer messages, auto-reply when safe, and notify you on Telegram for handoffs or missing facts:

```bash
PYTHONPATH=src python -m main \
  --user-data-dir ./.browser-profile \
  --telegram \
  --headful \
  --poll-interval 10
```

Useful flags:

| Flag | Purpose |
|------|---------|
| `--user-data-dir` | Persistent Chromium profile (required) |
| `--telegram` | Enable Telegram notifications and seller-input replies |
| `--headful` | Show the browser window |
| `--poll-interval` | Seconds between inbox polls (default `60`) |
| `--reply-delay-seconds` | Wait before replying to a new buyer message (default `120`) |
| `--only-chat-id` | Process one chat for testing |
| `--once` | Single poll iteration, then exit |
| `--verbose` | Debug logging |

Local SQLite state is stored under `./data/` (gitignored).

## Marketplace CLI (debug / extraction)

```bash
fb-marketplace inbox --user-data-dir ./.browser-profile --headful
fb-marketplace chat <chat_id> --user-data-dir ./.browser-profile
fb-marketplace listing <listing_url> --user-data-dir ./.browser-profile
```

`--manual-login` is still available on the CLI if a saved profile needs re-auth in a visible browser.

## Other scripts

```bash
python scripts/create_browser_profile.py --name seller1
python scripts/test_agent_reply.py
python scripts/test_marketplace_login_and_list_chats.py --user-data-dir ./.browser-profile
```

## Notes

- Facebook DOM changes frequently; selector tuning may be needed after live runs.
- Handoffs and seller-input requests include a direct Marketplace chat link in Telegram.
- SDK docs: [src/fb_marketplace/SDK.md](src/fb_marketplace/SDK.md)
