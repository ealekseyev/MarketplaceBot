#!/usr/bin/env python3
"""Create a fresh Chromium profile and log into Facebook for a different account."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fb_marketplace import FacebookMarketplaceClient, SessionConfig, facebook_credentials_from_env

DEFAULT_PROFILES_ROOT = Path(".browser-profiles")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a new persistent browser profile and complete Facebook login manually.",
    )
    parser.add_argument(
        "--name",
        help="Profile name under .browser-profiles/ (e.g. 'seller2' -> .browser-profiles/seller2)",
    )
    parser.add_argument(
        "--profile-dir",
        help="Full path for the Chromium user-data-dir (overrides --name)",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Optional .env for auto-fill login (default: manual login only, no credentials)",
    )
    parser.add_argument(
        "--use-env-credentials",
        action="store_true",
        help="Use FACEBOOK_EMAIL/FACEBOOK_PASSWORD from --env-file for auto login",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30_000,
        help="Playwright default timeout in milliseconds",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Use an existing profile directory without prompting",
    )
    return parser.parse_args()


def resolve_profile_dir(args: argparse.Namespace) -> Path:
    if args.profile_dir:
        return Path(args.profile_dir)
    if not args.name:
        raise SystemExit("Provide --name <account-label> or --profile-dir <path>.")
    return DEFAULT_PROFILES_ROOT / args.name


def confirm_existing_profile(profile_dir: Path, *, force: bool) -> None:
    if not profile_dir.exists():
        return
    has_session = any(profile_dir.iterdir()) if profile_dir.is_dir() else False
    if not has_session:
        return
    if force:
        print(f"Reusing existing profile directory: {profile_dir}")
        return
    print(f"Profile directory already exists: {profile_dir}")
    print("A new login will update the saved session in that directory.")
    answer = input("Continue? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        raise SystemExit("Aborted.")


async def main_async() -> None:
    args = parse_args()
    profile_dir = resolve_profile_dir(args)
    profile_dir.mkdir(parents=True, exist_ok=True)
    confirm_existing_profile(profile_dir, force=args.force)

    email = password = None
    if args.use_env_credentials:
        email, password = facebook_credentials_from_env(args.env_file)

    config = SessionConfig(
        user_data_dir=str(profile_dir.resolve()),
        headless=False,
        timeout_ms=args.timeout_ms,
        facebook_email=email,
        facebook_password=password,
        manual_login=True,
        pause_on_auth_failure=True,
    )

    print(f"Creating browser profile at: {profile_dir.resolve()}")
    print("A Chromium window will open. Log into the Facebook account you want this bot to use.")
    print("Complete any CAPTCHA or checkpoint prompts in the browser.")
    print()

    async with FacebookMarketplaceClient(config) as client:
        page = client._require_page()
        await client._safe_goto(page, config.facebook_login_url, wait_until="commit")

        if config.facebook_email and config.facebook_password:
            print("Attempting credential login from env...")
            await client._authenticate(page)
        else:
            print("Log into Facebook in the browser window...")
            await client._wait_for_manual_login(page)

        print("Login detected. Verifying Marketplace inbox access...")
        chats = await client.list_chats(limit=5)
        print()
        print(f"Login verified — Marketplace inbox returned {len(chats)} chat(s).")
        if chats:
            for chat in chats[:5]:
                buyer = chat.buyer_name or "(unknown)"
                preview = (chat.latest_message_preview or "")[:60]
                print(f"  - {buyer}: {preview}")
        print()
        input("Press Enter to close the browser and save this profile...")

    print()
    print("Profile saved.")
    print("Use it with:")
    print(f"  fb-marketplace inbox --user-data-dir {profile_dir}")
    print(f"  PYTHONPATH=src python -m main --user-data-dir {profile_dir} --telegram --headful")


if __name__ == "__main__":
    asyncio.run(main_async())
