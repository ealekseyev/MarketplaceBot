from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect the live Facebook login page and dump candidate submit controls")
    parser.add_argument("--output-dir", default="./debug/facebook-login", help="directory for screenshot and json dump")
    parser.add_argument("--headful", action="store_true", help="run Chromium with a visible window")
    parser.add_argument("--timeout-ms", type=int, default=20_000)
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(output_dir / "profile"),
            headless=not args.headful,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(args.timeout_ms)

        await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")
        await page.wait_for_timeout(2_000)

        dump = await page.evaluate(
            r"""
            () => {
              const isVisible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };

              const short = (value) => (value || '').replace(/\s+/g, ' ').trim().slice(0, 500);

              const buttons = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"], [role="button"]'))
                .filter(isVisible)
                .map((el, index) => ({
                  index,
                  tag: el.tagName.toLowerCase(),
                  id: el.id || null,
                  name: el.getAttribute('name'),
                  type: el.getAttribute('type'),
                  text: short(el.textContent || el.getAttribute('value') || ''),
                  ariaLabel: el.getAttribute('aria-label'),
                  dataTestId: el.getAttribute('data-testid'),
                  className: short(el.className || ''),
                  outerHtml: short(el.outerHTML),
                }));

              const forms = Array.from(document.querySelectorAll('form')).map((form, index) => ({
                index,
                id: form.id || null,
                action: form.getAttribute('action'),
                method: form.getAttribute('method'),
                inputNames: Array.from(form.querySelectorAll('input')).map((input) => ({
                  name: input.getAttribute('name'),
                  type: input.getAttribute('type'),
                  id: input.id || null,
                })),
                submitButtons: Array.from(form.querySelectorAll('button, input[type="submit"], input[type="button"]')).map((el) => ({
                  tag: el.tagName.toLowerCase(),
                  id: el.id || null,
                  name: el.getAttribute('name'),
                  type: el.getAttribute('type'),
                  text: short(el.textContent || el.getAttribute('value') || ''),
                })),
              }));

              const loginInputs = Array.from(document.querySelectorAll('input')).filter((input) => {
                const name = (input.getAttribute('name') || '').toLowerCase();
                return name === 'email' || name === 'pass';
              }).map((input) => ({
                name: input.getAttribute('name'),
                id: input.id || null,
                type: input.getAttribute('type'),
                visible: isVisible(input),
              }));

              return {
                url: location.href,
                title: document.title,
                loginInputs,
                forms,
                buttons,
                bodyTextPreview: short(document.body?.innerText || ''),
              };
            }
            """
        )

        screenshot_path = output_dir / "facebook-login.png"
        json_path = output_dir / "facebook-login.json"
        html_path = output_dir / "facebook-login.html"

        await page.screenshot(path=str(screenshot_path), full_page=True)
        html_path.write_text(await page.content(), encoding="utf-8")
        json_path.write_text(json.dumps(dump, indent=2), encoding="utf-8")

        await context.close()

    print(f"Wrote screenshot: {screenshot_path}")
    print(f"Wrote JSON dump: {json_path}")
    print(f"Wrote HTML dump: {html_path}")


if __name__ == "__main__":
    asyncio.run(main_async())
