"""Private Telegram Bot API delivery. Tokens are never logged or persisted."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class BotDeliveryError(RuntimeError):
    """An error safe for public CI logs.

    The base class means DELIVERY_UNCERTAIN: nobody can prove the message was or
    was not accepted, so callers must never resend automatically.
    """
    outcome = "DELIVERY_UNCERTAIN"


class BotRejectedError(BotDeliveryError):
    """Telegram answered with an explicit 4xx: the request was NOT accepted."""
    outcome = "DEFINITELY_REJECTED"

    def __init__(self, message, http_status, retry_after=None):
        super().__init__(message)
        self.http_status = http_status
        self.retry_after = retry_after


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
            raise BotRejectedError(
                "TELEGRAM_DELIVERY_REJECTED: HTTP " + str(exc.code) +
                ". Check bot token, chat ID, and that the recipient started the bot.",
                exc.code, _retry_after(exc) if exc.code == 429 else None) from None
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
