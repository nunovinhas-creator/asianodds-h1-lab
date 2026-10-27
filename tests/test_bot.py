import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from h1lab.bot import BotDeliveryError, configured, send_message
from h1lab.notify import message_for_ticket, run


class BotTest(unittest.TestCase):
    def test_requires_secret_pair(self):
        with patch.dict(os.environ, {"TG_BOT_TOKEN": "x", "TG_CHAT_ID": ""}):
            self.assertFalse(configured())

    def test_rejects_non_numeric_target_without_network(self):
        with patch.dict(os.environ, {"TG_BOT_TOKEN": "123:secret", "TG_CHAT_ID": "@unknown"}):
            with self.assertRaises(BotDeliveryError):
                send_message("test")

    def test_telegram_reply_confirmed_destination(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self, *args):
                return json.dumps({
                    "ok": True, "result": {"message_id": 42, "chat": {"id": 98765}}
                }).encode()

        with patch.dict(os.environ, {"TG_BOT_TOKEN": "123:secret", "TG_CHAT_ID": "98765"}), \
             patch("h1lab.bot.urlopen", return_value=Response()) as api:
            self.assertEqual(send_message("testing"), 42)
            request = api.call_args.args[0]
            self.assertEqual(json.loads(request.data)["chat_id"], "98765")

    def test_no_fallback_to_saved_messages(self):
        state = {"tickets": [{"ticket_id": "test", "signal_ids": ["1"]}],
                 "signals": [{"signal_id": "1"}]}
        with patch("h1lab.notify.read_state", return_value=state), \
             patch.dict(os.environ, {"TG_BOT_TOKEN": "", "TG_CHAT_ID": ""}), \
             patch("h1lab.notify.send_message") as sender:
            run()
            sender.assert_not_called()
            self.assertNotIn("bot_notified_at", state["tickets"][0])

    def test_legacy_saved_message_receipt_does_not_suppress_bot(self):
        kickoff = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        ticket = {"ticket_id": "T-123", "signal_ids": ["signal1"], "notified_at": "legacy",
                  "theoretical_odds": 2.0}
        signal = {"signal_id": "signal1", "home": "A", "away": "B", "line": 2.5,
                  "under_odds": 2.0, "kickoff_utc": kickoff}
        state = {"tickets": [ticket], "signals": [signal]}
        with patch("h1lab.notify.read_state", return_value=state), \
             patch.dict(os.environ, {"TG_BOT_TOKEN": "123:secret", "TG_CHAT_ID": "98765"}), \
             patch("h1lab.notify.send_message", return_value=42), \
             patch("h1lab.notify.save") as save_state:
            run()
            self.assertEqual(ticket["bot_message_id"], 42)
            self.assertEqual(ticket["bot_notification_status"], "sent")
            save_state.assert_called_once()


if __name__ == "__main__":
    unittest.main()
