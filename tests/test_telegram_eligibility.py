"""Telegram eligibility diagnostics: explain filters without changing senders."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from h1lab import telegram_eligibility as audit
from h1lab import three_moves_notify, two_up_notify
from h1lab.timeline import collect_timelines

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
KO = NOW + timedelta(hours=4)


def alert(i, before, after, *, match="fixture", at=None, ko=KO):
    return {
        "event_id": "telegram:" + str(i), "message_id": i,
        "match_key": match, "home": "Casa", "away": "Fora",
        "kickoff_utc": ko.isoformat(),
        "observed_at": (at or NOW - timedelta(minutes=60-i*10)).isoformat(),
        "market": "total", "total_before": before, "total_after": after,
        "over_before": 1.8, "over_after": 1.9,
        "under_before": 2.0, "under_after": 1.9,
    }


def timelines(rows, *, v4_ids=None):
    if v4_ids is None:
        v4_ids = {x["event_id"] for x in rows}
    markets = [{
        "event_id": x["event_id"], "match_key": x["match_key"],
        "kickoff_utc": x["kickoff_utc"], "observed_at": x["observed_at"],
        "trigger_market": "total",
        "markets": {"total": {
            "before": {"line": x["total_before"], "over_price": x["over_before"],
                       "under_price": x["under_before"]},
            "after": {"line": x["total_after"], "over_price": x["over_after"],
                      "under_price": x["under_after"]},
        }},
    } for x in rows if x["event_id"] in v4_ids]
    out, issues, excluded = collect_timelines(rows, markets)
    assert not issues and not excluded
    return out


class EligibilityTests(unittest.TestCase):
    def test_three_independent_and_two_up_are_not_same_rule(self):
        rows = [alert(1, 2.5, 2.75), alert(2, 2.75, 3.0),
                alert(3, 3.0, 2.75)]
        report = audit.build(timelines(rows), NOW)
        r = report["games"]["fixture"]
        self.assertTrue(r["three_eligible"])
        self.assertFalse(r["two_eligible"])
        self.assertEqual((r["valid_three_moves"], r["valid_up_moves"]), (3, 2))
        self.assertTrue(r["v4_down_observed"])

    def test_two_up_and_flat_third_message(self):
        rows = [alert(1, 3.25, 3.5), alert(2, 3.5, 3.75),
                alert(3, 3.75, 3.75)]
        r = audit.build(timelines(rows), NOW)["games"]["fixture"]
        self.assertTrue(r["two_eligible"])
        self.assertFalse(r["three_eligible"])
        self.assertEqual(r["rejects"].get("flat_total_line"), 1)
        self.assertEqual(r["net_up"], .5)

    def test_duplicate_not_treated_as_three_independent(self):
        rows = [alert(1, 3, 2.75),
                alert(2, 3, 2.75, at=NOW-timedelta(minutes=49, seconds=58)),
                alert(3, 2.75, 3.0)]
        rows[0]["observed_at"] = (NOW-timedelta(minutes=50)).isoformat()
        r = audit.build(timelines(rows), NOW)["games"]["fixture"]
        self.assertFalse(r["three_eligible"])
        self.assertTrue(r["review_possible_false_negative"])
        self.assertLess(r["valid_three_moves"], r["v4_moves_observed"])
        self.assertGreater(sum(r["rejects"].values()), 0)

    def test_h1_legacy_not_counted_and_stale_no_retroactive_alert(self):
        rows = [alert(1, 3, 2.75), alert(2, 2.75, 3),
                alert(3, 3, 2.75)]
        t = timelines(rows, v4_ids={rows[0]["event_id"], rows[1]["event_id"]})
        r = audit.build(t, NOW)["games"]["fixture"]
        self.assertFalse(r["three_eligible"])
        self.assertEqual(r["rejects"]["not_explicit_v4"], 1)
        late = NOW + timedelta(hours=6)
        past = audit.build(t, late)["games"]["fixture"]
        self.assertFalse(past["three_eligible"])
        self.assertIn("já iniciado", past["reason"])

    def test_receipt_reports_sent_but_does_not_send(self):
        rows = [alert(1, 3.25, 3.50), alert(2, 3.50, 3.75)]
        receipt = {"fixture": {"status": "sent", "telegram_message_id": 123}}
        report = audit.build(timelines(rows), NOW, receipts_two=receipt)
        self.assertEqual(report["games"]["fixture"]["receipts"]["two"],
                         {"status": "sent", "telegram_message_id": 123})

    def test_any_sender_parity_drift_blocks_report(self):
        rows = timelines([alert(1, 3.25, 3.50), alert(2, 3.50, 3.75)])
        with patch.object(two_up_notify, "candidates", return_value=[]):
            with self.assertRaisesRegex(ValueError, "parity mismatch"):
                audit.build(rows, NOW)

    def test_report_only_publishes_repeated_games(self):
        single = timelines([alert(1, 2.5, 2.75)])[0]
        report = audit.build([single], NOW)
        self.assertEqual(report["games"], {})
        self.assertEqual(report["summary"]["visible_games"], 0)


if __name__ == "__main__":
    unittest.main()
