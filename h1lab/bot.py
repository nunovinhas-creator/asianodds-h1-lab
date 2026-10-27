"""Private Telegram Bot API delivery. Tokens are never logged or persisted."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class BotDeliveryError(RuntimeError):
    """An error safe for public CI logs."""


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
        raise BotDeliveryError(
            "TELEGRAM_DELIVERY_FAILED: HTTP " + str(exc.code) +
            ". Check bot token, chat ID, and that the recipient started the bot."
        ) from None
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
