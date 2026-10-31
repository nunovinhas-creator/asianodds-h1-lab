"""FT rule: one validated provider, hard 24h expiry, immutable FINAL, no old retries."""
import unittest
from datetime import datetime, timedelta, timezone
from h1lab.lab_results import reconcile
from h1lab.lab_ft_backlog import audit

NOW = datetime(2026, 10, 31, 20, tzinfo=timezone.utc)

def signal(kickoff):
    return {"match_key": "2026-10-31,111,222", "home": "Home", "away": "Away",
            "kickoff_utc": kickoff.isoformat(), "event_id": "test:fixture", "h1": False}

def good(s):
    return ({"match_key": s["match_key"], "status": "final",
             "home_goals": 2, "away_goals": 1,
             "source": "https://example.org/verified-fixture"}, "ok")

def reconcile_one(s, *, now=NOW, previous=None, bsd=None, tsdb=None):
    return reconcile({"alerts": [s], "signals": []}, [],
                     previous or {"schema_version": 1, "matches": {}},
                     now=now, bsd_lookup=bsd or (lambda _: (None, "no_match")),
                     tsdb_lookup=tsdb or (lambda _: (None, "no_match")),
                     max_checks=30)

class TwentyFourHourFTPolicyTests(unittest.TestCase):
    def test_single_verified_provider_is_accepted(self):
        s=signal(NOW-timedelta(hours=4))
        ledger, report, attempts = reconcile_one(s, bsd=good)
        self.assertEqual(attempts, 1)
        self.assertEqual(report["final_recorded"], 1)
        self.assertEqual(ledger["matches"][s["match_key"]]["result"]["evidence"], "bsd_only")

    def test_24h_plus_one_second_expires_and_is_never_looked_up(self):
        s=signal(NOW-timedelta(hours=24, seconds=1))
        calls=[]
        def provider(value):
            calls.append(value)
            return good(value)
        ledger, report, attempts = reconcile_one(s,bsd=provider)
        self.assertEqual((attempts,calls),(0,[]))
        row=ledger["matches"][s["match_key"]]
        self.assertEqual(row["status"],"EXPIRED_UNVERIFIED")
        self.assertNotIn("provider_attempts", row)
        self.assertEqual(row["reason"], "ft_24h_window_elapsed")
        self.assertEqual(audit(ledger,NOW)["classification"]["closed_unverified"],1)
        later,_,again=reconcile_one(s,now=NOW+timedelta(days=3),
                                     previous=ledger,bsd=provider)
        self.assertEqual(again,0)
        self.assertEqual(later["matches"][s["match_key"]],row)

    def test_old_final_remains_immutable(self):
        s=signal(NOW-timedelta(hours=4))
        ledger,_,_=reconcile_one(s,bsd=good)
        later,report,attempts=reconcile_one(s,now=NOW+timedelta(days=5),previous=ledger)
        self.assertEqual(attempts,0)
        self.assertEqual(report["final_recorded"],1)
        self.assertEqual(later["matches"][s["match_key"]]["result"],
                         ledger["matches"][s["match_key"]]["result"])

    def test_provider_disagreement_is_not_accepted(self):
        s=signal(NOW-timedelta(hours=20))
        def conflict(v):
            doc,_=good(v)
            return ({**doc,"home_goals":0},"ok")
        ledger,report,_=reconcile_one(s,bsd=good,tsdb=conflict)
        self.assertEqual(report["status_counts"]["SCORE_CONFLICT"],1)
        later,_,attempts=reconcile_one(s,now=NOW+timedelta(hours=5),
                                        previous=ledger,bsd=good)
        self.assertEqual(attempts,0)
        self.assertEqual(later["matches"][s["match_key"]]["status"],"EXPIRED_UNVERIFIED")

if __name__=="__main__":
    unittest.main()
