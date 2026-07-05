from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from fb_marketplace import facebook_credentials_from_env

DEFAULT_CHATS = {
    "Shawn": "2131486027397586",
    "Max": "1200198092232951",
    "Junior": "2485540785247111",
}

SCROLL_TO_START_JS = r"""
() => {
  const findScroller = () => {
    let candidates = Array.from(document.querySelectorAll('div, section, main')).filter((node) => {
      const style = window.getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return ['auto', 'scroll'].includes(style.overflowY)
        && node.scrollHeight > node.clientHeight + 100
        && rect.height > 250
        && rect.width > 250;
    });
    candidates.sort((a, b) => b.clientHeight - a.clientHeight);
    return candidates[0] || null;
  };
  const scroller = findScroller();
  if (scroller) {
    scroller.setAttribute('data-fb-bot-thread-scroll', 'true');
    scroller.scrollTop = 0;
    return { found: true, scrollHeight: scroller.scrollHeight, clientHeight: scroller.clientHeight };
  }
  return { found: false };
}
"""

MESSAGE_PROBE_JS = r"""
() => {
  const short = (value, max = 500) => (value || '').replace(/\s+/g, ' ').trim().slice(0, max);
  const viewportMid = window.innerWidth / 2;
  const root = document.querySelector('[data-fb-bot-thread-scroll="true"]') || document.body;

  const ariaNodes = Array.from(document.querySelectorAll(
    '[aria-label*="Message sent"], [aria-label*="message sent"], '
    + '[aria-label*="Message received"], [aria-label*="message received"]'
  ));

  const dataIdNodes = Array.from(document.querySelectorAll('[data-message-id]'));
  const rowNodes = Array.from(root.querySelectorAll('[role="row"]'));
  const listitemNodes = Array.from(root.querySelectorAll('[role="listitem"]'));

  const collectAttrs = (node) => {
    const out = {};
    for (const attr of node.attributes || []) {
      if (attr.name.startsWith('data-') || attr.name.startsWith('aria-') || attr.name === 'role' || attr.name === 'id') {
        out[attr.name] = short(attr.value, 300);
      }
    }
    return out;
  };

  const extractEntry = (node, strategy) => {
    const rect = node.getBoundingClientRect();
    const ariaLabel = node.getAttribute('aria-label') || '';
    const timeNode = node.querySelector('time');
    const centerX = rect.left + rect.width / 2;
    const sideFromAria = /message received/i.test(ariaLabel) ? 'buyer'
      : (/message sent/i.test(ariaLabel) ? 'seller' : null);
    const sideFromPos = centerX >= viewportMid ? 'seller' : 'buyer';
    return {
      strategy,
      text: short(node.innerText, 1200),
      ariaLabel: short(ariaLabel, 600),
      messageId: node.getAttribute('data-message-id') || node.getAttribute('id') || null,
      timestampLabel: timeNode?.getAttribute('datetime') || short(timeNode?.textContent, 80) || null,
      rect: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) },
      sideFromAria,
      sideFromPos,
      attrs: collectAttrs(node),
      tagName: node.tagName,
      outerHtmlSnippet: short(node.outerHTML, 900),
    };
  };

  const entries = [];
  const seen = new Set();
  const addNodes = (nodes, strategy) => {
    for (const node of nodes) {
      const key = (node.getAttribute('aria-label') || '') + '::' + (node.innerText || '').slice(0, 120);
      if (seen.has(key)) continue;
      seen.add(key);
      const entry = extractEntry(node, strategy);
      if (entry.text || entry.ariaLabel) entries.push(entry);
    }
  };

  addNodes(ariaNodes, 'aria_message');
  addNodes(dataIdNodes, 'data_message_id');
  addNodes(rowNodes.filter((n) => (n.innerText || '').trim().length > 0), 'role_row');
  addNodes(listitemNodes.filter((n) => (n.innerText || '').trim().length > 0), 'role_listitem');

  entries.sort((a, b) => a.rect.y - b.rect.y);

  const ariaMessages = entries.filter((e) => e.strategy === 'aria_message');
  const parsed = ariaMessages.map((entry) => {
    const label = entry.ariaLabel || '';
    const lower = label.toLowerCase();
    let sender = null;
    let timestamp = null;
    let body = entry.text;
    let isSystem = false;

    const sentMatch = label.match(/^Message sent (.+?) by (.+?)(?:: (.+))?$/i);
    const recvMatch = label.match(/^Message received (.+?) from (.+?)(?:: (.+))?$/i);
    if (sentMatch) {
      timestamp = sentMatch[1];
      sender = sentMatch[2].trim().toLowerCase() === 'you' ? 'seller' : 'buyer';
      body = sentMatch[3] || entry.text;
    } else if (recvMatch) {
      timestamp = recvMatch[1];
      sender = 'buyer';
      body = recvMatch[3] || entry.text;
    } else if (/message sent .+ by$/i.test(label)) {
      isSystem = true;
    }

    const textLower = (body || entry.text || '').toLowerCase();
    const systemPatterns = [
      'started this chat',
      'to help identify and reduce scams',
      'waiting for your response',
      'rate this person',
      'rate seller',
      'rate buyer',
      'mark as',
      'view buyer profile',
      'view seller profile',
      'you can now message and call each other',
      'facebook marketplace assistant',
      'is this still available',
    ];
    if (systemPatterns.some((p) => textLower.includes(p))) {
      isSystem = true;
    }

    return {
      ...entry,
      parsedSender: sender || entry.sideFromAria || entry.sideFromPos,
      parsedTimestamp: timestamp || entry.timestampLabel,
      parsedText: body,
      likelySystem: isSystem,
    };
  });

  const uniqueAria = [...new Set(entries.map((e) => e.ariaLabel).filter(Boolean))];
  const bodyLines = (document.body?.innerText || '').split('\n').map((l) => l.trim()).filter(Boolean);

  return {
    pageUrl: location.href,
    title: document.title,
    viewportWidth: window.innerWidth,
    strategyCounts: {
      aria_message: ariaNodes.length,
      data_message_id: dataIdNodes.length,
      role_row: rowNodes.length,
      role_listitem: listitemNodes.length,
      unique_entries: entries.length,
    },
    messages: entries,
    parsedMessages: parsed,
    uniqueAriaLabels: uniqueAria,
    bodyLinesSample: bodyLines.slice(0, 100),
    headingText: short(document.querySelector('h1, h2, h3, [role="heading"]')?.textContent),
    listingLink: document.querySelector('a[href*="/marketplace/item/"]')?.href || null,
  };
}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe Messenger thread DOM for chat history extraction")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--user-data-dir", default="./.browser-profile")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--manual-login", action="store_true")
    parser.add_argument("--timeout-ms", type=int, default=25_000)
    parser.add_argument("--output-dir", default="./debug/messenger-chat")
    parser.add_argument("--chat-id", action="append", default=[], help="chat id to probe (repeatable); defaults to Shawn/Max/Junior")
    parser.add_argument("--scroll-passes", type=int, default=25)
    return parser.parse_args()


async def _is_login_page(page: Any) -> bool:
    if "login" in page.url or "recover" in page.url:
        return True
    for sel in ('input[name="email"]', 'input[name="pass"]'):
        if await page.locator(sel).count() > 0:
            return True
    return False


async def _wait_for_login(page: Any, manual: bool) -> None:
    if not manual:
        raise RuntimeError("Login required. Rerun with --headful --manual-login")
    print("Complete Facebook login in the browser window...")
    while await _is_login_page(page):
        await page.wait_for_timeout(2_000)


async def _scroll_thread_to_start(page: Any, passes: int) -> dict[str, Any]:
    await page.evaluate(SCROLL_TO_START_JS)
    last_height = -1
    stable = 0
    metrics: dict[str, Any] = {"passes": 0, "stableAtTop": False}
    scroller = page.locator('[data-fb-bot-thread-scroll="true"]').first
    if await scroller.count() == 0:
        metrics["scrollerFound"] = False
        return metrics
    metrics["scrollerFound"] = True
    for i in range(passes):
        await scroller.evaluate("(el) => { el.scrollTop = 0; }")
        await page.wait_for_timeout(600)
        m = await scroller.evaluate("(el) => ({ top: el.scrollTop, height: el.scrollHeight })")
        metrics["passes"] = i + 1
        metrics["lastMetrics"] = m
        if m["top"] == 0 and m["height"] == last_height:
            stable += 1
            if stable >= 2:
                metrics["stableAtTop"] = True
                break
        else:
            stable = 0
        last_height = m["height"]
    return metrics


async def _wait_for_thread(page: Any, timeout_ms: int) -> bool:
    try:
        await page.wait_for_selector(
            'h1, h2, h3, [role="heading"], '
            '[aria-label*="Message sent"], [aria-label*="Message received"], '
            '[role="textbox"]',
            timeout=timeout_ms,
        )
        return True
    except Exception:
        return False


def _classify_system_messages(parsed: list[dict[str, Any]]) -> list[str]:
    patterns: set[str] = set()
    for msg in parsed:
        if msg.get("likelySystem"):
            text = (msg.get("parsedText") or msg.get("text") or "").strip()
            if text:
                patterns.add(text[:200])
            label = msg.get("ariaLabel") or ""
            if label:
                patterns.add(label[:200])
    return sorted(patterns)


def _summarize_chat(name: str, chat_id: str, probe: dict[str, Any], scroll: dict[str, Any]) -> dict[str, Any]:
    parsed = probe.get("parsedMessages") or []
    real = [m for m in parsed if not m.get("likelySystem")]
    system = [m for m in parsed if m.get("likelySystem")]
    return {
        "name": name,
        "chatId": chat_id,
        "url": probe.get("pageUrl"),
        "loaded": bool(parsed),
        "scroll": scroll,
        "strategyCounts": probe.get("strategyCounts"),
        "totalAriaMessages": len(parsed),
        "realMessages": len(real),
        "systemMessages": len(system),
        "systemPatterns": _classify_system_messages(parsed),
        "chronologicalSample": [
            {
                "y": m.get("rect", {}).get("y"),
                "sender": m.get("parsedSender"),
                "timestamp": m.get("parsedTimestamp"),
                "text": (m.get("parsedText") or m.get("text") or "")[:120],
                "system": m.get("likelySystem"),
            }
            for m in parsed[:20]
        ],
        "realMessageSample": [
            {
                "sender": m.get("parsedSender"),
                "timestamp": m.get("parsedTimestamp"),
                "text": (m.get("parsedText") or m.get("text") or "")[:160],
            }
            for m in real[:10]
        ],
    }


async def main_async() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    chats = dict(DEFAULT_CHATS)
    if args.chat_id:
        chats = {f"chat_{cid}": cid for cid in args.chat_id}

    email, password = facebook_credentials_from_env(args.env_file)
    summaries: list[dict[str, Any]] = []

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            args.user_data_dir,
            headless=not (args.headful or args.manual_login),
        )
        page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(args.timeout_ms)

        # Warm session on facebook.com (not marketplace inbox)
        await page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
        await page.wait_for_timeout(1_500)
        if await _is_login_page(page):
            if email and password:
                await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")
                await page.locator('input[name="email"]').first.fill(email)
                await page.locator('input[name="pass"]').first.fill(password)
                await page.locator('button[name="login"], input[name="login"]').first.click()
                await page.wait_for_timeout(4_000)
            if await _is_login_page(page):
                await _wait_for_login(page, args.manual_login)

        for name, chat_id in chats.items():
            chat_dir = output_dir / chat_id
            chat_dir.mkdir(parents=True, exist_ok=True)
            url = f"https://www.facebook.com/messages/t/{chat_id}"

            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3_000)
            loaded = await _wait_for_thread(page, args.timeout_ms)
            scroll = await _scroll_thread_to_start(page, args.scroll_passes)
            await page.wait_for_timeout(1_500)

            probe = await page.evaluate(MESSAGE_PROBE_JS)
            probe["directNavigation"] = True
            probe["requestedUrl"] = url
            probe["threadLoaded"] = loaded

            (chat_dir / "probe.json").write_text(json.dumps(probe, indent=2), encoding="utf-8")
            (chat_dir / "page.html").write_text(await page.content(), encoding="utf-8")
            await page.screenshot(path=str(chat_dir / "screenshot.png"), full_page=True)

            summary = _summarize_chat(name, chat_id, probe, scroll)
            summaries.append(summary)
            (chat_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            print(f"{name} ({chat_id}): {summary['realMessages']} real / {summary['systemMessages']} system messages")

        await context.close()

    report = {
        "approach": "direct navigation to https://www.facebook.com/messages/t/{chat_id}",
        "chats": summaries,
        "aggregateSystemPatterns": sorted({p for s in summaries for p in s.get("systemPatterns", [])}),
        "recommendations": _recommendations(summaries),
    }
    report_path = output_dir / "FINDINGS.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    md_path = output_dir / "FINDINGS.md"
    md_path.write_text(_findings_markdown(report), encoding="utf-8")

    print(f"\nWrote {report_path}")
    print(f"Wrote {md_path}")


def _recommendations(summaries: list[dict[str, Any]]) -> list[str]:
    loaded = [s for s in summaries if s.get("loaded")]
    recs = [
        "Skip list_chats/inbox in get_chat for numeric thread IDs; goto build_chat_url(chat_id) from any page.",
        "Use aria-label nodes matching 'Message sent|received' as primary message selector (same as _extract_messages).",
        "Parse sender from aria-label: 'Message sent {ts} by You:' -> seller, '... by {name}:' -> buyer; 'Message received {ts} from {name}:' -> buyer.",
        "Use horizontal position (centerX >= viewport/2) as fallback sender when aria-label missing.",
        "Sort messages by getBoundingClientRect().y ascending for chronological order.",
        "Scroll thread scroller to scrollTop=0 repeatedly until scrollHeight stabilizes before extraction.",
        "Filter system messages by text/aria patterns listed in aggregateSystemPatterns.",
        "_parse_message_aria_label should also handle 'Message received ... from ...' pattern (currently only sent).",
    ]
    if not loaded:
        recs.insert(0, "WARNING: no chats loaded messages; verify auth/session before changing client.py")
    return recs


def _findings_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Messenger Chat History Research",
        "",
        "## Approach",
        report.get("approach", ""),
        "",
        "## Per-chat results",
    ]
    for chat in report.get("chats", []):
        lines.append(f"### {chat.get('name')} (`{chat.get('chatId')}`)")
        lines.append(f"- URL: {chat.get('url')}")
        lines.append(f"- Loaded: {chat.get('loaded')}")
        lines.append(f"- Messages: {chat.get('realMessages')} real, {chat.get('systemMessages')} system")
        lines.append(f"- Strategy counts: `{json.dumps(chat.get('strategyCounts'))}`")
        if chat.get("realMessageSample"):
            lines.append("- Sample real messages:")
            for msg in chat["realMessageSample"][:5]:
                lines.append(f"  - [{msg.get('sender')}] ({msg.get('timestamp')}) {msg.get('text')}")
        lines.append("")

    lines.extend(["## System message patterns to filter", ""])
    for pattern in report.get("aggregateSystemPatterns", []):
        lines.append(f"- `{pattern[:160]}`")

    lines.extend(["", "## Recommended client.py changes (not implemented)", ""])
    for rec in report.get("recommendations", []):
        lines.append(f"- {rec}")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    asyncio.run(main_async())
