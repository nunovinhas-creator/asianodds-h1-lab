"""V6 coverage gate tests: never claim past weeks or received-at timestamps."""
import unittest
from datetime import datetime, timezone
from h1lab.v6_readiness import measure


def timeline(key, ko="2026-11-01T16:00:00+00:00"):
    return {"match_key": key,
            "identity": {"kickoff_utc": [ko], "kickoff_consistent": True,
                         "team_names_consistent": True, "per_message_conflicts": []},
            "events": [{"event_id": key + ":1",
                        "observed_at": "2026-10-29T14:00:00+00:00"}]}


def record(key):
    return {"match_key": key, "event_id": key + ":1",
            "known_at": "2026-10-28T15:00:00+00:00",
            "kickoff_utc": "2026-11-01T16:00:00+00:00",
            "price_quality": {"status": "USABLE", "flags": []}}


class ReadinessTests(unittest.TestCase):
    def test_no_observed_forecasts_stays_warmup(self):
        r = measure([timeline("one")], [], datetime(2026, 11, 10, tzinfo=timezone.utc))
        self.assertEqual(r["p0_7_day_gate"], "WARMUP")
        self.assertIsNone(r["first_prospective_known_at"])

    def test_wait_seven_days_even_with_perfect_coverage(self):
        r = measure([timeline("one")], [record("one")], datetime(2026, 11, 2, tzinfo=timezone.utc))
        self.assertEqual(r["p0_7_day_gate"], "WARMUP")
        self.assertEqual(r["last_7_kickoff_days"]["ratio"], 1.0)

    def test_source_eligible_99pct_is_not_delivery_certification(self):
        r = measure([timeline("one")], [record("one")], datetime(2026, 11, 5, tzinfo=timezone.utc))
        self.assertEqual(r["p0_7_day_gate"], "SOURCE_COVERAGE_PASS_PENDING_EXTERNAL_VERIFICATION")
        self.assertEqual(r["v6_1_14_day_gate"], "WARMUP")
        self.assertIn("NOT_INGESTION", r["last_7_kickoff_days"]["interpretation"])

    def test_missing_capture_counts_and_does_not_pass(self):
        r = measure([timeline("one"), timeline("two")], [record("one")],
                    datetime(2026, 11, 5, tzinfo=timezone.utc))
        self.assertEqual(r["p0_7_day_gate"], "SOURCE_COVERAGE_BELOW_99_PERCENT")
        self.assertEqual(r["last_7_kickoff_days"]["missing_count"], 1)

    def test_invalid_identity_does_not_enter_denominator(self):
        t = timeline("two")
        t["identity"]["team_names_consistent"] = False
        r = measure([timeline("one"), t], [record("one")],
                    datetime(2026, 11, 5, tzinfo=timezone.utc))
        self.assertEqual(r["last_7_kickoff_days"]["source_eligible"], 1)


if __name__ == "__main__":
    unittest.main()
