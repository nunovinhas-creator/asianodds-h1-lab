"""No-network adversarial tests: BSD complete-day event IDs become durable.

Uses an actual-style BSD v2 envelope and strictly SYNTHETIC fixture responses.
No API keys, no claims of newly settled production games.
"""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from h1lab.lab_bsd_id_registry import (
    discover, empty, plan_days, due_unmapped_keys, BSDRegistryLookup)
from h1lab.lab_bsd_search import BSDDateFallback

DAY="2026-10-28"
KO="2026-10-28T20:30:00+00:00"
NOW=datetime(2026,10,29,12,0,tzinfo=timezone.utc)
KEY="2026-10-28,935,36428"
ROW={"match_key":KEY,"home":"FC do Porto",
     "away":"Académico de Viseu","kickoff_utc":KO,"status":"PENDING"}
SOURCE={"id":599528,"home_team":{"name":"FC Porto"},
        "away_team":{"name":"Académico Viseu FC"},"event_date":KO,
        "status":"finished","home_score":1,"away_score":0}
OTHER={"id":600001,"home_team":{"name":"Lillestrøm SK"},
       "away_team":{"name":"Sogndal IL"},
       "event_date":"2026-10-28T17:00:00+00:00",
       "status":"finished","home_score":2,"away_score":0}
OTHER_KEY="2026-10-28,515,658"
OTHER_ROW={"match_key":OTHER_KEY,"home":"Lillestrøm SK",
           "away":"Sogndal IL","kickoff_utc":OTHER["event_date"],
           "status":"PENDING"}


class FakeMonte:
    def __init__(self, event=SOURCE):
        self.event=copy.deepcopy(event)
        self.events_requested=0
    def _event(self, ident):
        self.events_requested+=1
        return copy.deepcopy(self.event),"monte_bsd_event_fetched"


class BSDPersistentIdsTests(unittest.TestCase):
    def catalogue(self, events=None, status="complete"):
        return {DAY:(copy.deepcopy(events if events is not None else
                                   [SOURCE,OTHER]),status)}

    def test_complete_day_populates_multiple_scoped_ids_without_scores(self):
        ledger={KEY:ROW,OTHER_KEY:OTHER_ROW}
        index,stats=discover(empty(),self.catalogue(),ledger,NOW)
        self.assertEqual(stats["new_ids"],2)
        self.assertEqual(index["matches"][KEY]["event_id"],599528)
        self.assertEqual(index["matches"][OTHER_KEY]["event_id"],600001)
        self.assertEqual(index["days"][DAY]["total_events"],2)
        self.assertEqual(index["matches"][KEY]["source"],
                         "BSD_COMPLETE_FINISHED_DAY_LIST")
        self.assertNotIn("home_score",index["matches"][KEY])
        self.assertNotIn("away_score",index["matches"][KEY])
        self.assertNotIn("score",str(index["matches"]))
        self.assertEqual(index["probes"][DAY]["status"],"COMPLETE")

    def test_future_run_reuses_same_id_without_any_date_or_name_search(self):
        first,_=discover(empty(),self.catalogue(),{KEY:ROW},NOW)
        later,_=discover(first,{}, {KEY:ROW},NOW+timedelta(hours=5))
        self.assertEqual(first["matches"][KEY]["first_seen_at_utc"],
                         later["matches"][KEY]["first_seen_at_utc"])
        monte=FakeMonte()
        via=BSDRegistryLookup(later,monte)
        result,reason=via.lookup(ROW)
        self.assertEqual(reason,"verified_bsd_from_persisted_id")
        self.assertEqual((result["home_goals"],result["away_goals"]),(1,0))
        self.assertTrue(result["source"].endswith("/599528/"))
        self.assertEqual(result["match_key"],KEY)
        self.assertEqual(monte.events_requested,1)

    def test_original_club_categories_and_reversed_names_are_vetoed(self):
        changed=[
            dict(SOURCE,home_team={"name":"FC Porto Women"}),
            dict(SOURCE,home_team={"name":"FC Porto U19"}),
            dict(SOURCE,home_team=SOURCE["away_team"],
                 away_team=SOURCE["home_team"]),
            dict(SOURCE,event_date="2026-10-28T22:00:00+00:00"),
            dict(SOURCE,status="cancelled"),
        ]
        for event in changed:
            with self.subTest(event=event):
                index,stats=discover(empty(),self.catalogue([event]),
                                     {KEY:ROW},NOW)
                self.assertNotIn(KEY,index["matches"])

    def test_duplicate_source_side_or_competing_asianodds_game(self):
        collision=dict(OTHER,home_team={"name":"FC Porto"},
                       event_date="2026-10-28T20:34:00+00:00")
        index,stats=discover(empty(),self.catalogue([SOURCE,collision]),
                             {KEY:ROW},NOW)
        self.assertNotIn(KEY,index["matches"])
        self.assertEqual(stats.get("BSD_SOURCE_SIDE_COLLISION"),1)
        second=dict(ROW, match_key="2026-10-28,999,888")
        index,_=discover(empty(),self.catalogue([SOURCE]),
                         {KEY:ROW,second["match_key"]:second},NOW)
        self.assertNotIn(KEY,index["matches"])
        self.assertNotIn(second["match_key"],index["matches"])

    def test_reopened_source_with_changed_id_goes_to_quarantine(self):
        first,_=discover(empty(),self.catalogue([SOURCE]),{KEY:ROW},NOW)
        amended=dict(SOURCE,id=709999)
        later,_=discover(first,self.catalogue([amended]),{KEY:ROW},
                          NOW+timedelta(hours=5))
        self.assertIn(KEY,later["conflicts"])
        monte=FakeMonte()
        result,reason=BSDRegistryLookup(later,monte).lookup(ROW)
        self.assertIsNone(result)
        self.assertEqual(reason,"bsd_registry_quarantined")
        self.assertEqual(monte.events_requested,0)

    def test_modified_ledger_identity_invalidates_old_binding(self):
        first,_=discover(empty(),self.catalogue([SOURCE]),{KEY:ROW},NOW)
        changed={**ROW,"home":"Another Club"}
        later,_=discover(first,{}, {KEY:changed},NOW+timedelta(hours=1))
        self.assertIn(KEY,later["conflicts"])
        self.assertNotIn(KEY,later["matches"])

    def test_never_infer_final_score_from_list_or_nonfinal_detail(self):
        first,_=discover(empty(),self.catalogue([SOURCE]),{KEY:ROW},NOW)
        non_final=dict(SOURCE,status="live")
        via=BSDRegistryLookup(first,FakeMonte(non_final))
        result,reason=via.lookup(ROW)
        self.assertIsNone(result)
        self.assertNotEqual(reason,"verified_bsd_from_persisted_id")

    def test_detail_id_and_kickoff_and_club_must_match_locked_claim(self):
        first,_=discover(empty(),self.catalogue([SOURCE]),{KEY:ROW},NOW)
        for event in (
            dict(SOURCE,id=1000),
            dict(SOURCE,event_date="2026-10-28T22:30:00+00:00"),
            dict(SOURCE,away_team={"name":"Different Club"}),
            dict(SOURCE,replaced_by=7777),
        ):
            with self.subTest(event=event):
                result,_=BSDRegistryLookup(first,FakeMonte(event)).lookup(ROW)
                self.assertIsNone(result)

    def test_incomplete_and_duplicate_date_never_create_reusable_ids(self):
        for events,status in (([SOURCE],"incomplete"),
                              ([SOURCE,SOURCE],"complete"),
                              ([dict(SOURCE,id=None)],"complete")):
            with self.subTest(status=status):
                r,_=discover(empty(),self.catalogue(events,status),
                              {KEY:ROW},NOW)
                self.assertEqual(r["matches"],{})
                self.assertEqual(r["days"],{})

    def test_priority_date_planner_caps_requests_and_honors_4h_probe(self):
        registry=empty()
        selected=[KEY,OTHER_KEY]
        ledger={KEY:ROW,OTHER_KEY:OTHER_ROW}
        self.assertEqual(plan_days(selected,ledger,registry,NOW),[DAY])
        after,_=discover(registry,self.catalogue([OTHER]),ledger,NOW)
        self.assertEqual(plan_days([KEY],ledger,after,NOW+timedelta(hours=1)),[])
        self.assertEqual(plan_days([KEY],ledger,after,NOW+timedelta(hours=4)),[DAY])
        self.assertEqual(plan_days(selected,ledger,registry,NOW,max_days=0),[])

    def test_bsd_day_discovery_is_independent_of_empty_ft_recheck_queue(self):
        ledger={KEY:ROW,OTHER_KEY:OTHER_ROW}
        # The network FT queue may select zero, yet the independent BSD
        # discovery still has two overdue, unmapped games on the same day.
        ft_selected=[]
        self.assertEqual(ft_selected,[])
        due=due_unmapped_keys(ledger,empty(),NOW)
        self.assertEqual(set(due),{KEY,OTHER_KEY})
        self.assertEqual(plan_days(due,ledger,empty(),NOW),[DAY])
        index,_=discover(empty(),self.catalogue(),ledger,NOW)
        self.assertEqual(len(index["matches"]),2)
        self.assertEqual(due_unmapped_keys(ledger,index,NOW),[])

    def test_unattempted_date_precedes_recently_probed_crowded_date(self):
        day2="2026-10-27"
        row2={"match_key":"older","home":"Team 1",
              "away":"Team 2","kickoff_utc":day2+"T12:00:00+00:00",
              "status":"PENDING"}
        ledger={KEY:ROW,OTHER_KEY:OTHER_ROW,"older":row2}
        old=empty()
        old["probes"][DAY]={"attempted_at_utc":(NOW-timedelta(hours=5)).isoformat(),
                             "status":"UNAVAILABLE_OR_INCOMPLETE"}
        due=due_unmapped_keys(ledger,old,NOW)
        self.assertEqual(plan_days(due,ledger,old,NOW,max_days=2),
                         [day2,DAY])

    def test_bsd_due_catalogue_excludes_future_and_expired_and_conflicts(self):
        future=dict(ROW,match_key="future",
                    kickoff_utc=(NOW+timedelta(days=1)).isoformat())
        expired=dict(ROW,match_key="expired",
                     kickoff_utc=(NOW-timedelta(days=31)).isoformat())
        early=dict(ROW,match_key="early",
                   kickoff_utc=(NOW-timedelta(minutes=100)).isoformat())
        ledger={KEY:ROW,"future":future,"expired":expired,"early":early}
        self.assertEqual(due_unmapped_keys(ledger,empty(),NOW),[KEY])
        bad=empty();bad["conflicts"][KEY]={"reason":"collided"}
        self.assertEqual(due_unmapped_keys(ledger,bad,NOW),[])

    def test_bsd_documented_total_is_required_for_live_complete_catalogue(self):
        requests=[]
        def bad_count(url, token):
            requests.append(url)
            return {"count":4,"next":None,"results":[SOURCE]}
        finder=BSDDateFallback(token="fake",fetch=bad_count,
             primary=lambda *a,**kw:(None,"bsd_no_exact_match"),
             max_days=1,max_pages=1,require_count=True)
        rows,reason=finder._date_index(DAY)
        self.assertEqual(rows,[])
        self.assertEqual(reason,"bsd_date_total_mismatch")
        index,_=discover(empty(),finder.days,{KEY:ROW},NOW)
        self.assertEqual(index["matches"],{})
        self.assertEqual(len(requests),1)

    def test_paginated_day_requires_every_page_and_total_count(self):
        urls=[]
        def fetch(url,token):
            urls.append(url)
            if "offset=0" in url:
                return {"count":2,"next":"https://sports.bzzoiro.com/next",
                        "results":[SOURCE]}
            return {"count":2,"next":None,"results":[OTHER]}
        finder=BSDDateFallback(token="fake",fetch=fetch,
            primary=lambda *a,**kw:(None,"bsd_no_exact_match"),
            max_days=1,max_pages=2,require_count=True)
        rows,why=finder._date_index(DAY)
        self.assertEqual(why,"complete")
        self.assertEqual(len(rows),2)
        self.assertEqual(len(urls),2)
        index,_=discover(empty(),finder.days,{KEY:ROW,OTHER_KEY:OTHER_ROW},NOW)
        self.assertEqual(len(index["matches"]),2)

if __name__=="__main__":
    unittest.main()
