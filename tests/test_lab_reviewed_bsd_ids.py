"""Exactly reviewed BSD IDs and no mistaken use of AsianOdds IDs."""
import unittest
from datetime import datetime, timezone
from h1lab.bsd import ROOT
from h1lab.lab_monte_bsd import MonteBSDCrosswalk
from h1lab.lab_reviewed_bsd_ids import REVIEWED_BSD_FIXTURES,reviewed_bsd_fixture
from h1lab.lab_results import reconcile

def signal(key):
    v=REVIEWED_BSD_FIXTURES[key]
    return {"match_key":key,"home":v[0],"away":v[1],"kickoff_utc":v[2]}

def detail(key):
    v=REVIEWED_BSD_FIXTURES[key]
    return {"id":v[3],"status":"finished",
            "home_team":{"name":v[4]},"away_team":{"name":v[5]},
            "event_date":v[2],"home_score":2,"away_score":0}

class ReviewedBSDIDsTests(unittest.TestCase):
    def test_all_five_verified_events_direct_without_monte_archive(self):
        self.assertEqual(len(REVIEWED_BSD_FIXTURES),5)
        for key in REVIEWED_BSD_FIXTURES:
            with self.subTest(key=key):
                target=REVIEWED_BSD_FIXTURES[key][3]
                called=[]
                def fetch(url,token):
                    called.append(url)
                    self.assertEqual(url,ROOT+str(target)+"/")
                    return detail(key)
                m=MonteBSDCrosswalk(token="test",downloader=lambda:
                       (_ for _ in ()).throw(AssertionError("not needed")),
                    fetch=fetch,sleep=lambda s:None)
                result,reason=m.lookup(signal(key))
                self.assertEqual(reason,"verified_bsd_ft_from_reviewed_id")
                self.assertEqual(result["source"],ROOT+str(target)+"/")
                self.assertEqual(called,[ROOT+str(target)+"/"])
                self.assertEqual(m.summary()["reviewed_bsd_ids_verified"],1)

    def test_other_match_key_or_modified_identity_not_allowed(self):
        key="2026-10-27,240,227"
        base=signal(key)
        for changed in ({**base,"match_key":"other"},
                        {**base,"home":"Roma U21"},
                        {**base,"away":"Other"},
                        {**base,"kickoff_utc":"2026-10-28T19:45:00+00:00"}):
            self.assertIsNone(reviewed_bsd_fixture(changed))

    def test_new_oct28_ids_are_strictly_fixture_scoped(self):
        for key in ("2026-10-28,1069,200","2026-10-28,521,159"):
            with self.subTest(key=key):
                original=signal(key)
                candidate=REVIEWED_BSD_FIXTURES[key]
                self.assertEqual(reviewed_bsd_fixture(original),
                                 (candidate[3], candidate[4], candidate[5]))
                for modified in (
                    {**original,"match_key":"2026-10-28,99999,99998"},
                    {**original,"home":candidate[4]},
                    {**original,"away":"Unknown Women"},
                    {**original,"kickoff_utc":"2026-10-28T19:30:00+00:00"},
                    {**original,"home":original["away"],"away":original["home"]},
                ):
                    if modified==original:
                        continue
                    self.assertIsNone(reviewed_bsd_fixture(modified))

    def test_new_reviewed_ids_get_one_safe_check_within_grace_and_budget(self):
        no=lambda _: (None,"not_found")
        now=datetime(2026,10,28,22,30,tzinfo=timezone.utc)
        for key in ("2026-10-28,1069,200","2026-10-28,521,159"):
            with self.subTest(key=key):
                s=signal(key)
                prior={"schema_version":1,"matches":{key:{
                    **s,"status":"PENDING","attempts":2,
                    "checked_at":"2026-10-28T21:46:17+00:00",
                    "lookup_source_version":11}}}
                calls=[]
                def bsd(sig):
                    calls.append(sig["match_key"])
                    return None,"bsd_regulation_unverified"
                first,_,n=reconcile({"alerts":[s],"signals":[]},[],prior,now=now,
                      bsd_lookup=bsd,tsdb_lookup=no,max_checks=30)
                self.assertEqual(n,1)
                self.assertEqual(calls,[key])
                self.assertEqual(first["matches"][key]["status"],"PENDING")
                self.assertEqual(first["matches"][key]["reviewed_bsd_id_check_version"],1)
                _,_,n2=reconcile({"alerts":[s],"signals":[]},[],first,now=now,
                      bsd_lookup=lambda _:(_ for _ in ()).throw(
                          AssertionError("must not recheck")),
                      tsdb_lookup=no,max_checks=30)
                self.assertEqual(n2,0)

    def test_wrong_event_id_or_team_or_kickoff_are_rejected(self):
        key="2026-10-27,240,227"
        for changed in ({"id":987654}, {"home_team":{"name":"Other FC"}},
                        {"event_date":"2026-10-28T19:45:00+00:00"},
                        {"status":"after extra time"}):
            def fetch(url,token,update=changed):
                return {**detail(key),**update}
            m=MonteBSDCrosswalk(token="test",fetch=fetch,
                downloader=lambda:(_ for _ in ()).throw(AssertionError("Should bypass archive")))
            self.assertIsNone(m.lookup(signal(key))[0])

    def test_ft_one_time_recheck_prioritized_and_not_repeated(self):
        key="2026-10-27,240,227"
        s=signal(key)
        st={"alerts":[s],"signals":[]}
        previous={"schema_version":1,"matches":{key:{
            "status":"PENDING","home":s["home"],"away":s["away"],
            "kickoff_utc":s["kickoff_utc"],"checked_at":"2026-10-28T08:20:00+00:00",
            "attempts":2,"lookup_source_version":6}}}
        times=[]
        def bsd(sig):
            times.append(sig["match_key"])
            return {"match_key":sig["match_key"],"status":"final",
                    "home_goals":2,"away_goals":0,
                    "source":ROOT+"210138/"},"verified_bsd_ft_from_reviewed_id"
        now=datetime(2026,10,28,8,30,tzinfo=timezone.utc)
        updated,report,count=reconcile(st,[],previous,now=now,
            bsd_lookup=bsd,tsdb_lookup=lambda s:(None,"not_found"))
        self.assertEqual(count,1)
        self.assertEqual(report["final_recorded"],1)
        self.assertEqual(updated["matches"][key]["reviewed_bsd_id_check_version"],1)
        self.assertEqual(len(times),1)
        updated2,report2,count2=reconcile(st,[],updated,now=now,
            bsd_lookup=lambda s: (_ for _ in ()).throw(AssertionError("must not repeat")),
            tsdb_lookup=lambda s: (_ for _ in ()).throw(AssertionError("must not repeat")))
        self.assertEqual(count2,0)
        self.assertEqual(report2["final_recorded"],1)
        self.assertEqual(updated2,updated)

if __name__=="__main__":
    unittest.main()
