"""Historical overdue reconciliation using documented normal-time evidence.

All providers are synthetic here. Never use full-time-plus-AET/penalty scores.
"""
import copy
import unittest
from datetime import datetime, timezone
from h1lab.lab_ft_reviewed_evidence import REVIEWED_PENDING_FT, verified_public_ft
from h1lab.lab_results import reconcile

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
EXPECTED = {
    "2026-10-27,23683,747": (0, 0),
    "2026-10-27,25153,62798": (4, 1),
    "2026-10-27,31960,1154": (1, 1),
    "2026-10-27,38744,1566": (0, 2),
    "2026-10-27,327,326": (2, 0),
}


def signal(key, row):
    return {"match_key": key, "home": row[0], "away": row[1], "kickoff_utc": row[2]}


def no_result(signal):
    return None, "no_match"


class OverdueFTTests(unittest.TestCase):
    def test_five_exact_reviewed_scores_not_including_penalties_or_aet(self):
        self.assertEqual(set(REVIEWED_PENDING_FT), set(EXPECTED))
        for key, fixture in REVIEWED_PENDING_FT.items():
            with self.subTest(key=key):
                result, reason = verified_public_ft(signal(key, fixture))
                self.assertEqual((result["home_goals"], result["away_goals"]), EXPECTED[key])
                self.assertEqual(result["status"], "final")
                self.assertEqual(reason, "reviewed_two_independent_public_ft")

    def test_corrupted_identity_rejected_at_review_boundary(self):
        for key, fixture in REVIEWED_PENDING_FT.items():
            for field, value in (("home","Unknown Club"), ("away","Other Club"),
                                 ("kickoff_utc","2026-10-26T12:00:00+00:00"),
                                 ("match_key","2026-10-27,99,100")):
                with self.subTest(key=key, altered=field):
                    changed=signal(key,fixture)
                    changed[field]=value
                    self.assertIsNone(verified_public_ft(changed)[0])

    def test_five_previously_pending_recovered_with_immutable_audit_urls(self):
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
        self.assertEqual(attempted,5)
        self.assertEqual(report["final_recorded"],5)
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
