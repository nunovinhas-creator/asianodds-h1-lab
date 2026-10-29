"""Offline tests for LAB BSD payload compatibility; H1 bsd.py untouched."""
import unittest
from h1lab.lab_bsd_payload import normalized_detail, normalized_payload
from h1lab.lab_bsd_search import BSDDateFallback

SIG={"match_key":"2026-10-28,30,31","home":"Home FC",
     "away":"Away FC","kickoff_utc":"2026-10-28T15:00:00+00:00"}
E={"id":"12345","home_team":{"name":"Home FC"},"away_team":{"name":"Away FC"},
   "event_date":"2026-10-28T15:00:00+00:00",
   "status":{"type":"finished"},"home_score":"2","away_score":"1"}


class BSDPayloadCompatibility(unittest.TestCase):
    def test_nested_bsd_detail_and_digit_scores(self):
        for data in ({"data":E},{"result":E},{"data":{"result":E}}):
            with self.subTest(data=data):
                e=normalized_detail(data)
                self.assertEqual(e["id"],12345)
                self.assertEqual(e["status"],"finished")
                self.assertEqual((e["home_score"],e["away_score"]),(2,1))

    def test_documented_regulation_score_nested_is_usable(self):
        e=dict(E,home_score=None,away_score=None,
               scores={"fulltime":{"home":"2","away":"1"}})
        result=normalized_detail(e)
        self.assertEqual((result["home_score"],result["away_score"]),(2,1))

    def test_generic_or_penalty_score_never_guessed(self):
        for patch in (
            {"home_score":None,"away_score":None,
             "score":{"home":2,"away":1}},
            {"home_score":None,"away_score":None,
             "scores":{"penalties":{"home":5,"away":4}}},
            {"status":"AET"},
            {"home_score":True,"away_score":1},
        ):
            with self.subTest(patch=patch):
                e=normalized_detail(dict(E,**patch))
                if e.get("status") == "finished":
                    self.assertTrue(e.get("home_score") is None or
                                    e.get("away_score") is None)
                else:
                    self.assertNotEqual(e.get("status"),"finished")

    def test_one_primary_and_one_detail_request_only(self):
        requested=[]
        def fetch(url,token):
            requested.append(url)
            if "/events/12345/" in url:
                return {"data":E}
            return {"data":{"count":1,"next":None,"results":[E]}}
        finder=BSDDateFallback(token="synthetic",fetch=fetch)
        result,why=finder.lookup(SIG)
        self.assertEqual(why,"verified_bsd_ft")
        self.assertEqual((result["home_goals"],result["away_goals"]),(2,1))
        self.assertEqual(len(requested),2)

    def test_bad_ambiguous_nested_result_cannot_auto_final(self):
        def fetch(url,token):
            return {"data":{"count":2,"next":None,"results":[E,E]}}
        finder=BSDDateFallback(token="synthetic",fetch=fetch)
        self.assertEqual(finder.lookup(SIG)[1],"bsd_ambiguous_match")


if __name__ == "__main__":
    unittest.main()
