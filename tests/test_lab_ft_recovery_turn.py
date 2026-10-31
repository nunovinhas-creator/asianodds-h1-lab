"""Regression: old API IDs can get one bounded turn; unproven GOAL cannot."""
import copy
import inspect
import unittest
from datetime import datetime, timedelta, timezone

from h1lab.lab_ft_recovery_turn import due, plan_exact_goal_ids, recovery_turn
from h1lab.lab_goal import GoalResults
from h1lab.lab_results import reconcile
from scripts import lab_results as producer

NOW = datetime(2026, 10, 31, 15, tzinfo=timezone.utc)
K = "2026-10-29,1,2"
ROW = {"match_key": K, "home": "FC Noah", "away": "Syunik",
       "status": "PENDING", "kickoff_utc": "2026-10-29T15:00:00+00:00",
       "lookup_source_version": 11,
       "queue_visited_at": "2026-10-31T08:41:23+00:00"}
C = {"provider": "goal", "provider_event_id": "858889",
     "provider_home": "Noah", "provider_away": "Syunik",
     "provider_competition": "Cup", "provider_kickoff_utc": ROW["kickoff_utc"],
     "last_seen_at": "2026-10-30T23:16:24+00:00",
     "reference_url": "https://api.goal-api.com/v1/fixtures/858889",
     "match_strength": "STRONG", "orientation": "SAME_ORDER",
     "review_only": True}


def review():
    return {"schema_version": 1, "games": [
        {**ROW, "possible_duplicates": [], "candidates": [dict(C)]}]}


def reconcile_run(previous, alerts, limit, **kwargs):
    return reconcile({"alerts": alerts}, [], previous, now=NOW,
                     max_checks=limit, evidence_retry=True,
                     bsd_lookup=lambda _: (None, "no_match"),
                     tsdb_lookup=lambda _: (None, "no_match"),
                     lookup_source_version=11, **kwargs)


class RecoveryTurnTests(unittest.TestCase):
    def test_historical_goal_candidate_is_diagnostic_only_even_if_exact(self):
        target = plan_exact_goal_ids({K: ROW}, review(), NOW)
        self.assertEqual(target[K]["provider_fixture_id"], "858889")
        self.assertNotIn("home_goals", target[K])
        with self.assertRaisesRegex(ValueError, "competition unproven"):
            recovery_turn({}, target, {K: ROW})

    def test_wrong_original_competition_never_activates_goal(self):
        # A valid same-provider ID, score, kickoff, team and league response
        # does not establish the original observed competition identity.
        observed = dict(ROW, competition="Italian Cup")
        provider = review()
        provider["games"][0]["observed_competition"] = "Kenyan Cup"
        target = plan_exact_goal_ids({K: observed}, provider, NOW)
        with self.assertRaisesRegex(ValueError, "competition unproven"):
            recovery_turn({}, target, {K: observed})
        self.assertNotIn("exact_targets", inspect.signature(GoalResults).parameters)

    def test_production_uses_api_only_and_existing_goal_review_path(self):
        src = inspect.getsource(producer)
        self.assertIn("recovery_turn(proposed_api, {}, existing['matches'])", src)
        self.assertNotIn("goal.exact_targets", src)
        self.assertNotIn("plan_exact_goal_ids", src)
        self.assertIn("plan_reviewed_goal_id", src)

    def test_one_turn_preserves_29_general_slots_and_preview_equals_real(self):
        alerts = [{**ROW, "match_key": str(i), "home": "Home " + str(i),
                   "away": "Away " + str(i),
                   "kickoff_utc": "2026-10-28T10:00:00Z"}
                  for i in range(35)] + [dict(ROW)]
        previous = {"schema_version": 1, "matches": {K: dict(ROW)}}
        _, baseline, _ = reconcile_run(previous, alerts, 30)
        self.assertNotIn(K, baseline["ft_queue"]["selected_keys"])
        old = recovery_turn({K: {"provider_fixture_id": 123}}, {},
                            previous["matches"])
        self.assertEqual(old, {K})
        _, preview, _ = reconcile_run(previous, alerts, 0, recovery_keys=old)
        _, current, count = reconcile_run(previous, alerts, 30, recovery_keys=old)
        chosen = current["ft_queue"]["selected_keys"]
        self.assertEqual(chosen[0], K)
        self.assertEqual(len(chosen), 30)
        self.assertEqual(count, 30)
        self.assertEqual(chosen, preview["ft_queue"]["deferred_keys"][:30])
        self.assertEqual(chosen[1:], baseline["ft_queue"]["selected_keys"][:29])
        self.assertEqual(current["ft_queue"]["old_id_recovery_turn"], [K])

    def test_no_forced_recheck_when_game_is_in_cooldown(self):
        previous = {"schema_version": 1,
                    "matches": {K: dict(ROW, queue_visited_at=NOW.isoformat())}}
        _, result, _ = reconcile_run(previous, [dict(ROW)], 30, recovery_keys={K})
        self.assertNotIn(K, result["ft_queue"]["selected_keys"])
        self.assertFalse(due(previous["matches"][K], NOW))

    def test_eligibility_and_input_budget_remain_bounded(self):
        for change in (
            {"status": "FINAL"},
            {"status": "SCORE_CONFLICT"},
            {"queue_visited_at": NOW.isoformat()},
            {"evidence_checked_at": (NOW-timedelta(minutes=5)).isoformat()},
            {"kickoff_utc": (NOW-timedelta(hours=23)).isoformat()}):
            with self.subTest(change=change):
                self.assertFalse(due(dict(ROW, **change), NOW))
        with self.assertRaises(ValueError):
            reconcile_run({"schema_version": 1, "matches": {K: ROW}},
                          [ROW], 30, recovery_keys={K, "other"})

    def test_old_id_attempt_rotation_never_modifies_history(self):
        rows = {K: dict(ROW, api_football_index_id_last_evidence={
                    "checked_at_utc": "2026-10-29T00:00:00Z"}),
                "second": dict(ROW, api_football_index_id_last_evidence={
                    "checked_at_utc": "2026-10-30T00:00:00Z"})}
        before = copy.deepcopy(rows)
        self.assertEqual(recovery_turn({K: {}, "second": {}}, {}, rows), {K})
        self.assertEqual(rows, before)
        rows[K]["api_football_index_id_last_evidence"]["checked_at_utc"] = NOW.isoformat()
        self.assertEqual(recovery_turn({K: {}, "second": {}}, {}, rows), {"second"})


if __name__ == "__main__":
    unittest.main()
