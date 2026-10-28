"""Historical overdue reconciliation using documented normal-time evidence.

All providers are synthetic here. Never use full-time-plus-AET/penalty scores.
"""
import copy
import unittest
from datetime import datetime, timezone
from h1lab.lab_ft_reviewed_evidence import REVIEWED_PENDING_FT, verified_public_ft
from h1lab.lab_results import reconcile

NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
EXPECTED = {
    "2026-10-27,10030127,75": (1, 0),
    "2026-10-27,59193,10052416": (3, 2),
    "2026-10-27,23683,747": (0, 0),
    "2026-10-27,25153,62798": (4, 1),
    "2026-10-27,31960,1154": (1, 1),
    "2026-10-27,38744,1566": (0, 2),
    "2026-10-27,327,326": (2, 0),
    "2026-10-27,10068586,24722": (1, 0),
    "2026-10-27,10085234,32260": (2, 1),
    "2026-10-27,26873,26901": (3, 1),
    "2026-10-27,29242,53546": (0, 2),
    "2026-10-27,39759,696": (1, 1),
    "2026-10-28,30921,29839": (0, 0),
    "2026-10-28,50151,10045457": (3, 2),
    "2026-10-28,31269,31927": (0, 1),
    "2026-10-28,40595,28192": (1, 1),
    "2026-10-28,10055256,84215": (1, 1),
    "2026-10-28,33305,10030821": (1, 0),
    "2026-10-28,28717,61795": (2, 3),
    "2026-10-28,28720,24581": (0, 0),
    "2026-10-28,799,631": (1, 1),
    "2026-10-28,55219,22939": (1, 2),
    "2026-10-28,10012613,10074748": (3, 2),
    "2026-10-28,10038000,1142": (0, 1),
    "2026-10-28,95299,1092": (0, 2),
    "2026-10-28,35198,74459": (5, 0),
    "2026-10-28,28354,23552": (0, 1),
    "2026-10-28,36192,993": (1, 1),
}


def signal(key, row):
    return {"match_key": key, "home": row[0], "away": row[1], "kickoff_utc": row[2]}


def no_result(signal):
    return None, "no_match"


class OverdueFTTests(unittest.TestCase):
    def test_twenty_eight_exact_reviewed_scores_not_including_penalties_or_aet(self):
        self.assertEqual(set(REVIEWED_PENDING_FT), set(EXPECTED))
        for key, fixture in REVIEWED_PENDING_FT.items():
            with self.subTest(key=key):
                result, reason = verified_public_ft(signal(key, fixture))
                self.assertEqual((result["home_goals"], result["away_goals"]), EXPECTED[key])
                self.assertEqual(result["status"], "final")
                self.assertEqual(reason, "reviewed_two_independent_public_ft")

    def test_post_regulation_scenarios_keep_only_ninety_minutes(self):
        # Adana ended 2-1 after extra time; Teleoptik qualified on penalties.
        self.assertEqual(EXPECTED["2026-10-28,10055256,84215"], (1, 1))
        self.assertEqual(EXPECTED["2026-10-28,40595,28192"], (1, 1))
        # Kars 36 is NOT a generic alias for Karsspor (distinct clubs).
        self.assertNotIn("2026-10-28,29823,1748", REVIEWED_PENDING_FT)
        # Potential duplicate Eskisehir/Anadolu IDs must not be promoted.
        self.assertNotIn("2026-10-28,10088406,95346", REVIEWED_PENDING_FT)
        self.assertNotIn("2026-10-28,10055350,95346", REVIEWED_PENDING_FT)

    def test_nagoya_and_puszcza_require_ninety_minute_score(self):
        # These were won in extra time; final tournament scores were 1-2,
        # but the scientific and H1 FT means 90-minute regulation scores.
        self.assertEqual(EXPECTED["2026-10-28,799,631"], (1, 1))
        self.assertEqual(EXPECTED["2026-10-28,36192,993"], (1, 1))

    def test_ten_new_reviewed_games_have_two_distinct_public_hosts(self):
        from urllib.parse import urlparse
        keys = ["2026-10-28,28717,61795","2026-10-28,28720,24581","2026-10-28,799,631","2026-10-28,55219,22939","2026-10-28,10012613,10074748","2026-10-28,10038000,1142","2026-10-28,95299,1092","2026-10-28,35198,74459","2026-10-28,28354,23552","2026-10-28,36192,993"]
        for key in keys:
            with self.subTest(key=key):
                x = REVIEWED_PENDING_FT[key]
                self.assertNotEqual(urlparse(x[5]).netloc, urlparse(x[6]).netloc)
                self.assertEqual(x[2].split("T")[0], key.split(",")[0])

    def test_corrupted_identity_rejected_at_review_boundary(self):
        for key, fixture in REVIEWED_PENDING_FT.items():
            for field, value in (("home","Unknown Club"), ("away","Other Club"),
                                 ("kickoff_utc","2026-10-26T12:00:00+00:00"),
                                 ("match_key","2026-10-27,99,100")):
                with self.subTest(key=key, altered=field):
                    changed=signal(key,fixture)
                    changed[field]=value
                    self.assertIsNone(verified_public_ft(changed)[0])

    def test_twenty_eight_previously_pending_recovered_with_immutable_audit_urls(self):
        previous={"schema_version":1,"matches":{}}
        alerts=[]
        for key, row in REVIEWED_PENDING_FT.items():
            sig=signal(key,row)
            alerts.append(sig)
            previous["matches"][key]={
                **sig,"status":"PENDING","reason":"no_verified_ft_yet",
                "checked_at":"2026-10-28T11:07:45+00:00",
                "lookup_source_version":11,"attempts":3}
        original=copy.deepcopy(previous)
        ledger,report,attempted=reconcile({"alerts":alerts,"signals":[]},[],previous,
            now=NOW, bsd_lookup=no_result,tsdb_lookup=no_result,max_checks=30)
        self.assertEqual(attempted,28)
        self.assertEqual(report["final_recorded"],28)
        self.assertEqual(previous, original)
        for key, row in REVIEWED_PENDING_FT.items():
            resolved=ledger["matches"][key]
            self.assertEqual(resolved["status"],"FINAL")
            self.assertEqual((resolved["result"]["home_goals"],
                              resolved["result"]["away_goals"]), EXPECTED[key])
            self.assertEqual(resolved["result"]["evidence"],"reviewed_public_only")
            self.assertEqual(resolved["reviewed_public_resolution"]["corroboration_urls"],
                             list(row[5:7]))

    def test_conflicting_independent_provider_is_quarantined_not_silently_overwritten(self):
        key="2026-10-27,31960,1154"
        f=REVIEWED_PENDING_FT[key]
        sig=signal(key,f)
        previous={"schema_version":1,"matches":{key:{
            **sig,"status":"PENDING","checked_at":"2026-10-28T11:00:00+00:00",
            "lookup_source_version":11}}}
        def conflicting(_):
            return ({"match_key":key,"status":"final","home_goals":2,
                    "away_goals":2,"source":"https://example.org/final"}, "verified")
        ledger,report,attempted=reconcile(
            {"alerts":[sig],"signals":[]},[],previous,now=NOW,
            bsd_lookup=conflicting,tsdb_lookup=no_result,max_checks=30)
        self.assertEqual(attempted,1)
        self.assertEqual(ledger["matches"][key]["status"],"SCORE_CONFLICT")
        self.assertNotIn("result",ledger["matches"][key])
        self.assertEqual(report["final_recorded"],0)

    def test_new_or_confirmed_games_do_not_inherit_old_reviewed_scores(self):
        key="2026-10-27,25153,62798"
        f=REVIEWED_PENDING_FT[key]
        sig=signal(key,f)
        old={"schema_version":1,"matches":{key:{
            **sig,"status":"FINAL","result":{
                "home_goals":1,"away_goals":0,"source":"https://example.org/original",
                "evidence":"bsd_only"}}}}
        ledger,_,attempts=reconcile({"alerts":[sig],"signals":[]},[],old,now=NOW,
            bsd_lookup=no_result,tsdb_lookup=no_result,max_checks=30)
        self.assertEqual(attempts,0)
        self.assertEqual(ledger["matches"][key]["result"],old["matches"][key]["result"])
        # A new entry with the same match_key cannot bypass the historical
        # need for a prior PENDING ledger record.
        fresh,_,attempts=reconcile({"alerts":[sig],"signals":[]},[],
            {"schema_version":1,"matches":{}},now=NOW,
            bsd_lookup=no_result,tsdb_lookup=no_result,max_checks=30)
        self.assertEqual(attempts,1)
        self.assertEqual(fresh["matches"][key]["status"],"PENDING")


if __name__=="__main__":
    unittest.main()
