"""BotBlockedError means "no HTTP request was made": never an uncertain delivery (all six notifiers)."""
import os
import shutil
import tempfile
import unittest
from datetime import timedelta

from h1lab.bot import BotBlockedError, BotDeliveryError, BotRejectedError


def setUpModule():
    global _TMP
    _TMP = tempfile.mkdtemp()
    os.environ["TG_DELIVERY_BLOCK_FILE"] = os.path.join(_TMP, "block.json")


def tearDownModule():
    os.environ.pop("TG_DELIVERY_BLOCK_FILE", None)
    shutil.rmtree(_TMP, ignore_errors=True)


def blocked(_):
    raise BotBlockedError("TELEGRAM_SEND_BLOCKED: HTTP 429 (no request made)")


class LegacyNotifierBlockedTests(unittest.TestCase):
    def test_e4(self):
        from h1lab.e4_notify import empty_ledger, process
        from tests.test_e4_notify import NOW, game
        ledger, stats = process([game()], empty_ledger(NOW), NOW, blocked, True)
        self.assertEqual((ledger["entries"], stats.get("blocked_before_http"), stats.get("failed", 0)), ({}, 1, 0))
        calls = []                                  # next run, pause over: it is sent normally
        ledger, stats = process([game()], ledger, NOW + timedelta(minutes=5), lambda m: calls.append(m) or 7, True)
        self.assertEqual((len(calls), stats["games_sent"]), (1, 1))

    def test_e4_other_failures_keep_their_legacy_behaviour(self):
        from h1lab.e4_notify import empty_ledger, process
        from tests.test_e4_notify import NOW, game
        for exc in (BotDeliveryError("uncertain"), BotRejectedError("rejected", 429, 10)):
            def send(_, exc=exc): raise exc
            ledger, stats = process([game()], empty_ledger(NOW), NOW, send, True)
            self.assertEqual(stats["failed"], 1)
            self.assertEqual(next(iter(ledger["entries"].values()))["status"], "delivery_uncertain_manual_review")

    def test_pattern(self):
        from h1lab.pattern_notify import new_ledger, process
        from tests.test_pattern_notify import NOW, row
        r = row()
        ledger, stats = process([r], new_ledger([], [], NOW), NOW + timedelta(minutes=4), blocked, True)
        self.assertNotIn(r["match_key"], ledger["entries"])
        self.assertEqual((stats.get("blocked_before_http"), stats.get("failed", 0)), (1, 0))
        calls = []
        ledger, stats = process([r], ledger, NOW + timedelta(minutes=9), lambda m: calls.append(m) or 9, True)
        self.assertEqual((len(calls), ledger["entries"][r["match_key"]]["status"]), (1, "sent"))

    def test_t05_future_and_historical(self):
        from h1lab import t05_notify as t05
        from tests.test_t05_notify import NOW, game
        data, stats = t05.process([game()], t05.empty_ledger(NOW), NOW, blocked, True)
        self.assertEqual(stats.get("uncertain", 0), 0)
        self.assertNotIn("T05|g1", data["entries"])
        self.assertNotIn("historical:2026-10-28-29", data["entries"])
        self.assertGreaterEqual(stats.get("blocked_before_http", 0), 1)
        calls = []
        data, stats = t05.process([game()], data, NOW + timedelta(minutes=5), lambda m: calls.append(m) or 30, True)
        self.assertGreaterEqual(len(calls), 1)

    def test_strategy(self):
        from h1lab.strategy_notify import empty_ledger, process
        from tests.test_strategy_notify import NOW, candidates, original, research, v4
        a = original()
        rows = candidates([a], [v4(a)])
        ledger, stats = process(rows, empty_ledger(NOW), NOW, blocked, True, research=research())
        self.assertEqual(ledger["entries"], {})
        self.assertEqual((stats.get("blocked_before_http"), stats.get("failed", 0)), (1, 0))

    def test_active_notifiers_do_not_mark_uncertain_either(self):
        from tests.test_three_moves_notify import candidates as three_rows, NOW
        from h1lab import three_moves_notify as three
        from h1lab.telegram_block import BlockStore
        BlockStore().clear()
        ledger, stats = three.process(three_rows(), three.empty_ledger(NOW), NOW, blocked, True)
        self.assertEqual(ledger["entries"], {})
        self.assertEqual((stats.get("blocked_before_http"), stats.get("uncertain", 0)), (1, 0))


if __name__ == "__main__":
    unittest.main()
