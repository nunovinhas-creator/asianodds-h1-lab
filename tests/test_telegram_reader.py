"""Offline regression tests for the non-interactive Telegram reader."""
import asyncio
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
        self.factory = factory
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


    async def test_stalled_setup_names_the_stage_and_keeps_checkpoint(self):
        async def stalled(*args, **kwargs):
            await asyncio.Future()

        for stage, call in (("CONNECT", self.client.connect),
                            ("AUTHORIZE", self.client),
                            ("CHANNEL_LOOKUP", self.client.get_entity)):
            with self.subTest(stage=stage):
                state = empty_state()
                previous = deepcopy(state)
                call.side_effect = stalled
                try:
                    with patch("h1lab.session.SETUP_TIMEOUT_SECONDS", 0.02):
                        with self.assertRaisesRegex(TelegramSessionError, f"^TELEGRAM_TIMEOUT {stage}$"):
                            await cli.poll(state)
                finally:
                    call.side_effect = None
                self.assertEqual(state, previous)
        self.save.assert_not_called()

    async def test_rejected_auth_key_is_not_retried_and_never_echoed(self):
        self.client.side_effect = errors.AuthKeyUnregisteredError(None)
        with self.assertRaisesRegex(TelegramSessionError,
                                    "^TELEGRAM_SESSION_REJECTED AuthKeyUnregisteredError$"):
            await cli.probe_telegram()
        self.assertEqual(self.client.await_count, 1)
        self.client.get_messages.assert_not_called()
        self.client.start.assert_not_called()
        self.save.assert_not_called()
        self.assertEqual(self.factory.call_args.kwargs["request_retries"], 1)
        self.assertFalse(self.factory.call_args.kwargs["auto_reconnect"])

    async def test_stalled_read_and_disconnect_preserve_cursor_and_primary_error(self):
        async def stalled(*args, **kwargs):
            await asyncio.Future()

        state = empty_state()
        previous = deepcopy(state)
        self.client.get_messages.side_effect = stalled
        self.client.disconnect.side_effect = stalled
        with patch("h1lab.session.READ_TIMEOUT_SECONDS", 0.02), \
             patch("h1lab.session.DISCONNECT_TIMEOUT_SECONDS", 0.02):
            with self.assertRaisesRegex(TelegramSessionError, "^TELEGRAM_TIMEOUT CHANNEL_READ$"):
                await cli.poll(state)
        self.assertEqual(state, previous)
        self.save.assert_not_called()

    async def test_disconnect_failure_after_read_cannot_advance_bootstrap_cursor(self):
        self.client.get_messages.return_value = [SimpleNamespace(id=42)]
        self.client.disconnect.side_effect = OSError("sensitive cleanup detail")
        state = empty_state()
        previous = deepcopy(state)
        with self.assertRaisesRegex(TelegramSessionError, "^TELEGRAM_DISCONNECT_FAILED$"):
            await cli.poll(state)
        self.assertEqual(state, previous)
        self.save.assert_not_called()

    async def test_rejected_session_survives_secondary_disconnect_exception(self):
        self.client.side_effect = errors.AuthKeyUnregisteredError(None)
        self.client.disconnect.side_effect = errors.RPCError(None, "sensitive detail")
        with self.assertRaisesRegex(TelegramSessionError,
                                    "^TELEGRAM_SESSION_REJECTED AuthKeyUnregisteredError$"):
            await cli.probe_telegram()

    async def test_partial_incremental_read_cannot_persist_or_advance_cursor(self):
        from datetime import datetime, timezone
        async def partial(*args, **kwargs):
            yield SimpleNamespace(id=43, raw_text="synthetic unparsed", entities=[],
                                  date=datetime(2026, 11, 5, tzinfo=timezone.utc), edit_date=None)
            raise OSError("sensitive transport detail")

        self.client.iter_messages = partial
        state = empty_state()
        state["last_id"] = 42
        previous = deepcopy(state)
        with patch("h1lab.cli.persist_shadow") as shadow, \
             patch("h1lab.cli.persist_market_v4") as market:
            with self.assertRaisesRegex(TelegramSessionError,
                                        "^TELEGRAM_TEMPORARY_FAILURE CHANNEL_READ$"):
                await cli.poll(state)
            shadow.assert_not_called()
            market.assert_not_called()
        self.assertEqual(state, previous)
        self.save.assert_not_called()

    async def test_two_empty_incremental_cycles_succeed_without_new_messages(self):
        from datetime import datetime, timezone
        async def empty(*args, **kwargs):
            if False:
                yield
        self.client.iter_messages = empty
        state = empty_state()
        state["last_id"] = 42
        state["collector"] = {"last_poll_at": datetime.now(timezone.utc).isoformat()}
        with patch("h1lab.cli.persist_shadow"), patch("h1lab.cli.persist_market_v4"):
            for _ in range(2):
                await cli.poll(state)
                self.assertEqual(state["last_id"], 42)
        self.save.assert_not_called()
        self.assertEqual(self.client.connect.await_count, 2)
        self.assertEqual(self.client.disconnect.await_count, 2)
