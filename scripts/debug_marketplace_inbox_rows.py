from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any

from fb_marketplace import FacebookMarketplaceClient, SessionConfig, facebook_credentials_from_env

INBOX_URL = "https://www.facebook.com/marketplace/inbox?targetTab=SELLER"

ROW_PROBE_JS = r"""
() => {
  const short = (value, max = 400) => (value || '').replace(/\s+/g, ' ').trim().slice(0, max);

  const isChatButton = (row) => {
    const rect = row.getBoundingClientRect();
    const rowText = (row.textContent || '').trim();
    return rect.x > 200 && rect.width > 200 && rect.height >= 40 && rowText.length > 10;
  };

  const threadIdFromHref = (href) => {
    if (!href) return null;
    const m1 = href.match(/\/messages\/t\/([^/?#]+)/);
    if (m1) return m1[1];
    const m2 = href.match(/[?&]thread_id=([^&#]+)/);
    return m2 ? m2[1] : null;
  };

  const collectDataAttrs = (el) => {
    const out = {};
    for (const attr of el.attributes || []) {
      if (attr.name.startsWith('data-') || attr.name.startsWith('aria-')) {
        out[attr.name] = short(attr.value, 300);
      }
    }
    return out;
  };

  const scanNodeForThreadIds = (root) => {
    const ids = new Set();
    const hrefs = new Set();

    root.querySelectorAll('a[href]').forEach((a) => {
      const href = a.getAttribute('href') || '';
      hrefs.add(href);
      const id = threadIdFromHref(href);
      if (id) ids.add(id);
    });

    const html = root.innerHTML || '';
    for (const m of html.matchAll(/\/messages\/t\/(\d+)/g)) ids.add(m[1]);
    for (const m of html.matchAll(/thread_id=(\d+)/g)) ids.add(m[1]);
    for (const m of html.matchAll(/"thread_fbid":"(\d+)"/g)) ids.add(m[1]);
    for (const m of html.matchAll(/"thread_id":"(\d+)"/g)) ids.add(m[1]);

    root.querySelectorAll('*').forEach((node) => {
      for (const attr of node.attributes || []) {
        const val = attr.value || '';
        const id = threadIdFromHref(val);
        if (id) ids.add(id);
        for (const m of val.matchAll(/\b(\d{10,20})\b/g)) {
          if (attr.name.includes('thread') || attr.name.includes('id') || val.includes('message')) {
            ids.add(m[1]);
          }
        }
      }
    });

    return { threadIds: [...ids], hrefs: [...hrefs].slice(0, 20) };
  };

  const findInboxScroller = () => {
    const candidates = Array.from(document.querySelectorAll('div, section, main, ul')).filter((node) => {
      const style = window.getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      const hasThreads = node.querySelector('a[href*="/messages/t/"]')
        || Array.from(node.querySelectorAll('div[role="button"][tabindex="0"]')).some(isChatButton);
      const isScrollable = ['auto', 'scroll', 'overlay'].includes(style.overflowY)
        || node.scrollHeight > node.clientHeight + 20;
      return hasThreads && isScrollable && rect.width > 200 && rect.height > 100;
    });
    candidates.sort((a, b) => b.scrollHeight - a.scrollHeight);
    return candidates[0] || document;
  };

  const root = findInboxScroller();

  const anchorRows = Array.from(root.querySelectorAll('a[href*="/messages/t/"], a[href*="thread_id="]'))
    .filter((anchor) => /\/messages\/t\/[^/?#]+/.test(anchor.getAttribute('href') || '') || /thread_id=([^&#]+)/.test(anchor.getAttribute('href') || ''))
    .map((anchor, index) => {
      const row = anchor.closest('[role="row"], [role="listitem"], li, section, article') || anchor;
      const rect = row.getBoundingClientRect();
      const scan = scanNodeForThreadIds(row);
      return {
        kind: 'anchor',
        index,
        buyerGuess: short((row.textContent || '').split('\n')[0]),
        rowText: short(row.textContent, 200),
        anchorHref: anchor.getAttribute('href'),
        anchorResolvedHref: anchor.href,
        threadIdFromAnchor: threadIdFromHref(anchor.getAttribute('href') || anchor.href),
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
        scan,
        rowDataAttrs: collectDataAttrs(row),
        anchorDataAttrs: collectDataAttrs(anchor),
        outerHtmlSnippet: short(row.outerHTML, 1200),
      };
    });

  const buttonRows = Array.from(root.querySelectorAll('div[role="button"][tabindex="0"]'))
    .filter(isChatButton)
    .map((row, index) => {
      const rect = row.getBoundingClientRect();
      const scan = scanNodeForThreadIds(row);
      const parent = row.parentElement;
      const parentScan = parent ? scanNodeForThreadIds(parent) : { threadIds: [], hrefs: [] };
      const grandparent = parent?.parentElement;
      const grandparentScan = grandparent ? scanNodeForThreadIds(grandparent) : { threadIds: [], hrefs: [] };
      return {
        kind: 'button',
        index,
        buyerGuess: short((row.textContent || '').split('\n')[0]),
        rowText: short(row.textContent, 200),
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
        scan,
        parentScan,
        grandparentScan,
        rowDataAttrs: collectDataAttrs(row),
        ariaLabel: row.getAttribute('aria-label'),
        outerHtmlSnippet: short(row.outerHTML, 1200),
      };
    });

  const pageThreadIds = scanNodeForThreadIds(document.body);

  return {
    pageUrl: location.href,
    rootTag: root.tagName,
    rootClass: short(root.className, 120),
    anchorRowCount: anchorRows.length,
    buttonRowCount: buttonRows.length,
    pageLevelThreadIds: pageThreadIds.threadIds.slice(0, 50),
    anchorRows,
    buttonRows,
  };
}
"""


CLICK_PROBE_JS = r"""
(nameNeedle) => {
  const short = (value, max = 200) => (value || '').replace(/\s+/g, ' ').trim().slice(0, max);
  const isChatButton = (row) => {
    const rect = row.getBoundingClientRect();
    const rowText = (row.textContent || '').trim();
    return rect.x > 200 && rect.width > 200 && rect.height >= 40 && rowText.length > 10;
  };

  const rows = Array.from(document.querySelectorAll('div[role="button"][tabindex="0"]')).filter(isChatButton);
  const needle = (nameNeedle || '').toLowerCase();
  const match = rows.find((row) => (row.textContent || '').toLowerCase().includes(needle));
  if (!match) {
    return { clicked: false, reason: 'no button row contains ' + nameNeedle };
  }

  const beforeUrl = location.href;
  const beforeText = short(match.textContent, 120);
  match.click();
  return { clicked: true, beforeUrl, beforeText, rowText: short(match.textContent, 200) };
}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dump Marketplace inbox row HTML to find real thread IDs")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--user-data-dir", default="./.browser-profile")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--manual-login", action="store_true")
    parser.add_argument("--timeout-ms", type=int, default=20_000)
    parser.add_argument("--output-dir", default="./debug/marketplace-inbox")
    parser.add_argument("--click-name", default="Shawn", help="click first inbox row containing this name and capture resulting URL")
    parser.add_argument("--no-click", action="store_true", help="skip click probe")
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    email, password = facebook_credentials_from_env(args.env_file)
    config = SessionConfig(
        user_data_dir=args.user_data_dir,
        headless=not (args.headful or args.manual_login),
        timeout_ms=args.timeout_ms,
        facebook_email=email,
        facebook_password=password,
        manual_login=args.manual_login,
        pause_on_auth_failure=args.headful,
        marketplace_inbox_url=INBOX_URL,
    )

    click_result: dict[str, Any] | None = None
    network_bodies: list[dict[str, Any]] = []

    async with FacebookMarketplaceClient(config) as client:
        page = client._require_page()  # noqa: SLF001 research script

        async def on_response(response: Any) -> None:
            url = response.url
            if "/api/graphql" not in url:
                return
            try:
                body = await response.text()
            except Exception:  # noqa: BLE001 research script
                return
            network_bodies.append({"url": url, "status": response.status, "body": body})

        page.on("response", on_response)
        await page.goto(INBOX_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3_000)

        dump = await page.evaluate(ROW_PROBE_JS)
        grid_probe = await page.evaluate(
            r"""
            () => {
              const threadId = (href) => {
                const m = (href || '').match(/\/messages\/t\/(\d+)/);
                return m ? m[1] : null;
              };
              const selectors = [
                '[role="grid"] a[href*="/messages/t/"]',
                'a[href*="/messages/t/"][role="link"]',
                '[role="listitem"] a[href*="/messages/t/"]',
              ];
              const out = {};
              for (const sel of selectors) {
                out[sel] = Array.from(document.querySelectorAll(sel)).map((a, index) => ({
                  index,
                  href: a.getAttribute('href'),
                  text: (a.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120),
                  threadId: threadId(a.getAttribute('href')),
                  rect: (() => {
                    const r = (a.closest('[role="listitem"], [role="row"], li') || a).getBoundingClientRect();
                    return { x: r.x, y: r.y, width: r.width, height: r.height };
                  })(),
                }));
              }
              return out;
            }
            """
        )
        dump["gridProbe"] = grid_probe
        html_path = output_dir / "inbox.html"
        html_path.write_text(await page.content(), encoding="utf-8")
        await page.screenshot(path=str(output_dir / "inbox.png"), full_page=True)

        if not args.no_click and args.click_name:
            network_bodies.clear()
            click_result = await page.evaluate(CLICK_PROBE_JS, args.click_name)
            await page.wait_for_timeout(4_000)
            click_result["afterUrl"] = page.url
            click_result["afterTitle"] = await page.title()

            thread_match = re.search(r"/messages/t/(\d+)", page.url)
            click_result["threadIdFromUrl"] = thread_match.group(1) if thread_match else None

            post_click_dump = await page.evaluate(ROW_PROBE_JS)
            click_result["selectedRowAfterClick"] = _find_row_by_name(post_click_dump, args.click_name)
            click_result["threadIdsInDomAfterClick"] = await page.evaluate(
                r"""
                () => {
                  const ids = new Set();
                  const html = document.body?.innerHTML || '';
                  for (const m of html.matchAll(/\/messages\/t\/(\d+)/g)) ids.add(m[1]);
                  for (const m of html.matchAll(/"thread_fbid":"(\d+)"/g)) ids.add(m[1]);
                  for (const m of html.matchAll(/"thread_id":"(\d+)"/g)) ids.add(m[1]);
                  for (const m of html.matchAll(/"client_thread_id":"(\d+)"/g)) ids.add(m[1]);
                  return [...ids];
                }
                """
            )

            click_result["networkAfterClick"] = _extract_thread_ids_from_network(network_bodies, args.click_name)

            (output_dir / "after-click.html").write_text(await page.content(), encoding="utf-8")
            await page.screenshot(path=str(output_dir / "after-click.png"), full_page=True)

    report = {
        "inboxUrl": INBOX_URL,
        "staticProbe": dump,
        "clickProbe": click_result,
        "analysis": _analyze(dump, click_result, args.click_name),
    }

    json_path = output_dir / "inbox-row-probe.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Wrote {json_path}")
    print(f"Wrote {html_path}")
    print()
    print("=== ANALYSIS ===")
    for line in report["analysis"]:
        print(line)


def _extract_thread_ids_from_network(bodies: list[dict[str, Any]], click_name: str) -> dict[str, Any]:
    thread_ids: set[str] = set()
    snippets: list[dict[str, str]] = []
    needle = click_name.lower()
    for item in bodies:
        body = item.get("body") or ""
        url = item.get("url") or ""
        for match in re.finditer(r'"(?:thread_fbid|thread_id|client_thread_id)":"(\d{10,20})"', body):
            thread_ids.add(match.group(1))
        for match in re.finditer(r"/messages/t/(\d{10,20})", body):
            thread_ids.add(match.group(1))
        if needle in body.lower() or "mopar" in body.lower():
            idx = body.lower().find(needle)
            if idx < 0:
                idx = body.lower().find("mopar")
            snippets.append({"url": url, "snippet": body[max(0, idx - 200) : idx + 400]})
    return {"graphqlCount": len(bodies), "threadIds": sorted(thread_ids), "snippets": snippets[:8]}


def _find_row_by_name(dump: dict[str, Any], name: str) -> dict[str, Any] | None:
    needle = name.lower()
    for kind in ("buttonRows", "anchorRows"):
        for row in dump.get(kind, []):
            if needle in (row.get("buyerGuess") or "").lower() or needle in (row.get("rowText") or "").lower():
                return row
    return None


def _analyze(dump: dict[str, Any], click_result: dict[str, Any] | None, click_name: str) -> list[str]:
    lines: list[str] = []

    shawn_buttons = [
        row for row in dump.get("buttonRows", [])
        if click_name.lower() in (row.get("buyerGuess") or "").lower()
        or click_name.lower() in (row.get("rowText") or "").lower()
    ]
    shawn_anchors = [
        row for row in dump.get("anchorRows", [])
        if click_name.lower() in (row.get("buyerGuess") or "").lower()
        or click_name.lower() in (row.get("rowText") or "").lower()
    ]

    lines.append(f"Page: {dump.get('pageUrl')}")
    lines.append(f"Rows: {dump.get('anchorRowCount')} anchor, {dump.get('buttonRowCount')} button")
    lines.append(f"Rows matching '{click_name}': {len(shawn_anchors)} anchor, {len(shawn_buttons)} button")

    for i, row in enumerate(shawn_buttons):
        lines.append(f"  button[{i}] scan.threadIds={row.get('scan', {}).get('threadIds')}")
        lines.append(f"  button[{i}] parent.threadIds={row.get('parentScan', {}).get('threadIds')}")
        lines.append(f"  button[{i}] grandparent.threadIds={row.get('grandparentScan', {}).get('threadIds')}")
        lines.append(f"  button[{i}] hrefs={row.get('scan', {}).get('hrefs')}")

    for i, row in enumerate(shawn_anchors):
        lines.append(f"  anchor[{i}] threadIdFromAnchor={row.get('threadIdFromAnchor')}")
        lines.append(f"  anchor[{i}] scan.threadIds={row.get('scan', {}).get('threadIds')}")

    if click_result:
        lines.append(f"Click '{click_name}': clicked={click_result.get('clicked')}")
        lines.append(f"  before={click_result.get('beforeUrl')}")
        lines.append(f"  after={click_result.get('afterUrl')}")
        lines.append(f"  threadIdFromUrl={click_result.get('threadIdFromUrl')}")
        lines.append(f"  threadIdsInDomAfterClick={click_result.get('threadIdsInDomAfterClick')}")
        net = click_result.get("networkAfterClick") or {}
        lines.append(f"  network.threadIds={net.get('threadIds')}")

    grid = dump.get("gridProbe") or {}
    for sel, rows in grid.items():
        visible = [r for r in rows if (r.get("rect") or {}).get("width", 0) > 0]
        lines.append(f"gridProbe {sel}: total={len(rows)} visible={len(visible)}")
        for row in visible[:3]:
            lines.append(f"  -> {row.get('threadId')} | {row.get('text')}")

    # Summarize where IDs appear across all button rows
    buttons_with_ids = [
        row for row in dump.get("buttonRows", [])
        if row.get("scan", {}).get("threadIds")
    ]
    lines.append(f"Button rows with thread IDs in HTML: {len(buttons_with_ids)}/{dump.get('buttonRowCount')}")

    if buttons_with_ids:
        sample = buttons_with_ids[0]
        lines.append(
            f"Sample button row '{sample.get('buyerGuess')}' ids={sample.get('scan', {}).get('threadIds')}"
        )

    return lines


if __name__ == "__main__":
    asyncio.run(main_async())
