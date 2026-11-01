"""Telegram delivery state machine: confirmed / rejected / uncertain / expired. Offline only."""
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from h1lab import bot, telegram_delivery as td
from h1lab import three_moves_notify as three
from h1lab import two_up_notify as two
from h1lab.bot import BotDeliveryError, BotRejectedError
from tests.test_three_moves_notify import candidates as three_rows, NOW as T0, KO

NOW = T0


def rejected(code, retry_after=None):
    def send(_):
        raise BotRejectedError("TELEGRAM_DELIVERY_REJECTED: HTTP %d" % code, code, retry_after)
    return send


class Clock:
    def __init__(self, start): self.now = start
    def __call__(self): return self.now
    def advance(self, **kw): self.now += timedelta(**kw)


def run_once(rows, ledger, sender, clock, persist=None):
    return three.process(rows, ledger, clock.now, sender, True, clock=clock, persist=persist)


class HttpClassificationTests(unittest.TestCase):
    """bot.send_message against a faked urlopen: the real classification, no network."""

    def call(self, exc_or_body):
        env = {"TG_BOT_TOKEN": "123:SECRET", "TG_CHAT_ID": "42"}
        def fake(request, timeout=0):
            if isinstance(exc_or_body, Exception):
                raise exc_or_body
            return exc_or_body
        with patch.dict(os.environ, env), patch.object(bot, "urlopen", fake):
            return bot.send_message("x")

    def http_error(self, code, body=None):
        return HTTPError("https://api.telegram.org/botSECRET/sendMessage", code, "x", {},
                         io.BytesIO(json.dumps(body or {}).encode()))

    def test_429_carries_retry_after_and_never_leaks_the_token(self):
        with self.assertRaises(BotRejectedError) as ctx:
            self.call(self.http_error(429, {"ok": False, "parameters": {"retry_after": 17}}))
        self.assertEqual((ctx.exception.http_status, ctx.exception.retry_after), (429, 17))
        self.assertNotIn("SECRET", str(ctx.exception))
        self.assertEqual(ctx.exception.outcome, "DEFINITELY_REJECTED")

    def test_other_4xx_rejected_but_5xx_and_network_are_uncertain(self):
        for code in (400, 401, 403, 404):
            with self.assertRaises(BotRejectedError):
                self.call(self.http_error(code))
        for exc in (self.http_error(500), self.http_error(502), URLError("down"), TimeoutError()):
            with self.assertRaises(BotDeliveryError) as ctx:
                self.call(exc)
            self.assertNotIsInstance(ctx.exception, BotRejectedError)
            self.assertEqual(ctx.exception.outcome, "DELIVERY_UNCERTAIN")

    def test_hostile_retry_after_is_ignored(self):
        for bad in ("5", -1, 10 ** 9, None, True):
            with self.assertRaises(BotRejectedError) as ctx:
                self.call(self.http_error(429, {"parameters": {"retry_after": bad}}))
            self.assertIsNone(ctx.exception.retry_after)


class StateMachineTests(unittest.TestCase):
    def setUp(self):
        self.rows = three_rows()
        self.clock = Clock(NOW)
        self.ledger = three.empty_ledger(NOW)

    def entry(self):
        return self.ledger["entries"]["fixture-1"]

    def test_429_is_rejected_waits_retry_after_then_is_sent_once(self):
        self.ledger, stats = run_once(self.rows, self.ledger, rejected(429, 120), self.clock)
        self.assertEqual((self.entry()["status"], stats["rejected"]), ("delivery_rejected", 1))
        self.assertEqual(self.entry()["retry_not_before"], (NOW + timedelta(seconds=120)).isoformat(timespec="seconds"))
        calls = []
        ok = lambda m: calls.append(m) or 77
        self.clock.advance(seconds=60)   # inside retry_after: global block, nothing sent
        self.ledger, stats = run_once(self.rows, self.ledger, ok, self.clock)
        self.assertEqual((calls, stats.get("rejected_waiting")), ([], 1))
        self.clock.advance(seconds=61)
        self.ledger, stats = run_once(self.rows, self.ledger, ok, self.clock)
        self.assertEqual((len(calls), self.entry()["status"], self.entry()["telegram_message_id"]), (1, "sent", 77))
        self.assertNotIn("delivery_block", self.ledger)
        self.clock.advance(hours=1)      # SENT_CONFIRMED is never resent
        run_once(self.rows, self.ledger, ok, self.clock)
        self.assertEqual(len(calls), 1)

    def test_429_stops_the_whole_batch_but_does_not_poison_other_games(self):
        other = three_rows()[0]
        other = {**other, "match_key": "fixture-2", "match_label": "B vs C"}
        calls = []
        def send(m): calls.append(m); raise BotRejectedError("x", 429, 30)
        self.ledger, stats = three.process([self.rows[0], other], self.ledger, NOW, send, True, clock=self.clock)
        self.assertEqual(len(calls), 1)          # stopped after the first 429
        self.assertNotIn("fixture-2", self.ledger["entries"])
        self.assertEqual(self.ledger["delivery_block"]["http_status"], 429)

    def test_401_suspends_for_hours_then_probes_once_and_exhausts(self):
        calls = []
        def send(m): calls.append(m); raise BotRejectedError("x", 401)
        for _ in range(td.MAX_REJECTED_ATTEMPTS):
            self.ledger, _ = three.process(self.rows, self.ledger, self.clock.now, send, True, clock=self.clock)
            self.clock.advance(minutes=30)       # inside the 6h block: no new call
            three.process(self.rows, self.ledger, self.clock.now, send, True, clock=self.clock)
            self.clock.advance(hours=6)
        self.assertEqual(len(calls), td.MAX_REJECTED_ATTEMPTS)
        self.assertEqual(self.entry()["status"], "delivery_rejected_final")
        self.assertEqual(self.entry()["reason"], "attempts_exhausted")
        three.process(self.rows, self.ledger, self.clock.now, send, True, clock=self.clock)
        self.assertEqual(len(calls), td.MAX_REJECTED_ATTEMPTS)

    def test_non_retryable_4xx_is_final_without_blocking_the_channel(self):
        self.ledger, stats = run_once(self.rows, self.ledger, rejected(400), self.clock)
        self.assertEqual(self.entry()["status"], "delivery_rejected_final")
        self.assertNotIn("delivery_block", self.ledger)

    def test_uncertain_is_never_resent(self):
        calls = []
        def send(m): calls.append(m); raise BotDeliveryError("TELEGRAM_DELIVERY_UNCERTAIN: timeout")
        self.ledger, stats = run_once(self.rows, self.ledger, send, self.clock)
        self.assertEqual(self.entry()["status"], "delivery_uncertain_manual_review")
        for _ in range(3):
            self.clock.advance(hours=1)
            run_once(self.rows, self.ledger, send, self.clock)
        self.assertEqual(len(calls), 1)

    def test_missing_message_id_is_uncertain(self):
        self.ledger, _ = run_once(self.rows, self.ledger, lambda m: None, self.clock)
        self.assertEqual(self.entry()["status"], "delivery_uncertain_manual_review")

    def test_game_starting_before_a_safe_retry_becomes_expired_not_sent(self):
        self.ledger, _ = run_once(self.rows, self.ledger, rejected(429, 600), self.clock)
        self.clock.now = KO + timedelta(minutes=1)
        calls = []
        self.ledger, stats = three.process([], self.ledger, self.clock.now, lambda m: calls.append(m) or 1, True, clock=self.clock)
        self.assertEqual((calls, self.entry()["status"], stats["expired_not_sent"]), ([], "expired_not_sent", 1))
        self.assertEqual(self.entry()["http_status"], 429)

    def test_kickoff_passing_during_the_run_never_sends(self):
        calls = []
        clock = Clock(KO - timedelta(seconds=1))
        def late(m): calls.append(m); return 1
        ledger = three.empty_ledger(NOW)
        clock.now = KO + timedelta(seconds=1)  # the real clock moved past kickoff after planning
        ledger, stats = three.process(self.rows, ledger, NOW, late, True, clock=clock)
        self.assertEqual((calls, ledger["entries"]), ([], {}))

    def test_crash_during_send_never_duplicates(self):
        """The intent is persisted before the call; a dead process leaves send_in_progress."""
        snapshots = []
        def persist(value): snapshots.append(json.loads(json.dumps(value)))
        class Crash(BaseException): pass
        def dies(_): raise Crash()
        with self.assertRaises(Crash):
            run_once(self.rows, self.ledger, dies, self.clock, persist)
        self.assertEqual(snapshots[-1]["entries"]["fixture-1"]["status"], "send_in_progress")
        restarted = snapshots[-1]
        calls = []
        self.clock.advance(minutes=5)
        restarted, stats = run_once(self.rows, restarted, lambda m: calls.append(m) or 5, self.clock)
        self.assertEqual(calls, [])
        self.assertEqual(restarted["entries"]["fixture-1"]["status"], "delivery_uncertain_manual_review")
        self.assertEqual(restarted["entries"]["fixture-1"]["reason"], "process_ended_during_send")

    def test_existing_receipts_and_message_ids_are_preserved(self):
        self.ledger["entries"]["fixture-1"] = {"status": "sent", "telegram_message_id": 352, "at": "x"}
        before = json.dumps(self.ledger, sort_keys=True)
        self.ledger, stats = run_once(self.rows, self.ledger, lambda m: self.fail("resent"), self.clock)
        self.assertEqual(json.dumps(self.ledger, sort_keys=True), before)
        self.assertEqual(stats["already_notified"], 1)

    def test_state_is_deterministic_after_restart_from_disk(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "l.json"
            persist = lambda v: path.write_text(json.dumps(v, sort_keys=True))
            self.ledger, _ = run_once(self.rows, self.ledger, rejected(429, 90), self.clock, persist)
            reloaded = json.loads(path.read_text())
            self.assertEqual(reloaded, self.ledger)
            self.clock.advance(seconds=100)
            reloaded, _ = run_once(self.rows, reloaded, lambda m: 9, self.clock, persist)
            self.assertEqual(reloaded["entries"]["fixture-1"]["status"], "sent")


class TwoUpParityTests(unittest.TestCase):
    def test_two_up_uses_the_same_machine(self):
        # Reuse the 2-up fixtures from its own test module to build a valid row.
        from tests.test_two_up_notify import select as select_two, lomza, NOW as T2
        rows = select_two(lomza())
        ledger = two.empty_ledger(T2)
        clock = Clock(T2)
        ledger, stats = two.process(rows, ledger, T2, rejected(429, 30), True, clock=clock)
        key = rows[0]["match_key"]
        self.assertEqual((ledger["entries"][key]["status"], stats["rejected"]), ("delivery_rejected", 1))
        clock.advance(seconds=31)
        ledger, stats = two.process(rows, ledger, clock.now, lambda m: 11, True, clock=clock)
        self.assertEqual(ledger["entries"][key]["status"], "sent")


class PublicationContractTests(unittest.TestCase):
    def test_transient_states_are_not_receipts_and_terminal_ones_are_accepted(self):
        from h1lab import telegram_eligibility as te
        self.assertIn("delivery_rejected_final", td.TERMINAL_RECEIPT_STATUSES)
        self.assertNotIn("delivery_rejected", td.TERMINAL_RECEIPT_STATUSES)
        self.assertNotIn("send_in_progress", td.TERMINAL_RECEIPT_STATUSES)
        import scripts.lab_ft_publish_safe as safe
        src = Path(safe.__file__).read_text()
        for status in td.TERMINAL_RECEIPT_STATUSES:
            self.assertIn('"%s"' % status, src, status)


if __name__ == "__main__":
    unittest.main()
