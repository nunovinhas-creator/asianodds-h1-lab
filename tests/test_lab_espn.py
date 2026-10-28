"""Synthetic ESPN scoreboard checks; zero network traffic."""
import unittest
from datetime import datetime, timezone
from h1lab.lab_espn import ESPNResults, final_score, BASE
from h1lab.lab_results import reconcile
from scripts.lab_results import competitions_by_key, PacedTSDB


def sig():
    return {"match_key": "2026-10-27,100,200",
            "home": "Arsenal", "away": "Chelsea",
            "kickoff_utc": "2026-10-27T19:45:00+00:00"}


def event(*,home="Arsenal",away="Chelsea",hs="2",aw="1",
          typ="STATUS_FULL_TIME",desc="Full Time",completed=True,
          period=2,kickoff="2026-10-27T19:45:00Z"):
    return {"id": "401999999",
            "date": kickoff,
            "status": {"period":period,"type":{"name":typ,"description":desc,
                                              "detail":"FT" if desc=="Full Time" else desc,
                                              "completed":completed}},
            "competitions": [{"competitors":[
                {"homeAway":"home","score":hs,"team":{"displayName":home}},
                {"homeAway":"away","score":aw,"team":{"displayName":away}}]}]}


class ESPNTests(unittest.TestCase):
    def test_strict_regulation(self):
        result,reason=final_score(sig(),event(),"eng.1")
        self.assertEqual(reason,"verified_espn_ft")
        self.assertEqual((result["home_goals"],result["away_goals"]),(2,1))
        self.assertEqual(result["source"], BASE+"eng.1/summary?event=401999999")

    def test_rejects_et_penalties_and_unverified_final(self):
        for ev in (event(desc="After Extra Time"), event(desc="Penalty Shootout"),
                   event(typ="STATUS_FINAL",desc="Final"),
                   event(period=3),event(completed=False)):
            result,reason=final_score(sig(),ev,"eng.1")
            self.assertIsNone(result,reason)

    def test_rejects_similar_team_names_invalid_scores_and_time(self):
        for ev in (event(home="Arsenal U21"), event(away="Chelsea Women"),
                   event(hs="2.5"),event(hs="-1"),
                   event(kickoff="2026-10-26T19:45:00Z")):
            self.assertIsNone(final_score(sig(),ev,"eng.1")[0])

    def test_match_uniqueness_and_cache(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            return [event()]
        p=ESPNResults({sig()["match_key"]:"England League 1"},fetch=fetch,max_scoreboards=1)
        self.assertEqual(p.lookup(sig())[1],"espn_no_exact_match" if False else "verified_espn_ft")
        self.assertEqual(p.lookup(sig())[1],"verified_espn_ft")
        self.assertEqual(len(calls),1)
        self.assertEqual(p.summary()["confirmed_in_run"],2)

    def test_absent_competition_no_lookup(self):
        def fail(_):raise AssertionError("Must not request")
        p=ESPNResults({},fetch=fail)
        self.assertEqual(p.lookup(sig())[1],"espn_unsupported_competition")
        self.assertEqual(p.requests,0)

    def test_competition_conflicts_fail_closed(self):
        alerts=[{"match_key":"k","competition":"England League 1"},
                {"match_key":"k","competition":"Italy Serie A"}]
        self.assertNotIn("k",competitions_by_key(alerts))

    def test_ambiguous_same_teams_does_not_choose(self):
        p=ESPNResults({sig()["match_key"]:"England League 1"},
                      fetch=lambda url:[event(),event()])
        result,reason=p.lookup(sig())
        self.assertIsNone(result)
        self.assertEqual(reason,"espn_ambiguous_match")

    def test_scoreboard_budget_per_unique_league_day(self):
        p=ESPNResults({"k1":"England League 1","k2":"Italy Serie A"},
                      fetch=lambda url:[],max_scoreboards=1)
        s=sig()
        s1={**s,"match_key":"k1"}
        s2={**s,"match_key":"k2"}
        self.assertEqual(p.lookup(s1)[1],"espn_no_exact_match")
        self.assertEqual(p.lookup(s2)[1],"espn_budget_deferred")
        self.assertEqual(p.requests,1)

    def test_unavailable_cached_no_repeat(self):
        calls=[]
        def fail(url):
            calls.append(url)
            raise OSError("provider failed")
        p=ESPNResults({sig()["match_key"]:"England League 1"},fetch=fail)
        self.assertEqual(p.lookup(sig())[1],"espn_unavailable")
        self.assertEqual(p.lookup(sig())[1],"espn_unavailable")
        self.assertEqual(len(calls),1)

    def test_three_way_conflict_never_settled(self):
        state={"alerts":[{**sig(),"competition":"England League 1"}],"signals":[]}
        def valid(s,goals):
            return ({"match_key":s["match_key"],"status":"final",
                     "home_goals":goals,"away_goals":1,
                     "source":"https://example.com/event"},"verified")
        ledger,report,checked=reconcile(
            state,[],{"schema_version":1,"matches":{}},
            now=datetime(2026,10,28,7,tzinfo=timezone.utc),
            bsd_lookup=lambda s:valid(s,2),
            tsdb_lookup=lambda s:valid(s,2),
            espn_lookup=lambda s:valid(s,3))
        row=ledger["matches"][sig()["match_key"]]
        self.assertEqual(row["status"],"SCORE_CONFLICT")
        self.assertNotIn("result",row)
        self.assertEqual(report["final_recorded"],0)
        self.assertEqual(checked,1)

    def test_third_provider_only_can_settle(self):
        state={"alerts":[{**sig(),"competition":"England League 1"}],"signals":[]}
        def espn(s):
            return {"match_key":s["match_key"],"status":"final","home_goals":1,
                    "away_goals":0,"source":BASE+"eng.1/summary?event=123456"},"verified"
        ledger,report,_=reconcile(state,[],{"schema_version":1,"matches":{}},
           now=datetime(2026,10,28,7,tzinfo=timezone.utc),
           bsd_lookup=lambda s:(None,"no_match"),
           tsdb_lookup=lambda s:(None,"no_match"),espn_lookup=espn)
        self.assertEqual(report["final_recorded"],1)
        self.assertEqual(ledger["matches"][sig()["match_key"]]["result"]["evidence"],"espn_only")

    def test_timing_separates_future_from_missing(self):
        state={"alerts":[{**sig(),"kickoff_utc":"2026-10-30T19:45:00+00:00"}],"signals":[]}
        _,report,checked=reconcile(state,[],{"schema_version":1,"matches":{}},
            now=datetime(2026,10,28,7,tzinfo=timezone.utc),
            bsd_lookup=lambda s:(None,"no_match"),
            tsdb_lookup=lambda s:(None,"no_match"),max_checks=0)
        self.assertEqual(report["timing_counts"]["FUTURE"],1)
        self.assertEqual(checked,0)

    def test_tsdb_429_stops_api_requests(self):
        # Avoid any HTTP; validate only fail-stop behavior.
        p=PacedTSDB(interval=0)
        p.rate_limited=True
        self.assertEqual(p.lookup(sig())[1],"tsdb_limited_this_run")
        self.assertEqual(p.counts["requested"],0)


if __name__=="__main__":
    unittest.main()
