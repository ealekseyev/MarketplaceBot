# Docker

Run the Marketplace bot in a container with Playwright + Chromium preinstalled.

## Prerequisites

- Docker and Docker Compose
- `.env` in the repo root with Telegram and LLM settings (see root [README.md](../README.md))

Facebook login is **not** in `.env`. You need a saved browser profile mounted at `/profile`.

## Build

From the repo root:

```bash
docker compose -f docker/docker-compose.yml build
```

## Browser profile (first time)

**Recommended:** create the profile on the host, then mount it:

```bash
python scripts/create_browser_profile.py --profile-dir ./.browser-profile
```

Update `docker-compose.yml` to bind-mount it:

```yaml
volumes:
  - ../.browser-profile:/profile
  - bot-data:/data
```

**Or** use the compose setup service (needs a display or remote desktop for the Chromium window):

```bash
docker compose -f docker/docker-compose.yml --profile setup run --rm browser-setup
```

## Run

```bash
docker compose -f docker/docker-compose.yml up -d
```

Logs:

```bash
docker compose -f docker/docker-compose.yml logs -f fb-bot
```

Stop:

```bash
docker compose -f docker/docker-compose.yml down
```

## Customize

Override the bot command in `docker-compose.yml`, for example:

```yaml
command:
  - --user-data-dir
  - /profile
  - --telegram
  - --poll-interval
  - "10"
  - --verbose
  - --only-chat-id
  - "123456789"
```

Or run a one-off poll:

```bash
docker compose -f docker/docker-compose.yml run --rm fb-bot \
  --user-data-dir /profile --telegram --once
```

## Volumes

| Mount | Purpose |
|-------|---------|
| `/profile` | Persistent Chromium session (Facebook login) |
| `/data` | SQLite chat policy DB (`fb-bot.sqlite`, listing cache) |

Named volumes `browser-profile` and `bot-data` are used by default. Switch to host paths if you prefer files you can inspect directly.

## Notes

- Container runs **headless** by default (no `--headful`). Use a pre-authenticated profile.
- Rebuild the image after code changes: `docker compose -f docker/docker-compose.yml build --no-cache`
