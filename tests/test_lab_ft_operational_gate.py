"""Fail-closed single-run operational FT gate, no network."""
import unittest
from scripts.lab_ft_operational_gate import CRITICAL, evaluate_health


def health(*, overrides=None, status="OK"):
    values = {name: "OK" for name in CRITICAL}
    values.update({"ft_execution": "UNKNOWN", "collector": "OK"})
    values.update(overrides or {})
    return {"status": status, "checks": [
        {"name": name, "status": value} for name, value in values.items()]}


class FTHealthGateTests(unittest.TestCase):
    def test_valid_snapshots_do_not_claim_24h_stability(self):
        result = evaluate_health(health(), upstream="success")
        self.assertEqual(result["status"], "DEGRADED")
        self.assertEqual(result["blocked"], [])
        self.assertEqual(result["stable_24h_48h_7d"],
                         "NOT_PROVEN_BY_SINGLE_OBSERVATION")

    def test_missing_journal_or_backlog_fails_closed(self):
        for name in ("ft_journal", "ft_backlog", "ft_counts",
                     "ft_publication", "h1_replay"):
            with self.subTest(name=name):
                x = evaluate_health(health(overrides={name:"UNKNOWN"}))
                self.assertEqual(x["status"],"FAILED")
                self.assertIn(name,x["blocked"])

    def test_missing_check_is_failure_not_implicit_success(self):
        x = evaluate_health({"status":"OK","checks":[]})
        self.assertEqual(x["status"],"FAILED")
        self.assertEqual(len(x["blocked"]),len(CRITICAL))

    def test_upstream_failure_cannot_be_masked_by_healthy_json(self):
        x = evaluate_health(health(), upstream="failure")
        self.assertEqual(x["status"],"FAILED")
        self.assertIn("upstream_ft_run_failed",x["blocked"])

    def test_provider_degradation_is_visible_but_not_fake_ft_corruption(self):
        x = evaluate_health(health(overrides={"ft_execution":"DEGRADED"}))
        self.assertEqual(x["status"],"DEGRADED")
        self.assertIn("ft_execution",x["non_ok_checks"])
        self.assertEqual(x["blocked"],[])


if __name__ == "__main__":
    unittest.main()
