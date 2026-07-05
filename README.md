# fb-bot

Monorepo for a Facebook Marketplace inbox bot: extraction, persistence, LLM replies, and Telegram alerts.

## Stack

- Python 3.11+
- Playwright (`fb_marketplace`)

## Packages

| Package | Path | Role |
|---------|------|------|
| `fb-marketplace` | `src/fb_marketplace` | Playwright extraction, `MarketplaceSession` SDK, CLI |
| `fb-store` | `src/fb_store` | Chat policy, outbound logs, blacklist |
| `fb-agent` | `src/fb_agent` | Reply vs hand-off decisions |
| `fb-telegram` | `src/fb_telegram` | Seller notifications |

See [plan-modules.md](plan-modules.md) for architecture and data flow.

## Install

Install everything from the repo root (recommended):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ./src/fb_marketplace -e ./src/fb_store -e ./src/fb_agent -e ./src/fb_telegram -e .
playwright install chromium
```

The root `fb-bot` package wires the orchestrator (`main.py`) and depends on the four packages above.

Or install packages individually:

```bash
pip install -e ./src/fb_marketplace
pip install -e ./src/fb_store
pip install -e ./src/fb_agent
pip install -e ./src/fb_telegram
```

## Credentials

Create a `.env` file in the project root.

```dotenv
FACEBOOK_EMAIL="you@example.com"
FACEBOOK_PASSWORD="replace-me"
```

The code will also accept `FACEBOOK_USERNAME`, `FB_EMAIL`, and `FB_PASSWORD`.

## First Login

The scraper uses a persistent Chromium profile. Pick a directory and reuse it.

```bash
fb-marketplace inbox --user-data-dir ./.browser-profile --env-file ./.env --headful
```

Recommended first run: use manual login so you can complete CAPTCHA/checkpoint once and save the session in the persistent browser profile.

```bash
fb-marketplace inbox --user-data-dir ./.browser-profile --manual-login
```

After that, reuse the same `--user-data-dir`; the saved session should skip login.

The older automatic email/password flow still exists, but Facebook may block it with CAPTCHA.

## Commands

```bash
fb-marketplace inbox --user-data-dir ./.browser-profile --env-file ./.env
fb-marketplace inbox --user-data-dir ./.browser-profile --manual-login
fb-marketplace chat <chat_id> --user-data-dir ./.browser-profile --env-file ./.env
fb-marketplace listing <listing_url> --user-data-dir ./.browser-profile --env-file ./.env
fb-bot --user-data-dir ./.browser-profile --once
python3 scripts/test_marketplace_login_and_list_chats.py --user-data-dir ./.browser-profile --manual-login
python3 scripts/debug_facebook_login_page.py --headful
```

## Notes

- The orchestrator (`fb-bot`) is a wiring stub; use `fb-marketplace` CLI for extraction today.
- Facebook DOM changes frequently. Selector tuning will likely be needed after the first live run.
- Login currently supports direct email/password only. Two-factor, checkpoint, and approval challenges are not implemented.
- SDK docs: [src/fb_marketplace/SDK.md](src/fb_marketplace/SDK.md)
