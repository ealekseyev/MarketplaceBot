from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class TelegramError(Exception):
    """Raised when the Telegram Bot API returns ok=false."""


@dataclass
class SentMessage:
    message_id: int
    chat_id: int


@dataclass
class TelegramUpdate:
    update_id: int
    message_id: int | None
    chat_id: int | None
    text: str | None
    reply_to_message_id: int | None


def _sync_request(
    url: str,
    payload: dict[str, Any] | None,
    *,
    timeout: float,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception as err:
            raise TelegramError(f"HTTP {exc.code}: {exc.reason}") from err
        if not body.get("ok"):
            raise TelegramError(body.get("description", f"HTTP {exc.code}: {exc.reason}"))
        return body

    if not body.get("ok"):
        raise TelegramError(body.get("description", "Unknown Telegram API error"))
    return body


def _parse_update(raw: dict[str, Any]) -> TelegramUpdate:
    message = raw.get("message") or raw.get("edited_message")
    if message is None:
        return TelegramUpdate(
            update_id=raw["update_id"],
            message_id=None,
            chat_id=None,
            text=None,
            reply_to_message_id=None,
        )

    reply_to = message.get("reply_to_message")
    return TelegramUpdate(
        update_id=raw["update_id"],
        message_id=message.get("message_id"),
        chat_id=message.get("chat", {}).get("id"),
        text=message.get("text"),
        reply_to_message_id=reply_to.get("message_id") if reply_to else None,
    )


class TelegramClient:
    """Minimal async client for Telegram Bot API send/receive."""

    def __init__(self, bot_token: str, chat_id: str | int) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._base_url = f"https://api.telegram.org/bot{bot_token}/"

    async def send_message(self, text: str, *, reply_markup: dict | None = None) -> SentMessage:
        payload: dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": text,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        result = await self._api_call("sendMessage", payload)
        message = result["result"]
        return SentMessage(message_id=message["message_id"], chat_id=message["chat"]["id"])

    async def get_updates(self, *, offset: int | None = None, timeout: int = 0) -> list[TelegramUpdate]:
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset

        request_timeout = float(max(timeout + 5, 30))
        result = await self._api_call("getUpdates", payload, timeout=request_timeout)
        return [_parse_update(raw) for raw in result.get("result", [])]

    async def close(self) -> None:
        return None

    async def _api_call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 30,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{method}"
        return await asyncio.to_thread(_sync_request, url, payload, timeout=timeout)


class TelegramNotifier(TelegramClient):
    """Backward-compatible alias for outbound Telegram alerts."""
