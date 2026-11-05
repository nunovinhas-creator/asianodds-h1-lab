"""Offline regression tests for the non-interactive Telegram reader."""
import os
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from telethon import errors
from telethon.tl.functions.updates import GetStateRequest

from h1lab import cli
from h1lab.core import empty_state
from h1lab.session import TelegramSessionError


class TelegramReaderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        client = AsyncMock()
        client.get_entity.return_value = SimpleNamespace(id=123)
        client.get_messages.return_value = []
        self.client = client
        factory = MagicMock(return_value=client)
        for patcher in (
            patch.dict(os.environ, {"TG_API_ID": "1", "TG_API_HASH": "synthetic",
                                    "TG_CHANNEL": "@example", "TG_SESSION": "1synthetic"}),
            patch("h1lab.session.load_telegram_session", return_value=object()),
            patch("telethon.TelegramClient", factory),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.save = patch("h1lab.cli.save").start()
        self.addCleanup(patch.stopall)

    async def test_revoked_and_unauthorized_are_distinct_and_never_prompt(self):
        state = empty_state()
        previous = deepcopy(state)
        for error, reason in (
            (errors.SessionRevokedError(None), "TELEGRAM_SESSION_REJECTED"),
            (errors.UnauthorizedError(None, "synthetic"), "TELEGRAM_SESSION_UNAUTHORIZED"),
        ):
            with self.subTest(reason=reason):
                self.client.side_effect = error
                with self.assertRaisesRegex(TelegramSessionError, reason):
                    await cli.poll(state)
                self.assertIsInstance(self.client.call_args.args[0], GetStateRequest)
                self.assertEqual(state, previous)
        self.client.get_entity.assert_not_called()
        self.client.start.assert_not_called()
        self.client.disconnect.assert_awaited()
        self.save.assert_not_called()

    async def test_transport_failure_then_successful_probe_and_empty_poll(self):
        self.client.connect.side_effect = OSError("sensitive transport details")
        state = empty_state()
        with self.assertRaisesRegex(TelegramSessionError, "^TELEGRAM_TEMPORARY_FAILURE CONNECT$"):
            await cli.poll(state)
        self.save.assert_not_called()
        self.client.connect.side_effect = None
        await cli.probe_telegram()
        self.save.assert_not_called()
        await cli.poll(state)
        self.assertEqual(state["last_id"], 0)
        self.assertEqual(state["collector"]["last_batch_new_messages"], 0)
        self.save.assert_called_once()
        self.client.start.assert_not_called()

    async def test_authorized_session_without_channel_access_leaves_checkpoint_intact(self):
        state = empty_state()
        previous = deepcopy(state)
        self.client.get_messages.side_effect = errors.ChannelPrivateError(None)
        with self.assertRaisesRegex(TelegramSessionError, "^TELEGRAM_CHANNEL_UNAVAILABLE CHANNEL_READ$"):
            await cli.poll(state)
        self.assertEqual(state, previous)
        self.save.assert_not_called()
