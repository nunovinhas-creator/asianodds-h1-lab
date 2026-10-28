"""Backlog ledger diagnosis and one-time provider activation, no live HTTP."""
import unittest
from datetime import datetime, timezone

from h1lab.lab_ft_backlog import audit, STATUS
from scripts.lab_results import backlog_recovery_enabled

NOW=datetime(2026,10,28,17,tzinfo=timezone.utc)


def fixture(ko, status="PENDING", checked=None, reasons=None):
    return {"status":status,"home":"Home","away":"Away","kickoff_utc":ko,
            "checked_at":checked,"provider_reasons":reasons or {},
            "attempts":int(bool(checked))}


class BacklogTests(unittest.TestCase):
    def test_split_finished_future_grace_review_and_overdue(self):
        ledger={"schema_version":1,"matches":{
            "f":fixture("2026-10-27T12:00:00Z", "FINAL"),
            "u":fixture("2026-10-27T13:00:00Z"),
            "c":fixture("2026-10-28T15:00:00Z"),
            "n":fixture("2026-10-29T17:00:00Z"),
            "r":fixture("2026-10-27T15:00:00Z","SOURCE_ORDER_CONFLICT"),
            "q":fixture("2026-10-28T10:00:00Z",checked="2026-10-28T14:00:00Z",
                         reasons={"bsd":"no_match","goal":"goal_identity_no_core_match"})
        }}
        d=audit(ledger,NOW,provider_summary={"api_football":{"requests":0}})
        self.assertEqual(d["status"],STATUS)
        self.assertEqual(d["classification"]["verified_ft"],1)
        self.assertEqual(d["classification"]["past_due_unverified"],2)
        self.assertEqual(d["classification"]["past_due_never_checked"],1)
        self.assertEqual(d["classification"]["in_3h_grace"],1)
        self.assertEqual(d["classification"]["future"],1)
        self.assertEqual(d["classification"]["quarantined_or_identity_review"],1)
        self.assertEqual(d["last_run_providers"]["api_football"]["requests"],0)
        self.assertEqual(d["overdue_by_kickoff_utc_day"]["2026-10-27"]["overdue"],1)
        self.assertEqual(d["overdue_by_kickoff_utc_day"]["2026-10-28"]["overdue"],1)
        self.assertEqual(d["overdue_games"][0]["match_key"],"u")
        self.assertNotIn("home_goals",d["overdue_games"][0])

    def test_timestamp_at_exact_boundary_is_due(self):
        t="2026-10-28T14:00:00+00:00"
        d=audit({"matches":{"x":fixture(t)}},NOW)
        self.assertEqual(d["classification"]["past_due_unverified"],1)

    def test_oneshot_only_explicit_push_main_workflow_and_flag(self):
        good={"LAB_FT_BACKLOG_ONCE_20261028":"true",
              "GITHUB_WORKFLOW":"Lab - Reconcile FT for all observed matches",
              "GITHUB_EVENT_NAME":"push","GITHUB_REF":"refs/heads/main"}
        self.assertTrue(backlog_recovery_enabled(good))
        for k,invalid in (
            ("LAB_FT_BACKLOG_ONCE_20261028","false"),
            ("GITHUB_WORKFLOW","H1 - Collect Telegram"),
            ("GITHUB_EVENT_NAME","schedule"),
            ("GITHUB_REF","refs/heads/feature/test"),
        ):
            bad=dict(good,**{k:invalid})
            with self.subTest(k=k):
                self.assertFalse(backlog_recovery_enabled(bad))
        self.assertFalse(backlog_recovery_enabled({}))

    def test_no_untrusted_provider_json_injection_or_score_fabrication(self):
        d=audit({"matches":{"x":fixture("2026-10-27T14:00:00Z",
                 reasons={"goal":"goal_identity_no_core_match"})}},NOW)
        self.assertNotIn("home_goals",d["overdue_games"][0])
        self.assertTrue(all("evidence" not in x for x in d["overdue_games"]))
