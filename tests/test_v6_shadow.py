"""V6 regression tests: no backfill, no overwrite, no H1 notification coupling."""
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from h1lab.v6_shadow import (ALPHA, ZERO_HASH, append_journal, captures,
                              quality, read_journal, report, sequential)


def now():
    return datetime(2026, 10, 28, 14, 30, tzinfo=timezone.utc)


def snap(line1=2.5, line2=2.5, o1=1.9, o2=1.89, u1=1.9, u2=1.92):
    return {"before": {"line": line1, "over_price": o1, "under_price": u1},
            "after": {"line": line2, "over_price": o2, "under_price": u2}}


def fixture(kickoff):
    return {
        "match_key": "match-1", "match_label": "A vs B",
        "identity": {"kickoff_utc": [kickoff], "kickoff_consistent": True,
                     "team_names_consistent": True, "per_message_conflicts": []},
        "movement_episodes": [["message-1"]],
        "events": [{"event_id": "message-1", "observed_at": "2026-10-28T13:00:00+00:00",
                    "minutes_to_kickoff": 180,
                    "snapshots": {"total": snap()}}],
    }


class QualityTests(unittest.TestCase):
    def test_usable_quote(self):
        q = quality(snap())
        self.assertEqual(q["status"], "USABLE")
        self.assertIsNotNone(q["p_over_2_5"])

    def test_cross_line_repeated_price_is_flagged(self):
        q = quality(snap(line2=2.75, o2=1.9))
        self.assertEqual(q["status"], "UNUSABLE")
        self.assertIn("cross_line_unchanged_price", q["flags"])
        self.assertIsNone(q["p_over_2_5"])

    def test_negative_margin_flag(self):
        q = quality(snap(o2=2.6, u2=2.6))
        self.assertIn("negative_after_margin", q["flags"])
        self.assertIsNone(q["p_over_2_5"])

    def test_no_total_stays_unknown(self):
        self.assertEqual(quality(None)["status"], "NO_TOTAL")


class JournalTests(unittest.TestCase):
    def test_append_only_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = {"match_key": "m1", "event_id": "one", "known_at": now().isoformat()}
            self.assertEqual(append_journal(tmp, now(), [row]), 1)
            self.assertEqual(append_journal(tmp, now(), [row]), 0)
            rows = read_journal(tmp)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["previous_sha256"], ZERO_HASH)

    def test_chain_detects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            append_journal(tmp, now(), [{"match_key": "m1", "event_id": "one"}])
            f = next((Path(tmp) / "data/lab").glob("v6-forecasts-*.jsonl"))
            f.write_text(f.read_text().replace("m1", "m2"), encoding="utf-8")
            with self.assertRaises(ValueError):
                read_journal(tmp)

    def test_second_event_keeps_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            append_journal(tmp, now(), [{"match_key": "m1", "event_id": "one"}])
            append_journal(tmp, now(), [{"match_key": "m1", "event_id": "two"}])
            rows = read_journal(tmp)
            self.assertEqual([x["event_id"] for x in rows], ["one", "two"])


class ProspectiveTests(unittest.TestCase):
    def test_future_only_and_known_at_is_now(self):
        rows = captures([fixture("2026-10-28T16:00:00+00:00")], now())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["known_at"], now().isoformat(timespec="seconds"))
        self.assertEqual(rows[0]["forecast_kind"], "MARKET_BASELINE_ONLY")

    def test_no_retroactive_forecast(self):
        self.assertEqual(captures([fixture("2026-10-28T14:00:00+00:00")], now()), [])

    def test_late_replay_does_not_backdate(self):
        row = captures([fixture("2026-10-28T16:00:00+00:00")], now())[0]
        self.assertNotEqual(row["known_at"], row["observed_at"])

    def test_e_process_is_not_a_p_value(self):
        positives = [{"market_probability_over_2_5": 0.5, "outcome": 1}] * 40
        self.assertGreater(sequential(positives), 1 / ALPHA)
        self.assertAlmostEqual(sequential([]), 1.0)

    def test_no_frozen_oos_means_inconclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "data/lab"
            folder.mkdir(parents=True)
            (folder / "ft-ledger.json").write_text('{"matches":{}}', encoding="utf-8")
            result = report(tmp, [], now())
            self.assertEqual(result["hypothesis"]["state"], "INCONCLUSIVO")
            self.assertEqual(result["forecasts"]["records"], 0)


if __name__ == "__main__":
    unittest.main()
