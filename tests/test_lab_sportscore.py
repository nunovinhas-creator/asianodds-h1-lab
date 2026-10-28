"""SportScore integration safety checks: all provider responses synthetic."""
import unittest
from datetime import datetime,timezone
from h1lab.lab_sportscore import SportScoreResults, verified
from h1lab.lab_results import reconcile

SIG={"match_key":"2026-10-27,1,2","home":"Sporting CP","away":"CS Maritimo",
     "kickoff_utc":"2026-10-27T20:15:00+00:00"}


def fixture(status="finished",status_text="FT",home="Sporting CP",
            away="CS Maritimo",score=("2","0"),url="https://sportscore.com/football/sample"):
    return {"home":home,"away":away,"time":SIG["kickoff_utc"],
            "status":status,"status_text":status_text,
            "home_score":score[0],"away_score":score[1],"url":url}


class SportScoreTests(unittest.TestCase):
    def test_exact_score_with_evidence(self):
        s,r=verified(SIG,fixture(),"Portugal Primeira Liga")
        self.assertEqual(r,"verified_sportscore_ft")
        self.assertEqual((s["home_goals"],s["away_goals"]),(2,0))

    def test_no_fake_ft_from_extra_time_penalties_and_cups(self):
        for status_text in ("AET","After extra time","Penalties","ET 120","1st Half",""):
            score,reason=verified(SIG,fixture(status_text=status_text),"Portugal Taça da Liga")
            self.assertIsNone(score,reason)
        self.assertIsNone(verified(SIG,fixture(status_text="Finished"),"Portugal Taça da Liga")[0])
        self.assertIsNotNone(verified(SIG,fixture(status_text="FT"),"Portugal Taça da Liga")[0])

    def test_rejects_nonfinal_and_mismatched_names(self):
        for x in (fixture(status="live"),fixture(home="Sporting CP U23"),
                  fixture(away="Maritimo B"),fixture(score=("-1","1")),
                  fixture(score=("2.5","0")),fixture(url="http://evil.test/x"),
                  fixture(url="https://other.com/football/game")):
            self.assertIsNone(verified(SIG,x,"Portugal Primeira Liga")[0])

    def test_date_cache_and_targeted_resolution(self):
        calls=[]
        def getter(endpoint,params):
            calls.append((endpoint,dict(params)))
            if endpoint=="search/":return {"teams":[{"name":"Sporting CP","slug":"sporting-cp"}]}
            if params.get("team")=="sporting-cp":return {"matches":[fixture()]}
            return {"matches":[]}
        p=SportScoreResults({SIG["match_key"]:"Portugal Taça da Liga"},getter=getter)
        self.assertEqual(p.lookup(SIG)[1],"verified_sportscore_ft")
        self.assertEqual(p.lookup(SIG)[1],"verified_sportscore_ft")
        self.assertEqual(p.requests,3)
        self.assertEqual(p.targeted,1)
        self.assertEqual(p.summary()["confirmed_in_run"],2)

    def test_only_date_cache_can_settle(self):
        p=SportScoreResults({},getter=lambda endpoint,params:{"matches":[fixture()]})
        self.assertEqual(p.lookup(SIG)[1],"verified_sportscore_ft")
        self.assertEqual(p.requests,1)

    def test_no_slug_guessing(self):
        def get(endpoint,params):
            return {"teams":[{"name":"Sporting CP U21","slug":"sporting-cp"}]} if endpoint=="search/" else {"matches":[]}
        p=SportScoreResults({},getter=get)
        self.assertEqual(p.lookup(SIG)[1],"sportscore_no_exact_match")

    def test_multiple_same_match_is_ambiguous(self):
        p=SportScoreResults({},getter=lambda e,p:{"matches":[fixture(),fixture()]})
        self.assertEqual(p.lookup(SIG)[1],"sportscore_ambiguous")

    def test_budget_preserved(self):
        p=SportScoreResults({},getter=lambda e,p:{"matches":[]},
                             max_requests=1,max_team_searches=0)
        self.assertEqual(p.lookup(SIG)[1],"sportscore_no_exact_match")
        self.assertEqual(p.requests,1)
        with self.assertRaises(ValueError):
            SportScoreResults({},max_requests=61)
        with self.assertRaises(ValueError):
            SportScoreResults({},max_team_searches=31)

    def test_no_resolution_on_provider_failure(self):
        p=SportScoreResults({},getter=lambda e,p: (_ for _ in ()).throw(OSError("secret")))
        self.assertEqual(p.lookup(SIG)[1],"sportscore_unavailable")
        self.assertEqual(p.summary()["confirmed_in_run"],0)

    def test_four_way_conflict_never_final(self):
        st={"alerts":[SIG],"signals":[]}
        def good(s,h):
            return ({"match_key":s["match_key"],"status":"final","home_goals":h,
                    "away_goals":1,"source":"https://example.com/game"},"verified")
        ledger,report,_=reconcile(st,[],{"schema_version":1,"matches":{}},
            now=datetime(2026,10,28,7,tzinfo=timezone.utc),
            bsd_lookup=lambda s:good(s,1),
            tsdb_lookup=lambda s:good(s,1),
            espn_lookup=lambda s:good(s,1),
            sportscore_lookup=lambda s:good(s,2))
        self.assertEqual(report["final_recorded"],0)
        self.assertEqual(ledger["matches"][SIG["match_key"]]["status"],"SCORE_CONFLICT")

    def test_old_lab_ledger_gets_one_immediate_upgrade_check(self):
        st={"alerts":[SIG],"signals":[]}
        prior={"schema_version":1,"matches":{SIG["match_key"]:{
            "status":"PENDING","home":SIG["home"],"away":SIG["away"],
            "kickoff_utc":SIG["kickoff_utc"],"checked_at":"2026-10-28T06:00:00+00:00",
            "attempts":1,"reason":"no_verified_ft_yet"}}}
        calls=[]
        def fourth(signal):
            calls.append(signal["match_key"])
            return verified(signal,fixture(),"")
        first,report,attempts=reconcile(
            st,[],prior,now=datetime(2026,10,28,7,tzinfo=timezone.utc),
            bsd_lookup=lambda s:(None,"not_found"),
            tsdb_lookup=lambda s:(None,"not_found"),
            sportscore_lookup=fourth)
        self.assertEqual(attempts,1)
        self.assertEqual(report["final_recorded"],1)
        self.assertEqual(len(calls),1)
        self.assertEqual(first["matches"][SIG["match_key"]]["lookup_source_version"],5)

    def test_new_source_does_not_requery_in_cooldown(self):
        st={"alerts":[SIG],"signals":[]}
        old={"schema_version":1,"matches":{SIG["match_key"]:{
            "status":"PENDING","home":SIG["home"],"away":SIG["away"],
            "kickoff_utc":SIG["kickoff_utc"],"checked_at":"2026-10-28T06:00:00+00:00",
            "lookup_source_version":5,"attempts":2}}}
        def fail(s):
            raise AssertionError("Cooldown should suppress lookups")
        _,report,attempts=reconcile(st,[],old,
            now=datetime(2026,10,28,7,tzinfo=timezone.utc),
            bsd_lookup=fail,tsdb_lookup=fail,sportscore_lookup=fail)
        self.assertEqual(attempts,0)
        self.assertEqual(report["timing_counts"]["ELIGIBLE_COOLDOWN"],1)

    def test_fourth_source_alone_is_visible_but_labeled(self):
        st={"alerts":[SIG],"signals":[]}
        ledger,report,_=reconcile(st,[],{"schema_version":1,"matches":{}},
            now=datetime(2026,10,28,7,tzinfo=timezone.utc),
            bsd_lookup=lambda s:(None,"no_event"),tsdb_lookup=lambda s:(None,"no_event"),
            espn_lookup=lambda s:(None,"no_event"),
            sportscore_lookup=lambda s:verified(s,fixture(),""))
        self.assertEqual(report["final_recorded"],1)
        self.assertEqual(ledger["matches"][SIG["match_key"]]["result"]["evidence"],"sportscore_only")


if __name__=="__main__":
    unittest.main()
