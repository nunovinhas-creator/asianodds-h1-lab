"""No-network regression tests for quota-neutral GOAL ID recovery."""
import unittest
from datetime import datetime, timezone
from h1lab.lab_goal_id_probe import plan_goal_id
from h1lab.lab_goal import GoalResults
from h1lab.lab_ft_rotation import advance

NOW = datetime(2026, 10, 29, 1, tzinfo=timezone.utc)
KEY = "2026-10-28,100,200"
MATCH = {"match_key":KEY,"home":"Egersund IK","away":"Bryne FK",
         "kickoff_utc":"2026-10-28T17:00:00+00:00",
         "status":"PENDING","checked_at":"2026-10-28T20:00:00+00:00",
         "provider_reasons":{"goal":"goal_no_regulation_score"}}


def candidate(event_id="857151",home="Egersund",away="Bryne"):
    return {"provider":"goal","provider_event_id":event_id,
            "provider_home":home,"provider_away":away,
            "provider_kickoff_utc":MATCH["kickoff_utc"],
            "orientation":"SAME_ORDER","review_only":True}


def review():
    return {"schema_version":1,"games":[{
        "match_key":KEY,"home":MATCH["home"],"away":MATCH["away"],
        "kickoff_utc":MATCH["kickoff_utc"],"possible_duplicates":[],
        "candidates":[candidate()]}]}


def event(status="FINISHED",home="Egersund",away="Bryne",ht="2",at="1"):
    return {"apiId":"857151","homeTeamName":home,"awayTeamName":away,
            "kickoffUtc":"2026-10-28T17:00:00Z",
            "matchStatus":status,"matchPeriod":"FINISHED",
            "homeTeamFtScore":ht,"awayTeamFtScore":at,
            "homeTeamScore":ht,"awayTeamScore":at}


class GoalIDProbeTests(unittest.TestCase):
    def test_only_selected_unique_verified_name_and_kickoff(self):
        self.assertEqual(plan_goal_id([KEY],{KEY:MATCH},review(),NOW),{KEY:"857151"})
        self.assertEqual(plan_goal_id([],{KEY:MATCH},review(),NOW),{})
        wrong=review()
        wrong["games"][0]["candidates"][0]["provider_home"]="Different Club"
        self.assertEqual(plan_goal_id([KEY],{KEY:MATCH},wrong,NOW),{})
        wrong=review()
        wrong["games"][0]["possible_duplicates"]=[{"match_key":"OTHER"}]
        self.assertEqual(plan_goal_id([KEY],{KEY:MATCH},wrong,NOW),{})
        wrong=review()
        wrong["games"][0]["candidates"][0]["provider_kickoff_utc"]="2026-10-28T17:06:00Z"
        self.assertEqual(plan_goal_id([KEY],{KEY:MATCH},wrong,NOW),{})
        wrong=review()
        wrong["games"].append(dict(wrong["games"][0],match_key="other"))
        self.assertEqual(plan_goal_id([KEY],{KEY:MATCH},wrong,NOW),{})

    def test_four_hours_and_current_identity_must_match(self):
        early=datetime(2026,10,28,22,tzinfo=timezone.utc)
        self.assertEqual(plan_goal_id([KEY],{KEY:MATCH},review(),early),{})
        changed={**MATCH,"away":"Other Side"}
        self.assertEqual(plan_goal_id([KEY],{KEY:changed},review(),NOW),{})

    def test_id_result_must_pass_regulation_validator(self):
        p=GoalResults("key",getter=lambda d,k:[],
                      allowed_days=["2026-10-28"],max_days=1,
                      target_ids={KEY:"857151"},
                      id_getter=lambda event_id,key:event())
        result,why=p.lookup(MATCH)
        self.assertEqual(why,"verified_goal_ft")
        self.assertEqual((result["home_goals"],result["away_goals"]),(2,1))
        self.assertEqual(p.summary()["requests"],1)
        self.assertEqual(p.summary()["id_requests"],1)
        self.assertEqual(p.summary()["date_requests"],0)
        self.assertEqual(p.lookup(MATCH)[1],"goal_id_budget_deferred")

    def test_id_is_not_evidence_when_identity_or_score_is_invalid(self):
        for response in (event(home="Wrong Team"),event(status="LIVE"),
                         event(ht=None),event(away="Bryne Women"),
                         event(at="7",ht="0")):
            with self.subTest(response=response):
                p=GoalResults("secret",allowed_days=[],max_days=0,
                              target_ids={KEY:"857151"},
                              id_getter=lambda _,__:response)
                # Zero date slots do not disable a single substituted ID slot.
                found,why=p.lookup(MATCH)
                if response.get("homeTeamFtScore")=="0":
                    # The validator may accept an unusual but valid final score.
                    self.assertEqual(why,"verified_goal_ft")
                else:
                    self.assertIsNone(found)
        p=GoalResults("key",allowed_days=[],max_days=0,target_ids={KEY:"857151"},
                      id_getter=lambda i,k:dict(event(),apiId="999999"))
        self.assertEqual(p.lookup(MATCH)[1],"goal_id_mismatch")

    def test_actual_goal_evidence_survives_a_later_rotation_deferral(self):
        from h1lab.lab_results import reconcile
        state={"alerts":[{k:MATCH[k] for k in
                          ("match_key","home","away","kickoff_utc")}],"signals":[]}
        no=lambda signal:(None,"no_match")
        t1=datetime(2026,10,28,20,30,tzinfo=timezone.utc)
        t2=datetime(2026,10,29,1,0,tzinfo=timezone.utc)
        first,_,n=reconcile(state,[],{"schema_version":1,"matches":{}},
                            now=t1,bsd_lookup=no,tsdb_lookup=no,
                            goal_lookup=lambda s:(None,"goal_no_regulation_score"),
                            max_checks=30)
        self.assertEqual(n,1)
        self.assertEqual(first["matches"][KEY]["goal_ft_last_evidence"]["reason"],
                         "goal_no_regulation_score")
        second,_,n=reconcile(state,[],first,now=t2,bsd_lookup=no,tsdb_lookup=no,
                             goal_lookup=lambda s:(None,"goal_day_rotation_deferred"),
                             max_checks=30)
        self.assertEqual(n,1)
        row=second["matches"][KEY]
        self.assertEqual(row["provider_reasons"]["goal"],"goal_day_rotation_deferred")
        self.assertEqual(row["goal_ft_last_evidence"]["reason"],"goal_no_regulation_score")
        t3=datetime(2026,10,29,5,30,tzinfo=timezone.utc)
        self.assertEqual(plan_goal_id([KEY],second["matches"],review(),t3),{KEY:"857151"})
        changed={"alerts":[{**state["alerts"][0],"home":"Other Club"}],"signals":[]}
        altered,_,_=reconcile(changed,[],second,now=t3,bsd_lookup=no,tsdb_lookup=no,
                              max_checks=0)
        self.assertNotIn("goal_ft_last_evidence",altered["matches"][KEY])
        self.assertEqual(plan_goal_id([KEY],altered["matches"],review(),t3),{})

    def test_id_probe_24h_cooldown_and_confirmed_id_exclusivity(self):
        recent={**MATCH,"goal_id_last_attempt_at":"2026-10-28T23:00:00+00:00"}
        self.assertEqual(plan_goal_id([KEY],{KEY:recent},review(),NOW),{})
        final={"status":"FINAL","home":"Other","away":"Other Away",
               "kickoff_utc":"2026-10-28T17:00:00+00:00",
               "result":{"evidence":"goal_only",
                         "source":"https://api.goal-api.com/v1/fixtures/857151"}}
        self.assertEqual(plan_goal_id([KEY],{KEY:MATCH,"other":final},review(),NOW),{})

    def test_two_call_ceiling_and_journal_counts_target(self):
        p=GoalResults("key",getter=lambda d,k:[],max_days=1,
                      allowed_days=["2026-10-28"],
                      target_ids={KEY:"857151"},
                      id_getter=lambda i,k:event())
        p.lookup(MATCH)
        p.lookup(dict(MATCH,match_key="other"))
        self.assertEqual(p.summary()["requests"],2)
        self.assertEqual(p.summary()["id_requests"],1)
        with self.assertRaises(ValueError):
            advance({"schema_version":1,"providers":{}},
                    {"goal":["2026-10-28"]},
                    {"goal":["2026-10-28"]},NOW,extra_requests={"goal":2})
        journal=advance({"schema_version":1,"providers":{}},
                        {"goal":["2026-10-28"]},
                        {"goal":["2026-10-28"]},NOW,extra_requests={"goal":1})
        self.assertEqual(journal["usage"]["goal"]["2026-10-29"],2)


if __name__=="__main__":
    unittest.main()
