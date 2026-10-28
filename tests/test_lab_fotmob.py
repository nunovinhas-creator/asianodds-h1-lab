"""LAB FotMob adapter: isolated fixtures, no network, 90-min fail closed."""
import unittest
from datetime import datetime, timezone

from h1lab.lab_fotmob import FotMobResults, final_result, safe_candidate

S={"match_key":"2026-10-27,123,456","home":"CS Corvinul Hunedoara",
   "away":"AFC Rapid Bucureşti","kickoff_utc":"2026-10-27T13:00:00+00:00"}

def ev(*,eid=70001,home="Corvinul Hunedoara",away="Rapid București",
       h=0,a=0,label="FT",finished=True,when="2026-10-27T13:00:00.000Z"):
    return {"id":eid,"home":{"id":1001,"name":home,"score":h},
            "away":{"id":1002,"name":away,"score":a},
            "status":{"utcTime":when,"started":True,"finished":finished,
                      "cancelled":False,"reason":{"short":label},
                      "scoreStr":f"{h} - {a}"}}

class FotMobLabTests(unittest.TestCase):
    def test_core_names_and_regulation_ft(self):
        p=FotMobResults(fetch=lambda day:[ev()])
        res,reason=p.lookup(S)
        self.assertEqual(reason,"verified_fotmob_ft")
        self.assertEqual((res["home_goals"],res["away_goals"]),(0,0))
        self.assertEqual(res["identity_match"],"CORE_NAME")
        self.assertIn("matchId=70001",res["source"])
        self.assertEqual(p.lookup(S)[1],"verified_fotmob_ft")
        self.assertEqual(p.summary()["requests"],1)

    def test_kickoff_away_home_and_qualifiers(self):
        cases=[ev(home="Rapid București",away="Corvinul Hunedoara"),
               ev(home="Corvinul Hunedoara U21"),
               ev(when="2026-10-27T17:00:00Z")]
        for sample in cases:
            with self.subTest(sample=sample):
                result,why=FotMobResults(fetch=lambda day:[sample]).lookup(S)
                self.assertIsNone(result)
                self.assertNotEqual(why,"verified_fotmob_ft")

    def test_duplicate_and_reversed_always_block_even_if_exact_one(self):
        other=ev(eid=70002,home="CS Corvinul Hunedoara",away="AFC Rapid Bucureşti")
        duplicate=ev()
        for games in ([other,duplicate],
                      [other,ev(eid=70003,home="Rapid București",away="Corvinul Hunedoara")],
                      [other,ev(eid=70003,home="Corvinul Hunedoara",away="Other Team")]):
            with self.subTest(n=len(games)):
                result,why=FotMobResults(fetch=lambda day:games).lookup(S)
                self.assertIsNone(result)
                self.assertIn(why,("fotmob_ambiguous_club_or_fixture",
                                   "fotmob_reversed_order_candidate"))

    def test_knockout_penalties_et_and_ambiguous_final(self):
        for label in ("Pen","AET","After extra time","","Final",None):
            with self.subTest(label=label):
                result,why=FotMobResults(fetch=lambda day:[ev(label=label)]).lookup(S)
                self.assertIsNone(result)
                self.assertEqual(why,"fotmob_regulation_unverified")

    def test_invalid_scores_status_and_scorestr(self):
        cases=[ev(finished=False),ev(h=-1),ev(h=True),ev(eid="wrong"),
               ev(when="2026-10-26T08:00:00Z")]
        wrong=ev()
        wrong["status"]["scoreStr"]="8 - 4"
        cases.append(wrong)
        cancelled=ev()
        cancelled["status"]["cancelled"]=True
        cases.append(cancelled)
        for row in cases:
            with self.subTest(row=row):
                result,why=final_result(S,row,"CORE_NAME")
                self.assertIsNone(result)

    def test_budget_and_failure_cached_once(self):
        calls=[]
        def fetch(day):
            calls.append(day)
            raise OSError("unavailable")
        p=FotMobResults(fetch=fetch,max_days=1)
        self.assertEqual(p.lookup(S)[1],"fotmob_unavailable")
        self.assertEqual(p.lookup(S)[1],"fotmob_unavailable")
        self.assertEqual(len(calls),1)
        other=dict(S,kickoff_utc="2026-10-26T13:00:00+00:00")
        self.assertEqual(p.lookup(other)[1],"fotmob_day_budget_deferred")
        with self.assertRaises(ValueError):
            FotMobResults(max_days=4)

    def test_integration_does_not_settle_conflict_with_other_provider(self):
        from h1lab.lab_results import reconcile
        state={"alerts":[S],"signals":[]}
        other=lambda s:({"match_key":s["match_key"],"status":"final",
                         "home_goals":2,"away_goals":0,
                         "source":"https://example.org/other"},"verified")
        out, report, n = reconcile(state, [], {"schema_version":1,"matches":{}},
            now=datetime(2026,10,28,8,tzinfo=timezone.utc),
            bsd_lookup=other,tsdb_lookup=lambda s:(None,"no_event"),
            fotmob_lookup=FotMobResults(fetch=lambda day:[ev()]).lookup,
            max_checks=1)
        self.assertEqual(n,1)
        self.assertEqual(report["status_counts"].get("SCORE_CONFLICT"),1)
        self.assertNotIn("result",out["matches"][S["match_key"]])

if __name__=="__main__":
    unittest.main()
