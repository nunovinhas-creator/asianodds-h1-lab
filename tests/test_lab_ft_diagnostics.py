"""No-network regression tests for read-only LAB FT diagnostics."""
import unittest
from h1lab.lab_ft_diagnostics import coverage_diagnostics


class FTDiagnosticsTests(unittest.TestCase):
    def test_overlapping_provider_failures_do_not_double_count_games(self):
        ledger = {"matches": {
            "a": {"status": "PENDING", "provider_reasons": {
                "bsd": "monte_no_exact_archive_match",
                "espn": "espn_unsupported_competition"}},
            "b": {"status": "SOURCE_ORDER_CONFLICT", "provider_reasons": {
                "sportscore": "verified_sportscore_ft"}},
            "c": {"status": "FINAL", "provider_reasons": {
                "bsd": "verified_bsd_ft"}},
            "d": {"status": "PENDING", "provider_reasons": {}},
        }}
        report = {"final_recorded": 1, "timing_counts": {
            "FINAL_RECORDED": 1, "FUTURE": 1, "IN_3H_GRACE": 0,
            "BLOCKED_REVIEW": 1, "ELIGIBLE_COOLDOWN": 1}}
        d = coverage_diagnostics(ledger, report)
        self.assertEqual(d["ft_confirmed"], 1)
        self.assertEqual(d["past_unverified_eligible"], 1)
        self.assertEqual(d["blocked_review"], 1)
        self.assertEqual(d["future"], 1)
        self.assertEqual(d["unresolved_statuses"],
                         {"PENDING": 2, "SOURCE_ORDER_CONFLICT": 1})
        self.assertEqual(sum(x["matches"] for x in d["provider_obstacles"]), 3)
        self.assertNotIn("verified_bsd_ft", str(d["provider_obstacles"]))

    def test_expired_24h_results_are_closed_not_overdue_or_lost(self):
        ledger = {"matches": {
            "confirmed": {"status": "FINAL"},
            "expired": {"status": "EXPIRED_UNVERIFIED"},
            "recent": {"status": "PENDING"},
        }}
        report = {"final_recorded": 1, "timing_counts": {
            "FINAL_RECORDED": 1, "EXPIRED": 1, "ELIGIBLE_NEVER_QUERIED": 1}}
        d = coverage_diagnostics(ledger, report)
        self.assertEqual(d["closed_unverified"], 1)
        self.assertEqual(d["past_unverified_eligible"], 1)
        self.assertEqual(d["ft_confirmed"], 1)
        self.assertEqual(sum(d[k] for k in (
            "ft_confirmed", "future", "grace", "blocked_review",
            "past_unverified_eligible", "closed_unverified", "unknown_kickoff")), 3)

    def test_missing_counts_and_invalid_inputs(self):
        d = coverage_diagnostics({"matches": {}}, {"timing_counts": {}})
        self.assertEqual(d["past_unverified_eligible"], 0)
        with self.assertRaises(ValueError):
            coverage_diagnostics({"matches": []}, {"timing_counts": {}})


if __name__ == "__main__":
    unittest.main()
