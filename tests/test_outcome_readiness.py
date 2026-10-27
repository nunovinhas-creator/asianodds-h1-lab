"""Synthetic safety tests for LAB-only outcome coverage; no betting metrics."""
import unittest
from datetime import datetime, timezone

from h1lab.outcome_readiness import STATUS, generate


def timeline():
    return {
        "source_commit": "abc123",
        "summary": {"matches": 3, "repeated_matches": 2},
        "sampling": {"timelines_omitted": 0},
        "timelines": [
            {
                "match_key": "2026-10-27,1,2",
                "identity": {"kickoff_utc": ["2026-10-27T10:00:00+00:00"]},
                "events": [
                    {"minutes_to_kickoff": 90, "snapshots": {"total": {"before": {"line": 2.5}, "after": {"line": 2.75}}}},
                    {"minutes_to_kickoff": 30, "snapshots": {"total": {"before": {"line": 2.75}, "after": {"line": 3}}}},
                ],
            },
            {
                "match_key": "2026-10-28,3,4",
                "identity": {"kickoff_utc": ["2026-10-28T10:00:00+00:00"]},
                "events": [
                    {"minutes_to_kickoff": 30, "snapshots": {"total": {"before": {"line": 2}, "after": {"line": 2.25}}}},
                    {"minutes_to_kickoff": -1, "snapshots": {"total": {"before": {"line": 2.25}, "after": {"line": 2.5}}}},
                ],
            },
        ],
    }


NOW = datetime(2026, 10, 27, 20, tzinfo=timezone.utc)
HEADER = "match_key,status,home_goals,away_goals,source\n"


class OutcomeReadinessTests(unittest.TestCase):
    def test_no_repeated_match_results_is_not_a_loss(self):
        csv_data = HEADER + '"2026-10-27,9,9",final,2,1,https://example.org/ft\n'
        report = generate(timeline(), csv_data, {}, now=NOW)
        self.assertEqual(report["status"], STATUS)
        self.assertFalse(report["inference_gate"]["approved"])
        self.assertEqual(report["repeated_match_outcomes"]["with_h1_final_record"], 0)
        self.assertEqual(report["repeated_match_outcomes"]["statuses"]["NOT_TRACKED_IN_H1_RESULT_FILES"], 2)
        self.assertEqual(report["pregame_data_readiness"]["all_observed_alerts_before_kickoff"], 1)
        self.assertEqual(report["pregame_data_readiness"]["at_least_two_nonflat_pregame_total_messages"], 1)
        self.assertNotIn("roi", str(report).lower())

    def test_repeated_match_settled_with_traceable_ft(self):
        csv_data = HEADER + '"2026-10-27,1,2",final,1,1,https://example.org/ft\n'
        r = generate(timeline(), csv_data, {"2026-10-28,3,4": {"status": "pending"}}, now=NOW)
        self.assertEqual(r["repeated_match_outcomes"]["with_h1_final_record"], 1)
        self.assertEqual(r["repeated_match_outcomes"]["statuses"]["H1_LOOKUP_PENDING"], 1)
        self.assertEqual(r["repeated_match_outcomes"]["coverage_pct_of_published_repeated"], 50.0)
        self.assertFalse(r["inference_gate"]["approved"])

    def test_invalid_ft_not_counted(self):
        csv_data = HEADER + '"2026-10-27,1,2",final,1,x,https://example.org/ft\n'
        r = generate(timeline(), csv_data, {}, now=NOW)
        self.assertEqual(r["scope"]["h1_final_rows_invalid"], 1)
        self.assertEqual(r["repeated_match_outcomes"]["with_h1_final_record"], 0)
        self.assertEqual(r["repeated_match_outcomes"]["statuses"]["H1_RESULT_ROW_NOT_FINAL"], 1)

    def test_duplicate_ft_keys_fail_closed(self):
        csv_data = HEADER + '"2026-10-27,1,2",final,1,1,https://example.org/a\n' \
                    + '"2026-10-27,1,2",final,2,1,https://example.org/b\n'
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            generate(timeline(), csv_data, {}, now=NOW)

    def test_sample_inconsistency_fails_closed(self):
        data = timeline()
        data["sampling"]["timelines_omitted"] = 2
        with self.assertRaisesRegex(ValueError, "coverage inconsistent"):
            generate(data, HEADER, {}, now=NOW)

    def test_partial_publication_is_explicit(self):
        data = timeline()
        data["summary"]["repeated_matches"] = 4
        data["sampling"]["timelines_omitted"] = 2
        r = generate(data, HEADER, {}, now=NOW)
        self.assertTrue(r["repeated_match_outcomes"]["coverage_partial_if_omitted"])
        self.assertEqual(r["scope"]["repeated_matches_omitted"], 2)


if __name__ == "__main__":
    unittest.main()
