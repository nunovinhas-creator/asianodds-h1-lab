"""Monte-Carlos read-only BSD ID crosswalk, synthetic SQLite + network mocks."""
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime,timezone

from h1lab.bsd import ROOT, BSDProviderError
from h1lab.lab_monte_bsd import (MonteBSDCrosswalk,exact_catalog,
                                 validated_result,_goals,_status,_redirect)

SIGNAL={"match_key":"2026-10-27,alpha,beta",
        "home":"Dinamo Zagreb","away":"Rijeka",
        "kickoff_utc":"2026-10-27T17:00:00+00:00"}
TIMESTAMP=int(datetime(2026,10,27,17,tzinfo=timezone.utc).timestamp())

def database(fixtures=None):
    fixtures=fixtures if fixtures is not None else [
        ("600100","Dinamo Zagreb","Rijeka",TIMESTAMP)]
    with tempfile.NamedTemporaryFile(suffix=".db",delete=False) as f:
        name=f.name
    try:
        c=sqlite3.connect(name)
        c.execute("CREATE TABLE predictions(match_id TEXT PRIMARY KEY,home_team TEXT,away_team TEXT,timestamp INTEGER)")
        c.executemany("INSERT INTO predictions VALUES(?,?,?,?)",fixtures)
        c.commit()
        c.close()
        with open(name,"rb") as f:return f.read()
    finally:
        os.unlink(name)

def event(eid=600100,status="finished",hs=2,aw=1,home="Dinamo Zagreb",away="Rijeka"):
    return {"id":eid,"status":status,"home_team":{"name":home},
            "away_team":{"name":away},"event_date":"2026-10-27T17:00:00+00:00",
            "home_score":hs,"away_score":aw}

class MonteBSDTests(unittest.TestCase):
    def test_public_sqlite_fixture_yields_strict_bsd_event_id(self):
        raw=database()
        idx=exact_catalog(raw)
        self.assertEqual(len(idx),1)
        self.assertEqual(idx[("dinamo zagreb","rijeka","2026-10-27")][0][0],600100)
        calls=[]
        def api(url,token):
            self.assertEqual(token,"test-key")
            calls.append(url)
            return event()
        finder=MonteBSDCrosswalk(token="test-key",downloader=lambda:raw,fetch=api,
                                  sleep=lambda t:None)
        result,reason=finder.lookup(SIGNAL)
        self.assertEqual(reason,"verified_bsd_ft_from_monte_id")
        self.assertEqual(result["home_goals"],2)
        self.assertEqual(result["away_goals"],1)
        self.assertEqual(calls,[ROOT+"600100/"])
        self.assertEqual(finder.summary()["exact_event_id_candidates"],1)
        self.assertEqual(finder.summary()["archive_status"],"read_only_loaded")
        self.assertEqual(finder.summary()["verified_in_run"],1)
        self.assertEqual(result["source"],ROOT+"600100/")

    def test_crosswalk_never_assumes_asianodds_match_key_is_bsd_id(self):
        raw=database()
        finder=MonteBSDCrosswalk(token="test",downloader=lambda:raw,
            fetch=lambda u,t: (_ for _ in ()).throw(AssertionError("No direct guessed ID")))
        other={**SIGNAL,"home":"Dinamo Zagreb Reserves"}
        result,why=finder.lookup(other)
        self.assertIsNone(result)
        self.assertEqual(why,"monte_no_exact_archive_match")

    def test_no_score_from_archive_without_live_bsd(self):
        raw=database()
        finder=MonteBSDCrosswalk(token="test",downloader=lambda:raw,
            fetch=lambda u,t: (_ for _ in ()).throw(BSDProviderError("BSD HTTP 502")))
        result,why=finder.lookup(SIGNAL)
        self.assertIsNone(result)
        self.assertEqual(why,"monte_bsd_provider_unavailable")

    def test_follow_replaced_by_only_after_event_detail_and_revalidate(self):
        raw=database()
        calls=[]
        def fetch(url,token):
            calls.append(url)
            if url==ROOT+"600100/":
                return {"data":event(status="postponed",hs=None,aw=None)
                        | {"replaced_by":{"id":600101}}}
            return {"result":event(eid=600101,hs="3",aw="2")}
        f=MonteBSDCrosswalk(token="test",downloader=lambda:raw,fetch=fetch)
        result,why=f.lookup(SIGNAL)
        self.assertEqual(why,"verified_bsd_ft_from_monte_id")
        self.assertEqual(result["source"],ROOT+"600101/")
        self.assertEqual((result["home_goals"],result["away_goals"]),(3,2))
        self.assertEqual(len(calls),2)

    def test_replaced_by_cycle_blocks_result(self):
        def fetch(url,token):
            eid=int(url.rstrip("/").split("/")[-1])
            return {"data":event(eid=eid)|{"replaced_by":600101 if eid==600100 else 600100}}
        f=MonteBSDCrosswalk(token="test",downloader=database,fetch=fetch)
        result,why=f.lookup(SIGNAL)
        self.assertIsNone(result)
        self.assertEqual(why,"monte_replaced_by_cycle")

    def test_extra_time_and_ambiguous_scores_never_settle(self):
        for obj in (event(status="after extra time"),
                    event(status="AET"),
                    event(hs="-1"),
                    event(hs=True),
                    event(home="Other Club"),
                    event(status="postponed")):
            self.assertIsNone(validated_result(SIGNAL,obj)[0])

    def test_nested_explicit_fulltime_score_but_no_generic_et_score(self):
        x=event()
        x.pop("home_score");x.pop("away_score")
        x["scores"]={"fulltime":{"home":"3","away":"0"}}
        self.assertEqual(_goals(x),(3,0))
        y=event()
        y.pop("home_score");y.pop("away_score")
        y["score"]={"home":5,"away":4}
        self.assertIsNone(_goals(y))

    def test_duplicate_matching_ids_fail_closed(self):
        raw=database([("600100","Dinamo Zagreb","Rijeka",TIMESTAMP),
                      ("600101","Dinamo Zagreb","Rijeka",TIMESTAMP)])
        f=MonteBSDCrosswalk(token="test",downloader=lambda:raw,
            fetch=lambda u,t: (_ for _ in ()).throw(AssertionError("Must not guess")))
        self.assertEqual(f.lookup(SIGNAL)[1],"monte_ambiguous_archive_match")

    def test_changed_kickoff_or_away_club_cannot_correlate(self):
        raw=database()
        for sig in ({**SIGNAL,"kickoff_utc":"2026-10-27T22:30:00+00:00"},
                    {**SIGNAL,"away":"Rijeka U21"}):
            f=MonteBSDCrosswalk(token="test",downloader=lambda:raw,
                fetch=lambda u,t: (_ for _ in ()).throw(AssertionError("No bad ID")))
            self.assertEqual(f.lookup(sig)[1],"monte_no_exact_archive_match")

    def test_no_token_or_bad_archive_must_not_query_bsd(self):
        f=MonteBSDCrosswalk(token="",downloader=lambda:database(),
             fetch=lambda u,t: (_ for _ in ()).throw(AssertionError("should not call")))
        self.assertEqual(f.lookup(SIGNAL)[1],"bsd_not_configured")
        f=MonteBSDCrosswalk(token="test",downloader=lambda:b"not sqlite",
             fetch=lambda u,t: (_ for _ in ()).throw(AssertionError("should not call")))
        self.assertEqual(f.lookup(SIGNAL)[1],"monte_archive_unavailable")

    def test_429_backoff_then_final_and_persistent_stop(self):
        attempts=[]
        sleeps=[]
        def fetch(u,t):
            attempts.append(u)
            if len(attempts)<3: raise BSDProviderError("BSD HTTP 429")
            return event()
        f=MonteBSDCrosswalk(token="test",downloader=database,fetch=fetch,sleep=sleeps.append)
        self.assertIsNotNone(f.lookup(SIGNAL)[0])
        self.assertEqual(sleeps,[2,4])
        self.assertEqual(f.events_requested,3)
        f=MonteBSDCrosswalk(token="test",downloader=database,
                            fetch=lambda u,t: (_ for _ in ()).throw(BSDProviderError("BSD HTTP 429")),
                            sleep=lambda t:None)
        self.assertEqual(f.lookup(SIGNAL)[1],"monte_bsd_rate_limited")
        self.assertTrue(f.summary()["rate_limited"])

    def test_request_cap_and_invalid_db(self):
        f=MonteBSDCrosswalk(token="test",downloader=database,
                            max_event_requests=0,
                            fetch=lambda u,t: (_ for _ in ()).throw(AssertionError()))
        self.assertEqual(f.lookup(SIGNAL)[1],"monte_bsd_budget_deferred")
        with self.assertRaises(ValueError):
            MonteBSDCrosswalk(token="test",max_event_requests=19)
        with self.assertRaises(ValueError):
            exact_catalog(b"SQLite format 3\x00"+"x".encode()*4000001)

    def test_unique_core_name_archive_id_verified_by_fresh_bsd(self):
        raw=database([("600100","AS Roma","Cagliari",TIMESTAMP)])
        original={**SIGNAL,"home":"Roma","away":"Cagliari"}
        calls=[]
        def fetch(url,token):
            calls.append(url)
            return event(home="AS Roma",away="Cagliari")
        f=MonteBSDCrosswalk(token="test",downloader=lambda:raw,fetch=fetch)
        result,why=f.lookup(original)
        self.assertEqual(why,"verified_bsd_ft_from_monte_core_name")
        self.assertEqual(result["identity_match"],"CORE_NAME")
        self.assertEqual(result["home_goals"],2)
        self.assertEqual(calls,[ROOT+"600100/"])
        self.assertEqual(f.summary()["core_name_event_id_candidates"],1)
        self.assertEqual(f.summary()["verified_core_name_in_run"],1)
        self.assertEqual(f.summary()["exact_event_id_candidates"],0)

    def test_core_name_rejects_duplicate_same_club_and_reverse_before_network(self):
        original={**SIGNAL,"home":"Roma","away":"Cagliari"}
        variants=(
            (database([("600100","AS Roma","Cagliari",TIMESTAMP),
                       ("600101","Roma","Cagliari",TIMESTAMP)]),
             "monte_core_ambiguous_match"),
            (database([("600100","AS Roma","Cagliari",TIMESTAMP),
                       ("600101","AS Roma","Lazio",TIMESTAMP)]),
             "monte_core_side_collision"),
            (database([("600100","AS Roma","Cagliari",TIMESTAMP),
                       ("600101","Cagliari","AS Roma",TIMESTAMP)]),
             "monte_core_reversed_order"),
            (database([("600100","Cagliari","AS Roma",TIMESTAMP)]),
             "monte_core_reversed_order"),
        )
        for raw,expected in variants:
            with self.subTest(expected=expected,sha=hash(raw)):
                f=MonteBSDCrosswalk(token="test",downloader=lambda:raw,
                    fetch=lambda u,t: (_ for _ in ()).throw(AssertionError("Unexpected API request")))
                self.assertEqual(f.lookup(original)[1],expected)
                self.assertEqual(f.events_requested,0)

    def test_core_name_never_drops_youth_or_reserve_qualifiers(self):
        raw=database([("600100","AS Roma U21","Cagliari",TIMESTAMP)])
        sig={**SIGNAL,"home":"Roma","away":"Cagliari"}
        f=MonteBSDCrosswalk(token="test",downloader=lambda:raw,
            fetch=lambda u,t: (_ for _ in ()).throw(AssertionError("Unexpected API request")))
        self.assertEqual(f.lookup(sig)[1],"monte_no_exact_archive_match")

    def test_core_name_detail_mismatch_not_a_verified_ft(self):
        raw=database([("600100","AS Roma","Cagliari",TIMESTAMP)])
        sig={**SIGNAL,"home":"Roma","away":"Cagliari"}
        f=MonteBSDCrosswalk(token="test",downloader=lambda:raw,
                            fetch=lambda u,t:event(home="Other Roma",away="Cagliari"))
        result,reason=f.lookup(sig)
        self.assertIsNone(result)
        self.assertEqual(reason,"monte_bsd_identity_mismatch")
        self.assertEqual(f.summary()["verified_core_name_in_run"],0)


if __name__=="__main__":
    unittest.main()
