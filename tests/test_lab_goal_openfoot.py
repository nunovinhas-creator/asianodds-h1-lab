"""Synthetic OpenFoot and GOAL FT validation; no external requests."""
import unittest
from datetime import datetime,timezone
from h1lab.lab_goal import GoalResults,verify as goal_verify
from h1lab.lab_openfoot import OpenFootResults,verify as open_verify

S={"match_key":"2026-10-27,44,55","home":"CS Corvinul Hunedoara",
   "away":"AFC Rapid Bucureşti","kickoff_utc":"2026-10-27T13:00:00+00:00"}

def go(status="FINISHED",ht="1",at="2",extra=None,pen=None,
       h="Corvinul Hunedoara",a="Rapid București",kick="2026-10-27T13:00:00Z",sid="748282"):
    return {"apiId":sid,"homeTeamName":h,"awayTeamName":a,
        "kickoffUtc":kick,"matchStatus":status,"matchPeriod":"FINISHED",
        "homeTeamFtScore":ht,"awayTeamFtScore":at,
        "homeTeamScore":ht,"awayTeamScore":at,
        "homeTeamExtraScore":extra,"awayTeamExtraScore":extra,
        "homeTeamPenaltyScore":pen,"awayTeamPenaltyScore":pen}

def op(status="finished",period="FT",h="Corvinul Hunedoara",a="Rapid București",
       hs=1,aw=2,kick="2026-10-27T13:00:00Z"):
    return {"id":"match_fmb_12345","competitionId":"comp_cupa_romaniei_ro",
        "homeTeam":{"id":"team_h","name":h},
        "awayTeam":{"id":"team_a","name":a},
        "kickoffAt":kick,"kickoffTimeKnown":True,
        "status":status,"period":period,"score":{"home":hs,"away":aw}}

class GoalAndOpenFootTests(unittest.TestCase):
    def test_goal_finished_and_core_identity(self):
        p=GoalResults("secret",getter=lambda day,key:[go()])
        result,why=p.lookup(S)
        self.assertEqual(why,"verified_goal_ft")
        self.assertEqual((result["home_goals"],result["away_goals"]),(1,2))
        self.assertEqual(result["identity_match"],"CORE_NAME")
        self.assertEqual(p.summary()["requests"],1)
        self.assertEqual(p.lookup(S)[1],"verified_goal_ft")
        self.assertEqual(p.summary()["requests"],1)

    def test_goal_after_pen_uses_ft_not_final(self):
        ev=go(status="AFTER_PEN",ht="1",at="1",pen="5")
        ev["homeTeamScore"]="3"
        ev["awayTeamScore"]="2"
        result,why=goal_verify(S,ev,"CORE_NAME")
        self.assertEqual(why,"verified_goal_ft_after_pen")
        self.assertEqual((result["home_goals"],result["away_goals"]),(1,1))

    def test_goal_after_extra_uses_ft(self):
        ev=go(status="AFTER_ET",ht="0",at="0",extra="1")
        ev["homeTeamScore"]="1"
        result,why=goal_verify(S,ev,"CORE_NAME")
        self.assertEqual(why,"verified_goal_ft_after_et")
        self.assertEqual((result["home_goals"],result["away_goals"]),(0,0))

    def test_goal_rejects_invalid_scores_and_ambiguous(self):
        for ev in (go(ht=None),go(ht=""),go(ht=True),go(status="LIVE"),
                   go(status="FINISHED",extra="1"),
                   go(status="AFTER_PEN"),go(status="AFTER_ET"),
                   go(h="Corvinul Hunedoara U21"),go(kick="2026-10-26T13:00:00Z")):
            with self.subTest(ev=ev):
                self.assertIsNone(GoalResults("key",getter=lambda d,k:[ev]).lookup(S)[0])
        self.assertIsNone(GoalResults("key",getter=lambda d,k:[go(),go(sid="748283")]).lookup(S)[0])
        self.assertIsNone(GoalResults("key",getter=lambda d,k:[go(h="Rapid București",a="Corvinul Hunedoara")]).lookup(S)[0])

    def test_goal_no_secret_budget(self):
        self.assertEqual(GoalResults().lookup(S)[1],"goal_not_configured")
        p=GoalResults("key",getter=lambda day,key:[],max_days=1)
        p.lookup(S)
        self.assertEqual(p.lookup(dict(S,kickoff_utc="2026-10-26T13:00:00+00:00"))[1],"goal_day_budget_deferred")
        with self.assertRaises(ValueError):
            GoalResults("key",max_days=4)

    def test_openfoot_ft(self):
        p=OpenFootResults("secret",getter=lambda day,key:[op()])
        result,why=p.lookup(S)
        self.assertEqual(why,"verified_openfoot_ft")
        self.assertEqual((result["home_goals"],result["away_goals"]),(1,2))
        self.assertEqual(p.summary()["requests"],1)

    def test_openfoot_rejects_et_unknown_or_identity_collisions(self):
        for ev in (op(period="AET"),op(period="PEN"),op(hs=None),
                   op(h="Corvinul Hunedoara U21"),op(kick="2026-10-28T15:00:00Z")):
            with self.subTest(ev=ev):
                self.assertIsNone(OpenFootResults("key",getter=lambda day,key:[ev]).lookup(S)[0])
        self.assertIsNone(OpenFootResults("key",getter=lambda d,k:[op(),op()]).lookup(S)[0])
        self.assertIsNone(OpenFootResults("key",getter=lambda d,k:[op(h="Rapid București",a="Corvinul Hunedoara")]).lookup(S)[0])

    def test_conflicting_providers_never_settle(self):
        from h1lab.lab_results import reconcile
        state={"alerts":[S],"signals":[]}
        got,report,n=reconcile(state,[],{"schema_version":1,"matches":{}},
            now=datetime(2026,10,28,14,tzinfo=timezone.utc),
            bsd_lookup=lambda s:(None,"missing"),
            tsdb_lookup=lambda s:(None,"missing"),
            goal_lookup=GoalResults("key",getter=lambda d,k:[go()]).lookup,
            openfoot_lookup=OpenFootResults("key",getter=lambda d,k:[op(hs=3)]).lookup,
            max_checks=1, lookup_source_version=11)
        self.assertEqual(n,1)
        self.assertEqual(got["matches"][S["match_key"]]["status"],"SCORE_CONFLICT")
        self.assertNotIn("result",got["matches"][S["match_key"]])

if __name__=="__main__":
    unittest.main()
