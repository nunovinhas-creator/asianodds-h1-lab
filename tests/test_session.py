"""Offline validation: do not store or print real Telegram credentials."""
import os
import sys
import types
import unittest
from unittest.mock import patch

from h1lab.session import TelegramSessionError, load_telegram_session


class StubSession:
    def __init__(self, value):
        if value != "1exampletoken":
            raise ValueError("Not a valid string")
        self.value = value


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.sessions = types.ModuleType("telethon.sessions")
        self.sessions.StringSession = StubSession
        self.telethon = types.ModuleType("telethon")
        self.telethon.sessions = self.sessions

    def call(self, raw):
        with patch.dict(sys.modules, {"telethon": self.telethon, "telethon.sessions": self.sessions}):
            with patch.dict(os.environ, {"TG_SESSION": raw}):
                return load_telegram_session()

    def test_multiline_copy(self):
        self.assertEqual(self.call("  1example\n token  ").value, "1exampletoken")

    def test_wrapped_in_quotes(self):
        self.assertEqual(self.call('"1exampletoken"').value, "1exampletoken")

    def test_wrong_value_is_rejected(self):
        with self.assertRaises(TelegramSessionError) as context:
            self.call("not-a-session")
        self.assertNotIn("not-a-session", str(context.exception))

    def test_broken_value_is_rejected_without_echo(self):
        with self.assertRaises(TelegramSessionError) as context:
            self.call("1invalid")
        self.assertNotIn("1invalid", str(context.exception))


if __name__ == "__main__":
    unittest.main()
