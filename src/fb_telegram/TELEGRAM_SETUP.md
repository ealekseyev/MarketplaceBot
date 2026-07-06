# Telegram setup

1. Open Telegram and message [@BotFather](https://t.me/BotFather). Run `/newbot`, follow the prompts, and copy the bot token.
2. Start a chat with your new bot and send `/start` so it can message you.
3. Get your chat id: message [@userinfobot](https://t.me/userinfobot) or run `python scripts/test_telegram.py poll` after step 2 and read the `chat_id` field.
4. Add to `.env` (or export in your shell):

   ```
   TELEGRAM_BOT_TOKEN=123456:ABC...
   TELEGRAM_CHAT_ID=your_numeric_chat_id
   ```
