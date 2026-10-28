"""V7 evidence retry regression: no credentials, network calls or H1 writes."""
import copy
import unittest
from datetime import datetime, timedelta, timezone

from h1lab.lab_results import reconcile, retry_wait
from h1lab.lab_ft_rotation import choose_days, advance, GOAL_DAILY_LIMIT
from h1lab.lab_ft_backlog import audit
from scripts.lab_ft_watchdog import plan

NOW = datetime(2026, 10, 28, 20, 0, tzinfo=timezone.utc)
GAME = {"match_key": "2026-10-27,100,200", "home": "Home FC",
        "away": "Away FC", "kickoff_utc": "2026-10-27T16:00:00+00:00"}


def api_event(status="NS"):
    return {
        "fixture": {"id": 9999, "date": GAME["kickoff_utc"],
                    "status": {"short": status}},
        "teams": {"home": {"name": "Different One", "id": 401},
                  "away": {"name": "Different Two", "id": 402}},
    }


class FakeAPI:
    def __init__(self, status="NS"):
        self.days = {"2026-10-27": [api_event(status)]}
    def lookup(self, _signal):
        return None, "api_football_candidate_names_differ"


def scan(previous, when, api, checks=30):
    return reconcile(
        {"alerts": [GAME], "signals": []}, [], previous,
        now=when, max_checks=checks,
        bsd_lookup=lambda s: (None, "bsd_no_exact_match"),
        tsdb_lookup=lambda s: (None, "tsdb_limited_this_run"),
        api_football_lookup=api.lookup if api else None,
        lookup_source_version=10 if api else 9, evidence_retry=True)


class V7Tests(unittest.TestCase):
    def test_only_new_snapshot_counts_as_attempt(self):
        initial = {"schema_version": 1, "matches": {}}
        one, _, n1 = scan(initial, NOW, FakeAPI())
        row = one["matches"][GAME["match_key"]]
        self.assertEqual(n1, 1)
        self.assertEqual(row["evidence_attempts"], 1)
        stamp = row["evidence_checked_at"]
        self.assertEqual(row["examined_against"]["api_football"]["candidate_count"], 1)
        two, _, n2 = scan(one, NOW + timedelta(hours=5), FakeAPI())
        row2 = two["matches"][GAME["match_key"]]
        self.assertEqual(n2, 1)  # a visit, NOT an effective attempt
        self.assertNotEqual(row2["evidence_checked_at"], stamp)
        self.assertEqual(row2["stable_confirmations"], 1)
        self.assertEqual(row2["examined_against"]["api_football"]["stable_confirmations"], 1)
        self.assertEqual(row2["evidence_attempts"], 1)
        self.assertEqual(row2["attempts"], 1)
        # A changed list resets the stability streak, but only when due.
        _, _, skipped = scan(two, NOW + timedelta(hours=6), FakeAPI("FT"))
        self.assertEqual(skipped, 0)
        three, _, n3 = scan(two, NOW + timedelta(hours=17), FakeAPI("FT"))
        row3 = three["matches"][GAME["match_key"]]
        self.assertEqual(n3, 1)
        self.assertEqual(row3["evidence_attempts"], 2)
        self.assertEqual(row3["stable_confirmations"], 0)
        self.assertNotEqual(row3["evidence_checked_at"], stamp)

    def test_24h_immutable_list_triggers_three_scans_not_45min_polling(self):
        previous = {"schema_version": 1, "matches": {}}
        calls = []
        for half_hour in range(48):
            when = NOW + timedelta(minutes=30 * half_hour)
            api = FakeAPI()
            ledger, _, checked = scan(previous, when, api)
            if checked:
                calls.append(half_hour * 0.5)
            previous = ledger
        self.assertEqual(calls, [0, 4, 16])
        final = previous["matches"][GAME["match_key"]]
        self.assertEqual(final["evidence_attempts"], 1)
        self.assertEqual(final["stable_confirmations"], 2)
        self.assertEqual(final["attempts"], 1)
        self.assertEqual(retry_wait(final), timedelta(hours=24))
        self.assertEqual(final["examined_against"]["api_football"]["stable_confirmations"], 2)

    def test_missing_or_failed_list_does_not_count_as_stable(self):
        class FailedAPI(FakeAPI):
            def __init__(self):
                self.days = {"2026-10-27": None}
        prior = {"schema_version": 1, "matches": {}}
        one, _, n1 = scan(prior, NOW, FailedAPI())
        self.assertEqual(n1, 1)
        two, _, n2 = scan(one, NOW + timedelta(minutes=45), FailedAPI())
        self.assertEqual(n2, 0)
        three, _, n3 = scan(two, NOW + timedelta(hours=4), FailedAPI())
        self.assertEqual(n3, 1)
        self.assertNotIn("stable_confirmations", three["matches"][GAME["match_key"]])
        self.assertNotIn("evidence_checked_at", three["matches"][GAME["match_key"]])

    def test_push_reconciliation_never_ages_evidence(self):
        prior = {"schema_version": 1, "matches": {
            GAME["match_key"]: {**GAME, "status": "PENDING", "attempts": 12,
                                "checked_at": "2026-10-28T17:00:00+00:00",
                                "provider_reasons": {"goal": "goal_no_core_match"}}}}
        untouched = copy.deepcopy(prior)
        ledger, _, n = scan(prior, NOW, None, checks=0)
        self.assertEqual(n, 0)
        row = ledger["matches"][GAME["match_key"]]
        for field in ("attempts", "checked_at", "provider_reasons"):
            self.assertEqual(row[field], untouched["matches"][GAME["match_key"]][field])
        self.assertNotIn("evidence_checked_at", row)

    def test_v7_retry_counts_evidence_not_legacy_invocations(self):
        self.assertEqual(retry_wait({"attempts": 12, "evidence_attempts": 2}),
                         timedelta(hours=4))
        self.assertEqual(retry_wait({"attempts": 12}),
                         timedelta(hours=24))  # legacy compatibility
        self.assertEqual(retry_wait({"evidence_attempts": 1, "stable_confirmations": 1}),
                         timedelta(hours=12))
        self.assertEqual(retry_wait({"evidence_attempts": 1, "stable_confirmations": 2}),
                         timedelta(hours=24))

    def test_backlog_does_not_claim_push_as_effective_check(self):
        previous = {"schema_version": 1, "matches": {
            GAME["match_key"]: {**GAME, "status": "PENDING", "attempts": 12,
                                "checked_at": "2026-10-28T17:00:00+00:00"}}}
        result = audit(previous, NOW, evidence_retry=True)
        self.assertEqual(result["classification"]["past_due_never_checked"], 1)
        game = result["overdue_games"][0]
        self.assertIsNone(game["last_checked_at"])
        self.assertEqual(game["legacy_last_checked_at"],
                         "2026-10-28T17:00:00+00:00")
        self.assertEqual(game["evidence_attempts"], 0)

    def test_watchdog_ignores_recent_push(self):
        runs = [{"created_at": "2026-10-28T19:58:00Z", "event": "push"},
                {"created_at": "2026-10-28T19:00:00Z", "event": "schedule"}]
        self.assertTrue(plan(runs, NOW)["dispatch"])
        runs[1]["created_at"] = "2026-10-28T19:50:00Z"
        self.assertFalse(plan(runs, NOW)["dispatch"])

    def test_goal_cap_is_persisted_and_checked(self):
        journal = {"schema_version": 1, "providers": {}, "usage": {
            "goal": {"2026-10-28": GOAL_DAILY_LIMIT-1}}}
        dates = choose_days([GAME["match_key"]],
                            {GAME["match_key"]: GAME},
                            journal, NOW, {"goal"})
        self.assertEqual(dates["goal"], ["2026-10-27"])
        updated = advance(journal, dates, {"goal": dates["goal"]}, NOW)
        self.assertEqual(updated["usage"]["goal"]["2026-10-28"], GOAL_DAILY_LIMIT)
        self.assertEqual(choose_days([GAME["match_key"]],
                            {GAME["match_key"]: GAME},
                            updated, NOW, {"goal"})["goal"], [])
        with self.assertRaises(ValueError):
            advance(journal, dates, {"goal": dates["goal"]}, NOW,
                    extra_requests={"goal": 1})


if __name__ == "__main__":
    unittest.main()
