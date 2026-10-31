"""Regression tests for the retired E4 notifier (kept as historical logic)."""
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from h1lab.bot import BotDeliveryError
from h1lab.e4_notify import (
    RULE_VERSION, _pending_action, classification, empty_ledger, message_for_game, process,
)
from h1lab.strategy_notify import STRATEGIES

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
E4 = next(x for x in STRATEGIES if x["number"] == 4)


def game(offset=8, numbers=(4,), match="test-1"):
    kickoff = NOW + timedelta(hours=offset)
    rules = [{**next(s for s in STRATEGIES if s["number"] == n),
              "history": {"hits": 30, "known": 42, "rate": 30/42}}
             for n in numbers]
    return {"match_key": match, "match_label": "Porto vs Benfica",
            "kickoff_utc": kickoff.isoformat(), "observed_through": NOW.isoformat(),
            "rules": rules, "patterns": ["G_LAST_LINE_HIGH"],
            "last_total_v4": 3.25, "last_total_observed_at": NOW.isoformat(),
            "weakening_verified": True}


class E4OnlyTests(unittest.TestCase):
    def test_single_e4_is_isolated_and_clearly_marked(self):
        r = game()
        group = classification(r)
        self.assertEqual(group["kind"], "ISOLADA")
        msg = message_for_game(r, group, "entered")
        self.assertIn("🟢 E4 ISOLADA", msg)
        self.assertIn("5/6 isolada", msg)
        self.assertNotIn("➕", msg)

    def test_e4_with_any_other_strategy_is_combined_but_only_e4_is_recommended(self):
        r = game(numbers=(1, 2, 3, 4, 5))
        group = classification(r)
        self.assertEqual(group["kind"], "COMBINADA")
        msg = message_for_game(r, group, "entered")
        self.assertIn("🟣 E4 COMBINADA", msg)
        self.assertIn("E1, E2, E3, E5", msg)
        self.assertNotIn("🎯 E1 ·", msg)
        self.assertNotIn("🎯 E3 ·", msg)

    def test_all_non_e4_eligible_games_silenced(self):
        r = game(numbers=(1, 2, 3, 5))
        sent = []
        ledger, stats = process([r], empty_ledger(NOW), NOW,
                                lambda m: sent.append(m) or 301, True)
        self.assertEqual(sent, [])
        self.assertEqual(ledger["entries"], {})
        self.assertEqual(stats["games_sent"], 0)

    def test_first_run_sends_all_detected_even_if_old_five_strategy_ledger_exists(self):
        rows = [game(numbers=(4,), match="m-" + str(i)) for i in range(9)]
        rows.append(game(numbers=(1, 3), match="without-e4"))
        sent = []
        ledger, stats = process(rows, empty_ledger(NOW), NOW,
                                lambda m: sent.append(m) or len(sent), True)
        self.assertEqual(len(sent), 9)
        self.assertEqual(stats["e4_isolated"], 9)
        self.assertEqual(len(ledger["entries"]), 9)
        self.assertTrue(all(key.endswith("|4") for key in ledger["entries"]))
        ledger, stats = process(rows, ledger, NOW + timedelta(minutes=5),
                                lambda _: self.fail("duplicate E4"), True)
        self.assertEqual(stats["games_sent"], 0)

    def test_category_switch_sends_once_notifies_new_classification(self):
        r = game(numbers=(4,))
        ledger, _ = process([r], empty_ledger(NOW), NOW, lambda _: 101, True)
        updated = game(numbers=(1, 4))
        updated["observed_through"] = (NOW + timedelta(minutes=4)).isoformat()
        sent = []
        ledger, stats = process([updated], ledger, NOW + timedelta(minutes=5),
                                lambda m: sent.append(m) or 102, True)
        self.assertEqual(stats["category_changes_sent"], 1)
        self.assertIn("AGORA", sent[0])
        self.assertIn("COMBINADA", sent[0])
        self.assertEqual(ledger["entries"]["test-1|4"]["kind"], "COMBINADA")
        ledger, stats = process([updated], ledger, NOW + timedelta(minutes=6),
                                lambda _: self.fail("duplicate category"), True)
        self.assertEqual(stats["games_sent"], 0)

    def test_exit_only_with_new_explicit_evidence(self):
        r = game()
        ledger, _ = process([r], empty_ledger(NOW), NOW, lambda _: 101, True)
        no_e4 = game(numbers=(1,))
        # Removing a rule without new explicit evidence never generates false exit.
        ledger, stats = process([no_e4], ledger, NOW + timedelta(minutes=1),
                                lambda _: self.fail("unsupported exit"), True)
        self.assertEqual(stats["withdrawals_sent"], 0)
        no_e4["observed_through"] = (NOW + timedelta(minutes=3)).isoformat()
        no_e4["last_total_observed_at"] = no_e4["observed_through"]
        no_e4["last_total_v4"] = 3.0
        messages = []
        ledger, stats = process([no_e4], ledger, NOW + timedelta(minutes=4),
                                lambda m: messages.append(m) or 103, True)
        self.assertEqual(stats["withdrawals_sent"], 1)
        self.assertIn("SAIU DA E4", messages[0])
        self.assertEqual(ledger["entries"]["test-1|4"]["status"], "withdrawn")

    def test_outside_window_or_started_not_sent(self):
        rows = [game(offset=13,match="later"), game(offset=-1,match="past")]
        ledger, stats = process(rows, empty_ledger(NOW), NOW,
                                lambda _: self.fail("outside window"), True)
        self.assertFalse(ledger["entries"])
        self.assertEqual(stats["games_sent"], 0)

    def test_no_bot_does_not_consume_receipts(self):
        ledger, stats = process([game()], empty_ledger(NOW), NOW,
                                lambda _: self.fail("unconfigured"), False)
        self.assertEqual(stats["unconfigured"], 1)
        self.assertFalse(ledger["entries"])

    def test_uncertain_delivery_never_auto_retries(self):
        calls = []
        def broken(m):
            calls.append(m)
            raise BotDeliveryError("uncertain")
        ledger, stats = process([game()], empty_ledger(NOW), NOW, broken, True)
        self.assertEqual(stats["failed"], 1)
        ledger, stats = process([game()], ledger, NOW + timedelta(minutes=1),
                                broken, True)
        self.assertEqual(len(calls), 1)

    def test_workflow_only_runs_e4_not_five_or_pattern(self):
        text = (Path(__file__).resolve().parents[1] /
                ".github/workflows/collect.yml").read_text(encoding="utf-8")
        self.assertNotIn("run: python -m h1lab.e4_notify", text)
        self.assertIn("run: python -m h1lab.three_moves_notify", text)
        self.assertNotIn("run: python -m h1lab.strategy_notify", text)
        self.assertNotIn("run: python -m h1lab.pattern_notify", text)
        self.assertNotIn("run: python -m h1lab.notify", text)
        self.assertNotIn("git add data/e4-notifications.json", text)


if __name__ == "__main__":
    unittest.main()
