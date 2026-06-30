# fb-bot

Extraction-only scaffold for Facebook Marketplace inbox data.

## Stack

- Python 3.11+
- Playwright

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
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

On first run, the browser will try to log in with the credentials from `.env`. If Facebook asks for checkpoint or two-factor verification, this scaffold stops and reports that explicitly.

## Commands

```bash
fb-marketplace inbox --user-data-dir ./.browser-profile --env-file ./.env
fb-marketplace chat <chat_id> --user-data-dir ./.browser-profile --env-file ./.env
fb-marketplace listing <listing_url> --user-data-dir ./.browser-profile --env-file ./.env
python3 scripts/test_marketplace_login_and_list_chats.py --env-file ./.env --user-data-dir ./.browser-profile --headful
```

## Notes

- The current code does not send messages.
- Facebook DOM changes frequently. Selector tuning will likely be needed after the first live run.
- Login currently supports direct email/password only. Two-factor, checkpoint, and approval challenges are not implemented.
- The data models already expose the fields needed for later reply logic and human-override detection.
