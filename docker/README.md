# Docker

Run the Marketplace bot in a container with Playwright + Chromium preinstalled.

## Prerequisites

- Docker
- `.env` in the repo root with Telegram and LLM settings (see root [README.md](../README.md))

Facebook login is **not** in `.env`. Create a browser profile on the host and mount it into the container.

**Important:** Docker `--env-file` does not strip inline comments. Use:

```dotenv
LLM_PROVIDER=openai
```

not `LLM_PROVIDER=openai   # or openai`.

## Browser profile (first time)

On the host:

```bash
python scripts/create_browser_profile.py --profile-dir ./.browser-profile
```

Log into Facebook in the browser window, then press Enter to save the profile.

## Build

From the repo root:

```bash
docker build -f docker/Dockerfile -t fb-bot:latest .
```

Clean rebuild after code changes:

```bash
docker build --no-cache -f docker/Dockerfile -t fb-bot:latest .
```

## Run

```bash
docker run -d --name fb-bot \
  --env-file .env \
  -v "$(pwd)/.browser-profile:/profile" \
  -v "$(pwd)/data:/data" \
  --restart unless-stopped \
  fb-bot:latest
```

Default command: `--user-data-dir /profile --telegram --poll-interval 10`

Logs:

```bash
docker logs -f fb-bot
```

Stop and remove:

```bash
docker stop fb-bot && docker rm fb-bot
```

## Customize

Pass flags after the image name:

```bash
docker run -d --name fb-bot \
  --env-file .env \
  -v "$(pwd)/.browser-profile:/profile" \
  -v "$(pwd)/data:/data" \
  --restart unless-stopped \
  fb-bot:latest \
  --user-data-dir /profile \
  --telegram \
  --poll-interval 6 \
  --verbose \
  --only-chat-id 123456789
```

One-off poll (foreground, removed on exit):

```bash
docker run --rm \
  --env-file .env \
  -v "$(pwd)/.browser-profile:/profile" \
  -v "$(pwd)/data:/data" \
  fb-bot:latest \
  --user-data-dir /profile --telegram --once
```

## Volumes

| Mount | Purpose |
|-------|---------|
| `/profile` | Persistent Chromium session (Facebook login) — mount `./.browser-profile` |
| `/data` | SQLite chat policy DB (`fb-bot.sqlite`, listing cache) |

## Notes

- Container runs **headless** by default (no `--headful`). Use a pre-authenticated profile.
- `ERR_TOO_MANY_REDIRECTS` means `/profile` is empty or not mounted — mount your logged-in profile.
- Rebuild the image after code changes before restarting the container.
