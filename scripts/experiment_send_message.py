#!/usr/bin/env python3
"""Experiment: send Messenger text via Playwright client.send_message().

FINDINGS (document updates here after runs):
- Thread URL: https://www.facebook.com/messages/t/{chat_id}
- Composer: bottom [role="textbox"], aria-label often "Write to {buyer} · {listing}"
- Placeholder visible as "Aa" in body text
- Submit: Enter key primary; fallback [aria-label="Send"]
- Verify: aria-label "Message sent ... by You: {text}" on data-message-id node
- ONLY test chat: 858819563627349 (Evan / Mercedes door panel)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fb_marketplace import FacebookMarketplaceClient, SessionConfig, facebook_credentials_from_env

ALLOWED_CHAT_ID = "858819563627349"

COMPOSER_PROBE_JS = r"""
() => {
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const short = (v, n = 300) => (v || '').replace(/\s+/g, ' ').trim().slice(0, n);

  const textboxes = Array.from(document.querySelectorAll('[role="textbox"]'))
    .filter(visible)
    .map((el) => {
      const rect = el.getBoundingClientRect();
      return {
        tag: el.tagName,
        ariaLabel: short(el.getAttribute('aria-label')),
        ariaPlaceholder: short(el.getAttribute('aria-placeholder')),
        contentEditable: el.getAttribute('contenteditable'),
        text: short(el.innerText, 120),
        rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
        bottomDistance: Math.round(window.innerHeight - rect.bottom),
      };
    })
    .sort((a, b) => b.rect.y - a.rect.y);

  const sendButtons = Array.from(document.querySelectorAll('[aria-label*="Send"], [aria-label*="send"]'))
    .filter(visible)
    .map((el) => ({
      ariaLabel: short(el.getAttribute('aria-label')),
      role: el.getAttribute('role'),
      rect: el.getBoundingClientRect(),
    }));

  const composeLines = (document.body?.innerText || '')
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => /^(Compose|Write to|Aa|Send)$/i.test(l) || /write to/i.test(l));

  return {
    pageUrl: location.href,
    viewport: { w: window.innerWidth, h: window.innerHeight },
    textboxes,
    sendButtons,
    composeLines,
    recommendedTextboxIndex: textboxes.findIndex(
      (tb) => tb.rect.w > 100 && tb.rect.h > 20 && (tb.ariaLabel || '').toLowerCase().includes('write to')
    ),
  };
}
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Experiment: send Messenger message via inline Playwright")
    p.add_argument("--chat-id", default=ALLOWED_CHAT_ID)
    p.add_argument("--text", default="", help="Message body to send (required unless --dry-run)")
    p.add_argument("--dry-run", action="store_true", help="Probe composer selectors only; do not send")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--user-data-dir", default="./.browser-profile")
    p.add_argument("--headful", action="store_true")
    p.add_argument("--manual-login", action="store_true")
    p.add_argument("--timeout-ms", type=int, default=25_000)
    p.add_argument("--output-dir", default="./debug/messenger-chat")
    return p.parse_args()


def _assert_chat_id(chat_id: str) -> None:
    if chat_id != ALLOWED_CHAT_ID:
        raise SystemExit(f"Refusing chat_id={chat_id!r}. Only {ALLOWED_CHAT_ID} is allowed for experiments.")


async def main_async() -> None:
    args = parse_args()
    _assert_chat_id(args.chat_id)

    if not args.dry_run and not args.text.strip():
        raise SystemExit("--text is required unless --dry-run")

    email, password = facebook_credentials_from_env(args.env_file)
    config = SessionConfig(
        user_data_dir=args.user_data_dir,
        headless=not (args.headful or args.manual_login),
        timeout_ms=args.timeout_ms,
        facebook_email=email,
        facebook_password=password,
        manual_login=args.manual_login,
        pause_on_auth_failure=args.headful,
    )

    out_dir = Path(args.output_dir) / args.chat_id
    out_dir.mkdir(parents=True, exist_ok=True)

    async with FacebookMarketplaceClient(config) as client:
        print(f"Opening thread {args.chat_id} via get_chat()...")
        chat_before = await client.get_chat(args.chat_id)
        page = client._require_page()
        print(f"  buyer={chat_before.buyer_name!r} messages={len(chat_before.messages)}")

        probe = await page.evaluate(COMPOSER_PROBE_JS)
        probe["dryRun"] = args.dry_run
        probe["chatId"] = args.chat_id
        probe_path = out_dir / "composer-probe.json"
        probe_path.write_text(json.dumps(probe, indent=2), encoding="utf-8")
        print(f"Wrote {probe_path}")
        print(json.dumps(probe, indent=2))

        await page.screenshot(path=str(out_dir / "composer-screenshot.png"), full_page=True)

        if args.dry_run:
            print("\n[DRY RUN] Composer probe complete. Inspect JSON/screenshot before live send.")
            return

        await client.send_message(args.chat_id, args.text)
        print("Send experiment succeeded.")


if __name__ == "__main__":
    asyncio.run(main_async())
