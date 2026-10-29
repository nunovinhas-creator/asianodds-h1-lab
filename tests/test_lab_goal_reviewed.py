"""Offline regression for reviewed GOAL identity-only fixture recovery."""
import copy
import unittest
from datetime import datetime, timezone

from h1lab.lab_goal import GoalResults
from h1lab.lab_goal_reviewed import plan_reviewed_goal_id, verify_reviewed_goal

NOW = datetime(2026, 10, 29, 20, tzinfo=timezone.utc)
KEY = "2026-10-27,77621,67110"
KO = "2026-10-27T18:00:00+00:00"
OBS = {"match_key": KEY, "home": "CA Independiente Reserves",
       "away": "CSyD Defensa y Justicia Reserves", "kickoff_utc": KO,
       "status": "PENDING"}
APPROVAL = dict(OBS, status="APPROVED_IDENTITY_ONLY", provider="goal",
                provider_fixture_id="834934", provider_home="Independiente Res.",
                provider_away="Defensa y Justicia Res.",
                provider_competition="Torneo Proyección",
                provider_kickoff_utc=KO, reviewed_at_utc="2026-10-29T09:59:33+00:00",
                reviewed_by="human-reviewed", score_gate="HOLD_FOR_OFFICIAL",
                api_football_anchor_id=1612137)
CAND = {"provider": "goal", "provider_event_id": "834934",
        "provider_home": "Independiente Res.",
        "provider_away": "Defensa y Justicia Res.",
        "provider_competition": "Torneo Proyección",
        "provider_kickoff_utc": KO, "match_strength": "STRONG",
        "orientation": "SAME_ORDER", "review_only": True}


def context():
    review = {"schema_version":1, "games":[
        dict(OBS, possible_duplicates=[], candidates=[dict(CAND)])]}
    goal = {"schema_version":1,"pairs":{KEY:dict(APPROVAL)}}
    api = {"schema_version":1,"pairs":{KEY:dict(OBS, provider="api_football",
               status="APPROVED", provider_fixture_id=1612137,
               competition_anchor_fixture_id=1612141)}}
    return {KEY:dict(OBS)}, review, goal, api


def plan(*, modify=None, selected=True):
    matches, review, goal, api = context()
    if modify:
        modify(matches, review, goal, api)
    decisions = {}
    outcome = plan_reviewed_goal_id([KEY] if selected else [], matches,
        review, goal, api, NOW, decisions=decisions)
    return outcome, decisions


def event():
    return {"apiId":"834934", "homeTeamName":"Independiente Res.",
            "awayTeamName":"Defensa y Justicia Res.",
            "kickoffUtc":"2026-10-27T18:00:00Z",
            "competition":{"name":"Torneo Proyección"},
            "matchStatus":"FINISHED","matchPeriod":"FINISHED",
            "homeTeamFtScore":"4","awayTeamFtScore":"1",
            "homeTeamScore":"4","awayTeamScore":"1"}


class ReviewedGoalTests(unittest.TestCase):
    def test_reviewed_pair_is_one_match_key_only_and_score_is_held(self):
        selected, decisions = plan()
        self.assertEqual(set(selected), {KEY})
        self.assertEqual(decisions[KEY]["status"], "ELIGIBLE_IDENTITY_ONLY")
        calls = []
        p = GoalResults("test", max_days=1, allowed_days=[KO[:10]],
            target_ids={KEY:"834934"}, reviewed_targets=selected,
            id_getter=lambda fixture,key:(calls.append(fixture) or event()),
            getter=lambda day,key:self.fail("No extra date requests"))
        result, reason = p.lookup(OBS)
        self.assertIsNone(result)
        self.assertEqual(reason, "goal_reviewed_ft_held_for_official")
        self.assertEqual(p.reviewed_observations[KEY]["home_goals"], 4)
        self.assertEqual(p.reviewed_observations[KEY]["away_goals"], 1)
        self.assertEqual(p.reviewed_observations[KEY]["status"],
            "PROVIDER_FT_AWAITING_OFFICIAL_CORROBORATION")
        self.assertEqual(calls, ["834934"])
        self.assertEqual(p.summary()["requests"], 1)
        self.assertEqual(p.summary()["date_requests"], 0)
        self.assertEqual(p.lookup(OBS)[1], "goal_id_budget_deferred")

    def test_unselected_or_missing_review_never_queries(self):
        self.assertEqual(plan(selected=False)[0], {})
        self.assertEqual(plan(modify=lambda m,r,g,a:g["pairs"].clear())[0], {})
        self.assertEqual(plan(modify=lambda m,r,g,a:a["pairs"].clear())[0], {})

    def test_other_weak_candidate_not_confirmed_collision(self):
        def weak(m,r,g,a):
            r["games"].append(dict(OBS,match_key="other",candidates=[
                dict(CAND,match_strength="WEAK_REVIEW_ONLY")],
                possible_duplicates=[]))
        self.assertIn(KEY,plan(modify=weak)[0])
        def strong(m,r,g,a):
            r["games"].append(dict(OBS,match_key="other",candidates=[dict(CAND)],
                possible_duplicates=[]))
        self.assertNotIn(KEY,plan(modify=strong)[0])

    def test_source_identity_and_categories_cannot_change(self):
        mutations = [
            lambda m,r,g,a:g["pairs"][KEY].update(provider_fixture_id="999999"),
            lambda m,r,g,a:g["pairs"][KEY].update(provider_home="Independiente"),
            lambda m,r,g,a:g["pairs"][KEY].update(provider_competition="Other League"),
            lambda m,r,g,a:g["pairs"][KEY].update(provider_kickoff_utc="2026-10-27T19:00:00Z"),
            lambda m,r,g,a:g["pairs"][KEY].update(status="CANDIDATE"),
            lambda m,r,g,a:g["pairs"][KEY].update(score_gate="AUTO_FINAL"),
            lambda m,r,g,a:a["pairs"][KEY].update(provider_fixture_id=55555),
            lambda m,r,g,a:r["games"][0].update(possible_duplicates=[{"match_key":"dup"}]),
            lambda m,r,g,a:m[KEY].update(home="CA Independiente U21"),
            lambda m,r,g,a:m[KEY].update(goal_id_last_attempt_at="2026-10-29T18:00:00+00:00"),
            lambda m,r,g,a:m.update({"confirmed":{"status":"FINAL","result":{
                "evidence":"goal_only","source":"https://api.goal-api.com/v1/fixtures/834934"}}}),
        ]
        for mut in mutations:
            with self.subTest(mut=str(mut)):
                self.assertNotIn(KEY, plan(modify=mut)[0])

    def test_invalid_goals_status_names_kickoff_and_competition_never_become_final(self):
        for field, val in [
            ("apiId","0"), ("matchStatus","LIVE"),("matchPeriod","SECOND_HALF"),
            ("homeTeamName","Independiente"),
            ("awayTeamName","Defensa y Justicia U21"),
            ("homeTeamFtScore",None),("homeTeamScore","3"),
            ("kickoffUtc","2026-10-27T20:00:00Z"),
            ("competition",{"name":"Senior Premier League"}),
        ]:
            with self.subTest(field=field):
                e=event()
                e[field]=val
                result,why,proof=verify_reviewed_goal(OBS,e,APPROVAL)
                self.assertIsNone(result)
                self.assertIsNone(proof)
                self.assertNotEqual(why,"goal_reviewed_ft_held_for_official")

    def test_id_errors_are_recorded_per_match_without_fake_ft(self):
        targets, _ = plan()
        def missing(_fixture, _key):
            raise OSError("transient provider issue")
        p = GoalResults("test",max_days=1,allowed_days=[],
            target_ids={KEY:"834934"},reviewed_targets=targets,id_getter=missing)
        found,reason = p.lookup(OBS)
        self.assertIsNone(found)
        self.assertEqual(reason,"goal_id_unavailable")
        self.assertEqual(p.id_outcomes[KEY],reason)
        self.assertEqual(p.summary()["id_outcomes"][KEY],reason)
        self.assertEqual(p.summary()["id_requests"],1)
        self.assertEqual(p.reviewed_observations,{})
        self.assertEqual(p.lookup(OBS)[1],"goal_id_budget_deferred")
        self.assertEqual(p.id_outcomes[KEY],"goal_id_unavailable")

        q = GoalResults("test",max_days=1,allowed_days=[],
            target_ids={KEY:"834934"},reviewed_targets=targets,
            id_getter=lambda fixture,key:dict(event(),apiId="999999"))
        self.assertEqual(q.lookup(OBS)[1],"goal_id_mismatch")
        self.assertEqual(q.id_outcomes[KEY],"goal_id_mismatch")
        self.assertFalse(q.reviewed_observations)

    def test_no_score_gate_can_produce_final(self):
        e=event()
        result,reason,proof=verify_reviewed_goal(OBS,e,dict(APPROVAL,score_gate="AUTO_FINAL"))
        self.assertIsNone(result)
        self.assertIsNone(proof)
        self.assertEqual(reason,"goal_reviewed_score_gate_invalid")


if __name__ == "__main__":
    unittest.main()
