"""Bot orchestrator — wires fb_marketplace, fb_store, fb_agent, and fb_telegram."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from fb_agent import (
    AgentConfig,
    HandoffSummarizer,
    MarketplaceResponder,
    SellerInputResponder,
)
from fb_store import ChatPolicy, Database, ListingCache
from fb_telegram import TelegramClient, telegram_credentials_from_env
from orchestrator import BotOrchestrator

logger = logging.getLogger(__name__)

_NOISY_LOGGERS = ("httpx", "httpcore", "urllib3", "playwright", "asyncio")


def _configure_logging(*, verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    orchestrator_logger = logging.getLogger("orchestrator")
    marketplace_logger = logging.getLogger("fb_marketplace")
    if verbose:
        orchestrator_logger.setLevel(logging.DEBUG)
        marketplace_logger.setLevel(logging.DEBUG)
    else:
        orchestrator_logger.setLevel(logging.INFO)
        marketplace_logger.setLevel(logging.INFO)


async def async_main(args: argparse.Namespace) -> None:
    _configure_logging(verbose=args.verbose)

    if args.mock_fb:
        from fb_marketplace_mock import MarketplaceSession, SessionConfig, facebook_credentials_from_env
    else:
        from fb_marketplace import MarketplaceSession, SessionConfig, facebook_credentials_from_env

    if args.reply_delay_seconds is not None:
        reply_delay = args.reply_delay_seconds
    else:
        reply_delay = 0.0

    logger.info(
        "Startup config: poll_interval=%.1fs, reply_delay=%.1fs, only_chat_id=%s, "
        "telegram=%s, once=%s, headless=%s, mock_fb=%s",
        args.poll_interval,
        reply_delay,
        args.only_chat_id or "(all)",
        "on" if args.telegram else "off",
        args.once,
        not args.headful,
        args.mock_fb,
    )

    if args.mock_fb:
        logger.info(
            "Mock Facebook mode: marketplace DB /tmp/fb-bot-mock-marketplace.sqlite, "
            "store DB /tmp/fb-bot-mock-store.sqlite"
        )
        email, password = None, None
        config = SessionConfig(
            user_data_dir=args.user_data_dir or "/tmp/fb-bot-mock-profile",
            headless=True,
        )
        db = Database("/tmp/fb-bot-mock-store.sqlite")
    else:
        email, password = facebook_credentials_from_env(args.env_file)
        config = SessionConfig(
            user_data_dir=args.user_data_dir,
            facebook_email=email,
            facebook_password=password,
            headless=not args.headful,
        )
        db = Database()
    chat_policy = ChatPolicy(db)
    listing_cache = ListingCache(db)
    telegram: TelegramClient | None = None
    if args.telegram:
        bot_token, chat_id = telegram_credentials_from_env(args.env_file)
        if not bot_token or not chat_id:
            raise SystemExit(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required with --telegram "
                "(see src/fb_telegram/TELEGRAM_SETUP.md)"
            )
        telegram = TelegramClient(bot_token, chat_id)

    agent_config = AgentConfig.from_env(env_file=args.env_file)
    orchestrator = BotOrchestrator(
        chat_policy=chat_policy,
        agent_config=agent_config,
        responder=MarketplaceResponder(agent_config),
        seller_input=SellerInputResponder(agent_config),
        summarizer=HandoffSummarizer(agent_config),
        telegram=telegram,
        reply_delay_seconds=reply_delay,
        only_chat_id=args.only_chat_id,
    )

    try:
        async with MarketplaceSession(config, listing_cache=listing_cache) as session:
            if args.once:
                logger.info("Running single poll iteration")
                await orchestrator.run_once(session)
                logger.info("Single poll iteration complete")
                return
            logger.info("Starting poll loop (interval=%.1fs)", args.poll_interval)
            await orchestrator.run_forever(session, args.poll_interval)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Facebook Marketplace bot orchestrator")
    parser.add_argument("--env-file", default=".env", help="Path to .env with FB credentials")
    parser.add_argument(
        "--mock-fb",
        action="store_true",
        help="Use mock Facebook Marketplace (no browser or FB credentials)",
    )
    parser.add_argument("--user-data-dir", help="Persistent Chromium profile directory")
    parser.add_argument("--headful", action="store_true", help="Run browser with UI")
    parser.add_argument("--poll-interval", type=float, default=60.0, help="Seconds between inbox polls")
    parser.add_argument(
        "--only-chat-id",
        metavar="CHAT_ID",
        help="Only process this Marketplace chat ID (skip all others)",
    )
    parser.add_argument(
        "--reply-delay-seconds",
        type=float,
        default=None,
        help="Min age of latest buyer message before reply (default 0)",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Enable Telegram client (requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in env/.env)",
    )
    parser.add_argument("--once", action="store_true", help="Run one iteration and exit")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    if not args.mock_fb and not args.user_data_dir:
        parser.error("--user-data-dir is required unless --mock-fb is set")

    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
