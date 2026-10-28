"""Real reviewed fixture-name pairs: no fuzzy runtime identities."""
import unittest
from datetime import datetime,timezone

from h1lab.lab_reviewed_aliases import SPORTSCORE_REVIEWED, reviewed_provider_pair
from h1lab.lab_sportscore import verified, SportScoreResults
from h1lab.lab_results import reconcile

def signal(key):
    item=SPORTSCORE_REVIEWED[key]
    return {"match_key":key,"home":item[0],"away":item[1],"kickoff_utc":item[2]}

def listing(key,status_text="Finished"):
    item=SPORTSCORE_REVIEWED[key]
    return {"home":item[3],"away":item[4],"time":item[2],
            "status":"finished","status_text":status_text,
            "home_score":"2","away_score":"1",
            "url":"https://sportscore.com/football/match/testing-"+key.split(",")[1]}

class ReviewedAliasTests(unittest.TestCase):
    def test_16_fixture_specific_source_name_pairs(self):
        self.assertEqual(len(SPORTSCORE_REVIEWED),16)
        for key in SPORTSCORE_REVIEWED:
            with self.subTest(key=key):
                self.assertEqual(reviewed_provider_pair(signal(key)),
                                 SPORTSCORE_REVIEWED[key][3:])

    def test_not_reused_with_other_key_teams_or_kickoff(self):
        key="2026-10-27,1734,1137"
        base=signal(key)
        for changed in ({**base,"match_key":"2026-10-27,999,888"},
                        {**base,"home":"Dinamo Zagreb B"},
                        {**base,"away":"Rijeka B"},
                        {**base,"kickoff_utc":"2026-10-28T17:00:00+00:00"}):
            self.assertIsNone(reviewed_provider_pair(changed))
            self.assertIsNone(verified(changed,listing(key),"Croatia Division 1 (HNL)")[0])

    def test_club_alias_validated_only_for_non_cup_ft(self):
        key="2026-10-27,1734,1137"
        result,reason=verified(signal(key),listing(key),"Croatia Division 1 (HNL)")
        self.assertIsNotNone(result)
        self.assertEqual(reason,"verified_sportscore_ft_reviewed_alias")
        self.assertEqual((result["home_goals"],result["away_goals"]),(2,1))

    def test_romanian_cupa_is_not_90min_without_ft_label(self):
        key="2026-10-27,95935,1688"
        self.assertEqual(verified(signal(key),listing(key),
                         "Romania Cupa Romaniei")[1],"cup_regulation_unverified")
        result,reason=verified(signal(key),listing(key,"FT"),
                         "Romania Cupa Romaniei")
        self.assertIsNotNone(result)
        self.assertEqual(reason,"verified_sportscore_ft_reviewed_alias")

    def test_kickoff_and_team_uniqueness_retained(self):
        key="2026-10-27,1367,1652"
        s=signal(key)
        bad={**listing(key),"time":"2026-10-27T20:10:00+00:00"}
        self.assertIsNone(verified(s,bad,"Slovenia 1. SNL")[0])
        p=SportScoreResults({key:"Slovenia 1. SNL"},
                            getter=lambda endpoint,params:{"matches":[listing(key),listing(key)]},
                            max_team_searches=0)
        self.assertEqual(p.lookup(s)[1],"sportscore_ambiguous")

    def test_recover_observed_ledger_fixture_and_do_not_repeat(self):
        key="2026-10-27,1734,1137"
        s=signal(key)
        state={"alerts":[s],"signals":[]}
        previous={"schema_version":1,"matches":{key:{
            "status":"PENDING","home":s["home"],"away":s["away"],
            "kickoff_utc":s["kickoff_utc"],"attempts":2,
            "lookup_source_version":4,
            "checked_at":"2026-10-28T07:00:00+00:00"}}}
        calls=[]
        def ss(sig):
            calls.append(sig["match_key"])
            return verified(sig,listing(key),"Croatia Division 1 (HNL)")
        t=datetime(2026,10,28,8,tzinfo=timezone.utc)
        nxt,report,queried=reconcile(state,[],previous,now=t,
            bsd_lookup=lambda s:(None,"no_match"),
            tsdb_lookup=lambda s:(None,"no_match"),
            sportscore_lookup=ss)
        self.assertEqual(queried,1)
        self.assertEqual(len(calls),1)
        self.assertEqual(report["final_recorded"],1)
        self.assertEqual(nxt["matches"][key]["result"]["evidence"],"sportscore_only")
        self.assertEqual(nxt["matches"][key]["reviewed_alias_check_version"],1)
        third,_,checked=reconcile(state,[],nxt,now=t,
            bsd_lookup=lambda s: (_ for _ in ()).throw(AssertionError("repeated")),
            tsdb_lookup=lambda s: (_ for _ in ()).throw(AssertionError("repeated")),
            sportscore_lookup=ss)
        self.assertEqual(checked,0)
        self.assertEqual(third,nxt)

    def test_first_checks_before_reviewed_alias_when_budget_one(self):
        key="2026-10-27,1734,1137"
        other={"match_key":"2026-10-27,1,2","home":"Sample","away":"Other",
               "kickoff_utc":"2026-10-27T17:00:00+00:00"}
        st={"alerts":[other,signal(key)],"signals":[]}
        prior={"schema_version":1,"matches":{}}
        seen=[]
        def no(s):
            seen.append(s["match_key"])
            return None,"no_match"
        _,_,checked=reconcile(st,[],prior,
            now=datetime(2026,10,28,8,tzinfo=timezone.utc),
            bsd_lookup=no,tsdb_lookup=lambda s:(None,"none"),max_checks=1)
        self.assertEqual(checked,1)
        self.assertEqual(seen,[other['match_key']])

if __name__ == "__main__":
    unittest.main()
