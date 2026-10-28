"""Factual integrity: source match URL cannot contradict home-away scoring."""
import unittest
from datetime import datetime,timezone

from h1lab.lab_sportscore import verified, source_order_conflict
from h1lab.lab_reviewed_aliases import SPORTSCORE_REVIEWED
from h1lab.lab_results import reconcile

K1="2026-10-27,10102013,10048381"
K2="2026-10-27,70933,35866"
REVERSED_1="https://sportscore.com/football/match/albion-fc-reserves-vs-montevideo-city-torque-reserves/2y8m4zhv34gyql0/"
REVERSED_2="https://sportscore.com/football/match/fc-dobrudzha-dobrich-vs-ludogorets-razgrad-ii/dn1m1ghlzylzmoe/"

def signal(key):
    row=SPORTSCORE_REVIEWED[key]
    return {"match_key":key,"home":row[0],"away":row[1],"kickoff_utc":row[2]}

def listing(key,url):
    row=SPORTSCORE_REVIEWED[key]
    return {"home":row[3],"away":row[4],"time":row[2],"status":"finished",
            "status_text":"Finished","home_score":"4","away_score":"0","url":url}

class SourceOrderTests(unittest.TestCase):
    def test_real_reversed_provider_urls_rejected(self):
        for key,url in ((K1,REVERSED_1),(K2,REVERSED_2)):
            with self.subTest(key=key):
                a=SPORTSCORE_REVIEWED[key]
                self.assertTrue(source_order_conflict(url,a[3],a[4]))
                result,reason=verified(signal(key),listing(key,url),"Uruguay Reserve League")
                self.assertIsNone(result)
                self.assertEqual(reason,"source_home_away_conflict")

    def test_proper_order_remains_valid(self):
        key="2026-10-27,1734,1137"
        url="https://sportscore.com/football/match/dinamo-zagreb-vs-rijeka/ednm9whwl60pryo/"
        a=SPORTSCORE_REVIEWED[key]
        self.assertFalse(source_order_conflict(url,a[3],a[4]))
        result,reason=verified(signal(key),listing(key,url),"Croatia Division 1 (HNL)")
        self.assertIsNotNone(result)
        self.assertEqual(reason,"verified_sportscore_ft_reviewed_alias")

    def test_unrelated_or_unparseable_url_never_assumed_reversed(self):
        for url in ("https://sportscore.com/x","https://evil.com/football/match/away-vs-home/123",
                    "https://sportscore.com/football/match/unknown-vs-other/123"):
            self.assertFalse(source_order_conflict(url,"Home","Away"))

    def test_existing_reversed_final_removed_from_ledger(self):
        for key,url in ((K1,REVERSED_1),(K2,REVERSED_2)):
            with self.subTest(key=key):
                s=signal(key)
                previous={"schema_version":1,"matches":{key:{
                    "status":"FINAL","home":s["home"],"away":s["away"],
                    "kickoff_utc":s["kickoff_utc"],"checked_at":"2026-10-28T08:09:07+00:00",
                    "result":{"home_goals":4,"away_goals":0,"evidence":"sportscore_only",
                              "source":url}}}}
                def no(_):
                    raise AssertionError("Do not automatically settle quarantined match")
                updated,report,checked=reconcile(
                    {"alerts":[s],"signals":[]},[],previous,
                    now=datetime(2026,10,28,9,tzinfo=timezone.utc),
                    bsd_lookup=no,tsdb_lookup=no,max_checks=30)
                row=updated["matches"][key]
                self.assertEqual(row["status"],"SOURCE_ORDER_CONFLICT")
                self.assertNotIn("result",row)
                self.assertEqual(checked,0)
                self.assertEqual(report["final_recorded"],0)
                self.assertEqual(report["timing_counts"]["BLOCKED_REVIEW"],1)

    def test_existing_valid_final_is_preserved(self):
        key="2026-10-27,1734,1137"
        s=signal(key)
        previous={"schema_version":1,"matches":{key:{
            "status":"FINAL","home":s["home"],"away":s["away"],
            "kickoff_utc":s["kickoff_utc"],
            "result":{"home_goals":2,"away_goals":1,"evidence":"sportscore_only",
                      "source":"https://sportscore.com/football/match/dinamo-zagreb-vs-rijeka/ednm9whwl60pryo/"}}}}
        updated,report,checked=reconcile({"alerts":[s],"signals":[]},[],previous,
            now=datetime(2026,10,28,9,tzinfo=timezone.utc),
            bsd_lookup=lambda x:(None,"no_match"),
            tsdb_lookup=lambda x:(None,"no_match"))
        self.assertEqual(checked,0)
        self.assertEqual(report["final_recorded"],1)
        self.assertEqual(updated["matches"][key]["status"],"FINAL")

if __name__=="__main__":
    unittest.main()
