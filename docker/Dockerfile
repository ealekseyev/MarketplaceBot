# Playwright image includes Chromium system dependencies.
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /app

# Dependency manifests only — cached until a pyproject.toml changes.
COPY pyproject.toml README.md ./
COPY src/fb_marketplace/pyproject.toml src/fb_marketplace/
COPY src/fb_store/pyproject.toml src/fb_store/
COPY src/fb_agent/pyproject.toml src/fb_agent/
COPY src/fb_telegram/pyproject.toml src/fb_telegram/

# Stubs so editable installs can resolve dependencies before real source is copied.
RUN mkdir -p src/fb_marketplace src/fb_store src/fb_agent src/fb_telegram \
    && touch \
        src/fb_marketplace/__init__.py \
        src/fb_store/__init__.py \
        src/fb_agent/__init__.py \
        src/fb_agent/agent.yaml \
        src/fb_agent/prompts.yaml \
        src/fb_telegram/__init__.py \
        src/main.py \
        src/orchestrator.py \
        src/adapters.py

RUN pip install --no-cache-dir \
    -e ./src/fb_store \
    -e ./src/fb_marketplace \
    -e ./src/fb_agent \
    -e ./src/fb_telegram \
    -e . \
    && playwright install chromium

# Application source — only this layer rebuilds on typical code changes.
COPY src ./src
COPY scripts ./scripts

ENV PYTHONUNBUFFERED=1 \
    FB_STORE_PATH=/data/fb-bot.sqlite

RUN mkdir -p /data /profile

VOLUME ["/data", "/profile"]

ENTRYPOINT ["fb-bot"]
CMD ["--user-data-dir", "/profile", "--telegram", "--poll-interval", "10"]
