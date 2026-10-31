"""Telegram cutover: three independently evidenced pre-match Total movements."""
import copy
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from h1lab.bot import BotDeliveryError
from h1lab import three_moves_notify as notify
from h1lab.timeline import collect_timelines

NOW = datetime(2026, 10, 31, 19, 0, tzinfo=timezone.utc)
KO = NOW + timedelta(hours=36)


def alert(i, before, after, *, at=None, ko=KO, match="fixture-1"):
    at = at or NOW - timedelta(minutes=60 - i * 10)
    return {"event_id": "telegram:" + str(i), "message_id": i, "match_key": match,
            "home": "Casa", "away": "Fora", "kickoff_utc": ko.isoformat(),
            "observed_at": at.isoformat(), "market": "total",
            "total_before": before, "total_after": after,
            "over_before": 1.8, "under_before": 2.0,
            "over_after": 1.9, "under_after": 1.9}


def v4(a):
    return {"event_id": a["event_id"], "match_key": a["match_key"],
            "observed_at": a["observed_at"], "kickoff_utc": a["kickoff_utc"],
            "trigger_market": "total",
            "markets": {"total": {
                "before": {"line": a["total_before"], "over_price": a["over_before"],
                           "under_price": a["under_before"]},
                "after": {"line": a["total_after"], "over_price": a["over_after"],
                          "under_price": a["under_after"]}}}}


def three():
    return [alert(1, 3.0, 2.75), alert(2, 2.75, 3.0), alert(3, 3.0, 2.75)]


def candidates(rows=None, markets=None, *, now=NOW):
    rows = rows if rows is not None else three()
    markets = markets if markets is not None else [v4(a) for a in rows]
    timeline, _, excluded = collect_timelines(rows, markets)
    assert not excluded
    return notify.candidates(timeline, now)


class ThreeTotalMovementTests(unittest.TestCase):
    def test_three_real_alternating_v4_messages_are_eligible_beyond_12h(self):
        rows = candidates()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["movement_count"], 3)
        self.assertEqual(rows[0]["reversals"], 2)
        self.assertEqual(rows[0]["kickoff_utc"], KO.isoformat())
        msg = notify.message_for_game(rows[0])
        self.assertIn("3+ MOVIMENTOS", msg)
        self.assertIn("Casa vs Fora", msg)
        self.assertIn("Inversões: 2", msg)
        self.assertIn("3,00→2,75", msg)
        self.assertNotIn("OVER 2,5", msg)
        self.assertLess(len(msg), 400)

    def test_two_movements_or_flat_prices_never_qualify(self):
        self.assertEqual(candidates(three()[:2]), [])
        rows = three()
        rows[2]["total_after"] = rows[2]["total_before"]
        self.assertEqual(candidates(rows), [])

    def test_legacy_only_snapshot_does_not_become_v4_proof(self):
        rows = three()
        self.assertEqual(candidates(rows, [v4(x) for x in rows[:2]]), [])

    def test_near_identical_alert_is_one_episode_not_three(self):
        rows = three()
        rows[1] = alert(2, 3.0, 2.75, at=NOW-timedelta(minutes=49,seconds=55))
        rows[0]["observed_at"] = (NOW-timedelta(minutes=50)).isoformat()
        self.assertEqual(candidates(rows), [])

    def test_ambiguous_far_repeat_is_not_third_independent_movement(self):
        rows = [alert(1, 3.0, 2.75), alert(2, 3.0, 2.75),
                alert(3, 2.75, 3.0)]
        self.assertEqual(candidates(rows), [])

    def test_bad_identity_and_future_information_cannot_qualify(self):
        rows = three()
        rows[2]["observed_at"] = (NOW+timedelta(minutes=1)).isoformat()
        self.assertEqual(candidates(rows), [])
        rows = three()
        rows[1]["kickoff_utc"] = (KO+timedelta(hours=1)).isoformat()
        self.assertEqual(candidates(rows), [])
        past = [alert(i, x, y, ko=NOW-timedelta(minutes=1))
                for i, (x,y) in enumerate([(3.0,2.75),(2.75,3.0),(3.0,2.75)],start=1)]
        self.assertEqual(candidates(past), [])

    def test_one_message_per_match_and_no_six_message_limit(self):
        original = candidates()[0]
        rows = []
        for i in range(15):
            row = copy.deepcopy(original)
            row["match_key"] = "fixture-" + str(i)
            rows.append(row)
        calls = []
        ledger, stats = notify.process(rows, notify.empty_ledger(NOW), NOW,
                                       lambda msg: calls.append(msg) or len(calls), True)
        self.assertEqual(stats["sent"], 15)
        self.assertEqual(len(ledger["entries"]), 15)
        ledger, stats = notify.process(rows, ledger, NOW+timedelta(minutes=1),
                                       lambda _: self.fail("duplicate"), True)
        self.assertEqual(stats["sent"], 0)
        self.assertEqual(stats["already_notified"], 15)

    def test_no_secret_does_not_mark_sent_and_bad_ledger_fails_closed(self):
        rows = candidates()
        ledger, stats = notify.process(rows, notify.empty_ledger(NOW), NOW,
                                       lambda _: self.fail("unconfigured"), False)
        self.assertEqual(stats["unconfigured"], 1)
        self.assertFalse(ledger["entries"])
        with self.assertRaisesRegex(ValueError, "invalid three-move"):
            notify.process(rows, {"entries": {}}, NOW,
                           lambda _: self.fail("invalid ledger sent"), True)

    def test_ambiguous_delivery_never_automatically_retries(self):
        rows = candidates()
        calls = []
        def uncertain(message):
            calls.append(message)
            raise BotDeliveryError("uncertain")
        ledger, stats = notify.process(rows, notify.empty_ledger(NOW), NOW, uncertain, True)
        self.assertEqual(stats["uncertain"], 1)
        self.assertEqual(ledger["entries"]["fixture-1"]["status"],
                         "delivery_uncertain_manual_review")
        notify.process(rows, ledger, NOW+timedelta(minutes=1), uncertain, True)
        self.assertEqual(len(calls), 1)

    def test_clock_prevents_sending_if_game_has_started(self):
        rows = candidates()
        ledger, stats = notify.process(rows, notify.empty_ledger(NOW), NOW,
                                       lambda _: self.fail("started"), True,
                                       clock=lambda: KO+timedelta(seconds=1))
        self.assertEqual(stats["expired"], 1)
        self.assertEqual(ledger["entries"], {})

    def test_dry_run_does_not_send_or_create_receipts(self):
        rows = three()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(notify, "read_sources", return_value=(rows, [v4(x) for x in rows], [])):
                result = notify.run(root=tmp, now=NOW, sender=lambda _: self.fail("sent"),
                                    bot_enabled=True, dry_run=True)
            self.assertEqual(result["entries"], {})
            self.assertFalse((Path(tmp)/notify.LEDGER).exists())

    def test_production_workflow_has_exactly_one_telegram_sender(self):
        root = Path(__file__).resolve().parents[1]
        wf = (root / ".github/workflows/collect.yml").read_text(encoding="utf-8")
        self.assertEqual(wf.count("run: python -m h1lab.three_moves_notify"), 1)
        self.assertNotIn("run: python -m h1lab.e4_notify", wf)
        self.assertNotIn("run: python -m h1lab.t05_notify", wf)
        self.assertNotIn("run: python -m h1lab.strategy_notify", wf)
        self.assertNotIn("run: python -m h1lab.pattern_notify", wf)
        self.assertNotIn("run: python -m h1lab.notify", wf)
        self.assertIn("git add data/three-total-moves-notifications.json", wf)


if __name__ == "__main__":
    unittest.main()
