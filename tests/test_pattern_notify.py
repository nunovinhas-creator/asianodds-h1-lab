"""MASTER BRAIN Telegram: prospective, bootstrap-safe, one delivery per game."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from h1lab.bot import BotDeliveryError
from h1lab.pattern_notify import message_for_pattern, new_ledger, process, run

NOW = datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc)


def row(key="2026-10-28,1,2", last_at=None, category="RISING_WITH_FLAT"):
    last_at = last_at or (NOW + timedelta(minutes=2)).isoformat()
    return {
        "match_key": key, "match_label": "Casa FC vs Fora FC",
        "kickoff_utc": (NOW + timedelta(hours=3)).isoformat(),
        "last_alert_at": last_at, "messages": 2, "episodes": 2,
        "strict_condition": True, "category": category,
        "total_line_before": 2.5, "total_line_after": 2.75,
        "observations": [
            {"event_id": "123:1", "delta_lambda": .10},
            {"event_id": "123:2", "delta_lambda": -.01},
        ],
    }


class PatternNotifyTests(unittest.TestCase):
    def test_bootstrap_suppresses_old_candidates(self):
        old = row()
        ledger = new_ledger([old], ["already-observed"], NOW)
        ledger, stats = process([old], ledger, NOW+timedelta(minutes=5), lambda _: 4, True)
        self.assertEqual(stats["sent"], 0)
        self.assertEqual(ledger["entries"][old["match_key"]]["status"], "suppressed_at_activation")
        self.assertIn("already-observed", ledger["entries"])

    def test_new_pattern_is_sent_once_with_receipt(self):
        r = row()
        ledger = new_ledger([], [], NOW)
        msgs = []
        def sender(message):
            msgs.append(message)
            return 875
        ledger, stats = process([r], ledger, NOW+timedelta(minutes=4), sender, True)
        self.assertEqual(stats["sent"], 1)
        self.assertEqual(ledger["entries"][r["match_key"]]["telegram_message_id"], 875)
        self.assertIn("NÃO validada", msgs[0])
        self.assertIn("2 episódios independentes", msgs[0])
        self.assertIn("Linha de golos Total (Over/Under): 2,75", msgs[0])
        self.assertIn("Último movimento da linha: 2,5 → 2,75", msgs[0])
        ledger, stats = process([r], ledger, NOW+timedelta(minutes=10), sender, True)
        self.assertEqual(stats["sent"], 0)
        self.assertEqual(len(msgs), 1)

    def test_missing_bot_config_preserves_pending_match(self):
        r = row()
        ledger, stats = process([r], new_ledger([], [], NOW), NOW+timedelta(minutes=4),
                                lambda _: self.fail("should not send"), False)
        self.assertEqual(stats["unconfigured"], 1)
        self.assertNotIn(r["match_key"], ledger["entries"])

    def test_before_activation_wont_replay(self):
        r = row(last_at=(NOW-timedelta(minutes=1)).isoformat())
        ledger, stats = process([r], new_ledger([], [], NOW), NOW+timedelta(minutes=4),
                                lambda _: self.fail("should not send"), True)
        self.assertEqual(stats["sent"], 0)
        self.assertNotIn(r["match_key"], ledger["entries"])

    def test_uncertain_delivery_no_automatic_retry(self):
        r = row()
        attempts = []
        def uncertain(message):
            attempts.append(message)
            raise BotDeliveryError("TELEGRAM_DELIVERY_UNCERTAIN")
        ledger, stats = process([r], new_ledger([], [], NOW), NOW+timedelta(minutes=4), uncertain, True)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(ledger["entries"][r["match_key"]]["status"], "delivery_uncertain_manual_review")
        process([r], ledger, NOW+timedelta(minutes=5), uncertain, True)
        self.assertEqual(len(attempts), 1)

    def test_bad_category_refused(self):
        with self.assertRaises(ValueError):
            message_for_pattern(row(category="FALLING"))

    def test_unchanged_line_is_included_without_imagined_movement(self):
        r = row()
        r["total_line_before"] = 2.25
        r["total_line_after"] = 2.25
        message = message_for_pattern(r)
        self.assertIn("Linha de golos Total (Over/Under): 2,25", message)
        self.assertIn("Linha inalterada no último alerta", message)
        self.assertNotIn("2,5 → 2,75", message)

    def test_missing_line_does_not_notify_or_consume_receipt(self):
        r = row()
        r["total_line_after"] = None
        ledger = new_ledger([], [], NOW)
        calls = []
        ledger, stats = process([r], ledger, NOW + timedelta(minutes=4),
                                lambda msg: calls.append(msg) or 9, True)
        self.assertEqual(stats["sent"], 0)
        self.assertEqual(stats["missing_total_line"], 1)
        self.assertNotIn(r["match_key"], ledger["entries"])
        self.assertEqual(calls, [])
        with self.assertRaises(ValueError):
            message_for_pattern(r)

    def test_first_run_bootstraps_then_next_fresh_candidate_delivered(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            hist = root / "data/lab/pattern-watch-first-seen.json"
            hist.parent.mkdir(parents=True)
            hist.write_text(json.dumps({"entries": [{"match_key": "historical"}]}))
            previous = row("old")
            current = row("new")
            with patch("h1lab.pattern_notify.read_sources", return_value=([], [], [])), \
                 patch("h1lab.pattern_notify.collect_timelines", return_value=([previous], [], [])), \
                 patch("h1lab.pattern_notify.inspect", return_value=previous):
                state = run(root=root, now=NOW, sender=lambda _: self.fail("bootstrap sent"), bot_enabled=True)
            self.assertIn("historical", state["entries"])
            self.assertIn("old", state["entries"])
            sent = []
            with patch("h1lab.pattern_notify.read_sources", return_value=([], [], [])), \
                 patch("h1lab.pattern_notify.collect_timelines", return_value=([current], [], [])), \
                 patch("h1lab.pattern_notify.inspect", return_value=current):
                state = run(root=root, now=NOW+timedelta(minutes=3),
                            sender=lambda m: sent.append(m) or 17, bot_enabled=True)
            self.assertEqual(state["entries"]["new"]["status"], "sent")
            self.assertEqual(len(sent), 1)


if __name__ == "__main__":
    unittest.main()
