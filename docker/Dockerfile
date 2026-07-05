# Playwright image includes Chromium system dependencies.
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts

RUN pip install --no-cache-dir \
    -e ./src/fb_marketplace \
    -e ./src/fb_store \
    -e ./src/fb_agent \
    -e ./src/fb_telegram \
    -e . \
    && playwright install chromium

ENV PYTHONUNBUFFERED=1 \
    FB_STORE_PATH=/data/fb-bot.sqlite

RUN mkdir -p /data /profile

VOLUME ["/data", "/profile"]

ENTRYPOINT ["fb-bot"]
CMD ["--user-data-dir", "/profile", "--telegram", "--poll-interval", "10"]
