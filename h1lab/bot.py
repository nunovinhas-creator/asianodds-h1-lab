"""Private Telegram Bot API delivery. Tokens are never logged or persisted."""
import json
import os
import sys
from urllib.error import HTTPError, URLError
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

from .telegram_block import BlockStore


class BotDeliveryError(RuntimeError):
    """An error safe for public CI logs.

    The base class means DELIVERY_UNCERTAIN: nobody can prove the message was or
    was not accepted, so callers must never resend automatically.
    """
    outcome = "DELIVERY_UNCERTAIN"


class BotBlockedError(BotDeliveryError):
    """Not sent: a shared 429/401/403 block is active. No HTTP request was made."""
    outcome = "NOT_SENT_BLOCKED"


class BotRejectedError(BotDeliveryError):
    """Telegram answered with an explicit 4xx: the request was NOT accepted."""
    outcome = "DEFINITELY_REJECTED"

    def __init__(self, message, http_status, retry_after=None):
        super().__init__(message)
        self.http_status = http_status
        self.retry_after = retry_after


def _record_block(store, status, retry_after):
    """Shared pause for every notifier: retry_after (429) or a 24h probe interval (401/403)."""
    if status not in (429, 401, 403):
        return
    now = datetime.now(timezone.utc)
    if status == 429:
        wait = timedelta(seconds=retry_after if retry_after is not None else 300)
        diagnosis = "FLOOD_WAIT_RETRY_AFTER" if retry_after is not None else "FLOOD_WAIT_CONSERVATIVE_5MIN"
    else:
        wait = timedelta(hours=24)
        diagnosis = "AUTH_REJECTED_CHECK_TG_BOT_TOKEN_AND_TG_CHAT_ID"
    try:
        store.record(now + wait, status, now, diagnosis)
    except OSError as exc:
        # Never silent: the rejection is still raised, but the shared pause could not be stored.
        print("TELEGRAM_BLOCK_NOT_RECORDED", type(exc).__name__, file=sys.stderr)


def _retry_after(exc):
    """Seconds from Telegram's JSON error body (parameters.retry_after), else None."""
    try:
        body = json.loads(exc.read(65536))
        value = body["parameters"]["retry_after"]
        return int(value) if type(value) is int and 0 <= value <= 86400 else None
    except Exception:  # unreadable body: stay conservative, caller applies a default
        return None


def configured():
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TG_CHAT_ID", "").strip()
    return bool(token and chat_id)


def send_message(message):
    store = BlockStore()
    blocked = store.active(datetime.now(timezone.utc))
    if blocked is not None:
        raise BotBlockedError("TELEGRAM_SEND_BLOCKED: HTTP %s until %s (no request made)"
                              % (blocked["http_status"], blocked["until"]))
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TG_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise BotDeliveryError("NOTIFY_SETUP_REQUIRED: TG_BOT_TOKEN and TG_CHAT_ID")
    # A numeric chat ID for the intended user/private group; no inferred target.
    if not chat_id.lstrip("-").isdigit():
        raise BotDeliveryError("NOTIFY_SETUP_REQUIRED: TG_CHAT_ID must be a numeric Telegram chat ID")
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    body = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }).encode("utf-8")
    request = Request(url, data=body, method="POST",
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            if response.status != 200:
                raise BotDeliveryError("TELEGRAM_DELIVERY_FAILED: bad HTTP response")
            result = json.loads(response.read(65536))
    except HTTPError as exc:
        # The exception repr and URL contain the bot secret. Never expose either.
        if 400 <= exc.code < 500:
            retry_after = _retry_after(exc) if exc.code == 429 else None
            _record_block(store, exc.code, retry_after)
            raise BotRejectedError(
                "TELEGRAM_DELIVERY_REJECTED: HTTP " + str(exc.code) +
                ". Check bot token, chat ID, and that the recipient started the bot.",
                exc.code, retry_after) from None
        raise BotDeliveryError(
            "TELEGRAM_DELIVERY_UNCERTAIN: HTTP " + str(exc.code) +
            ". A server error does not prove the message was not accepted.") from None
    except (URLError, TimeoutError, ValueError):
        raise BotDeliveryError(
            "TELEGRAM_DELIVERY_UNCERTAIN: network or malformed reply. "
            "Review the destination chat before rerunning."
        ) from None
    if not result.get("ok") or not isinstance(result.get("result"), dict):
        raise BotDeliveryError("TELEGRAM_DELIVERY_FAILED: unexpected API response")
    obj = result["result"]
    if str(obj.get("chat", {}).get("id")) != chat_id or not isinstance(obj.get("message_id"), int):
        raise BotDeliveryError("TELEGRAM_DELIVERY_UNCERTAIN: destination or message ID missing")
    return obj["message_id"]
