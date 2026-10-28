"""Synthetic API-Football tests, no real HTTP or credentials."""
import unittest
from datetime import datetime,timezone
from h1lab.lab_api_football import APIFootballResults,_score

S={"match_key":"2026-10-27,44,55","home":"CS Corvinul Hunedoara",
   "away":"AFC Rapid Bucureşti","kickoff_utc":"2026-10-27T13:00:00+00:00"}

def game(eid=1000,home="Corvinul Hunedoara",away="Rapid București",
         h=0,a=0,status="FT",date="2026-10-27T13:00:00+00:00"):
    return {"fixture":{"id":eid,"date":date,"status":{"short":status}},
            "teams":{"home":{"id":33,"name":home},"away":{"id":44,"name":away}},
            "goals":{"home":h,"away":a},
            "score":{"fulltime":{"home":h,"away":a}}}

class APIResultsTests(unittest.TestCase):
    def test_not_configured_is_zero_requests(self):
        p=APIFootballResults(key="",fetch=lambda d,k: (_ for _ in ()).throw(AssertionError()))
        self.assertEqual(p.lookup(S)[1],"api_football_not_configured")
        self.assertEqual(p.requests,0)

    def test_ft_verified_once_by_unique_core_name(self):
        calls=[]
        def fetch(day,key):
            calls.append((day,key))
            return [game()]
        p=APIFootballResults(key="test-secret",fetch=fetch)
        r,reason=p.lookup(S)
        self.assertEqual(reason,"verified_api_football_ft")
        self.assertEqual(r["identity_match"],"CORE_NAME")
        self.assertEqual((r["home_goals"],r["away_goals"]),(0,0))
        self.assertEqual(p.lookup(S)[1],"verified_api_football_ft")
        self.assertEqual(calls,[("2026-10-27","test-secret")])
        self.assertEqual(p.summary()["verified_in_run"],2)

    def test_reject_pen_et_wrong_scores_and_invalid_ids(self):
        for ev in (game(status="PEN"),game(status="AET"),
                   game(status="NS"),game(eid=None)):
            self.assertIsNone(_score(S,ev,"CORE_NAME")[0])
        ev=game()
        ev["goals"]["away"]=2
        self.assertEqual(_score(S,ev,"CORE_NAME")[1],"api_football_score_conflict")

    def test_reversed_duplicate_or_wrong_qualifiers_block(self):
        sources=([game(home="Rapid București",away="Corvinul Hunedoara")],
                 [game(),game(eid=1001,home="CS Corvinul Hunedoara")],
                 [game(home="Corvinul Hunedoara U21")])
        for rows in sources:
            with self.subTest(rows=rows):
                p=APIFootballResults(key="test",fetch=lambda d,k:rows)
                self.assertIsNone(p.lookup(S)[0])

    def test_budget_and_cached_unavailability(self):
        calls=[]
        def fail(day,key):
            calls.append(day)
            raise OSError("unavailable")
        p=APIFootballResults(key="test",fetch=fail,max_days=1)
        self.assertEqual(p.lookup(S)[1],"api_football_unavailable")
        self.assertEqual(p.lookup(S)[1],"api_football_unavailable")
        other=dict(S,kickoff_utc="2026-10-26T13:00:00+00:00")
        self.assertEqual(p.lookup(other)[1],"api_football_day_budget_deferred")
        self.assertEqual(len(calls),1)
        with self.assertRaises(ValueError):
            APIFootballResults(key="test",max_days=4)

    def test_no_rewrite_of_preexisting_final(self):
        from h1lab.lab_results import reconcile
        st={"alerts":[S],"signals":[]}
        existing={"schema_version":1,"matches":{S["match_key"]:{
            "status":"FINAL","home":S["home"],"away":S["away"],
            "kickoff_utc":S["kickoff_utc"],"result":{"home_goals":1,
            "away_goals":0,"source":"https://example.org","evidence":"bsd_only"}}}}
        got,report,n=reconcile(st,[],existing,
            now=datetime(2026,10,28,8,tzinfo=timezone.utc),
            bsd_lookup=lambda s:(None,"missing"),tsdb_lookup=lambda s:(None,"missing"),
            api_football_lookup=APIFootballResults(key="test",
                fetch=lambda d,k: (_ for _ in ()).throw(AssertionError())).lookup)
        self.assertEqual(n,0)
        self.assertEqual(report["final_recorded"],1)
        self.assertEqual(got["matches"][S["match_key"]]["result"]["evidence"],"bsd_only")


if __name__=="__main__":
    unittest.main()
