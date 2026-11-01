"""BSD football final score matching tests: synthetic data only."""
import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from h1lab.bsd import find_result, regulation_result

UTC=timezone.utc
KO=datetime(2026,10,27,19,45,tzinfo=UTC)
SIGNAL={"home":"Borussia Dortmund","away":"SV Werder Bremen",
        "kickoff_utc":KO.isoformat(),"match_key":"2026-10-27,194,203"}
EVENT={"id":31878,"home_team":{"id":2,"name":"Borussia Dortmund"},
       "away_team":{"id":3,"name":"Werder Bremen"},
       "event_date":KO.isoformat(),"status":"finished",
       "home_score":2,"away_score":1,
       "extra_time_score":None,"penalty_shootout":None}


class BSDTests(unittest.TestCase):
    def test_completed_regulation_score(self):
        final, reason = regulation_result(SIGNAL,EVENT)
        self.assertEqual(reason,"verified_bsd_ft")
        self.assertEqual((final["home_goals"],final["away_goals"]),(2,1))
        self.assertIn("/31878/",final["source"])

    def test_not_finished(self):
        self.assertIsNone(regulation_result(SIGNAL,{**EVENT,"status":"live"})[0])

    def test_regulation_result_unaffected_by_extra_time_or_penalties(self):
        # BSD explicitly documents the normal-time score separately from ET.
        for field, payload in (("extra_time_score",{"home":1,"away":0}),
                               ("penalty_shootout",{"home":5,"away":4})):
            with self.subTest(field=field):
                result, reason = regulation_result(SIGNAL, {**EVENT,field:payload})
                self.assertEqual(reason,"verified_bsd_ft")
                self.assertEqual((result["home_goals"],result["away_goals"]),(2,1))

    def test_wrong_team_and_date(self):
        for candidate in (
            {**EVENT,"home_team":{"name":"Borussia Dortmund U21"}},
            {**EVENT,"event_date":(KO+timedelta(days=1)).isoformat()},
            {**EVENT,"away_team":{"name":"VfB Stuttgart"}},
        ):
            self.assertIsNone(regulation_result(SIGNAL,candidate)[0])

    def test_no_guessing_when_missing_regulation_score(self):
        for candidate in ({**EVENT,"home_score":None},
                          {**EVENT,"home_score":True},
                          {**EVENT,"id":None},
                          {**EVENT,"event_date":"2026-10-27"}):
            self.assertIsNone(regulation_result(SIGNAL,candidate)[0])

    def test_fetches_list_then_detail(self):
        urls=[]
        def fake_fetch(url, token):
            self.assertEqual(token,"SYNTHETIC_TOKEN")
            urls.append(url)
            if "?team_name=" in url:
                return {"count":1,"next":None,"results":[EVENT]}
            return EVENT
        result, reason=find_result(SIGNAL,fetch=fake_fetch,token="SYNTHETIC_TOKEN")
        self.assertEqual(reason,"verified_bsd_ft")
        self.assertEqual(result["away_goals"],1)
        self.assertEqual(len(urls),2)
        self.assertIn("status=finished",urls[0])

    def test_ambiguity_is_pending(self):
        def fake_fetch(url, token):
            return {"results":[EVENT,EVENT],"next":None}
        self.assertEqual(find_result(SIGNAL,fetch=fake_fetch,token="SYNTHETIC_TOKEN")[1],
                         "bsd_ambiguous_match")


    def test_cf_sc_designators_still_require_full_identity_and_detail(self):
        from h1lab.results import norm_team
        self.assertEqual(norm_team("Córdoba CF"), norm_team("Córdoba"))
        self.assertEqual(norm_team("SC Farense"), norm_team("Farense"))
        self.assertEqual(norm_team("CF Granada"), norm_team("Granada"))
        self.assertNotEqual(norm_team("SC Farense U21"), norm_team("Farense"))
        self.assertNotEqual(norm_team("Real Madrid CF"), norm_team("Atlético Madrid CF"))
        self.assertEqual(norm_team("FC"), "fc")  # Never normalize to blank.
        fixture={**SIGNAL,"home":"Córdoba CF","away":"SC Farense"}
        event={**EVENT,"home_team":{"name":"Córdoba"},
               "away_team":{"name":"Farense"}}
        calls=[]
        def fetch(url, token):
            calls.append(url)
            return {"results":[event],"next":None} if "?" in url else event
        result,reason=find_result(fixture,fetch=fetch,token="SYNTHETIC_TOKEN")
        self.assertEqual(reason,"verified_bsd_ft")
        self.assertEqual((result["home_goals"],result["away_goals"]),(2,1))
        self.assertEqual(len(calls),2)  # One list + independently verified detail.

    def test_bsd_reason_classification_uses_same_single_list_call(self):
        examples = [
            ([], "bsd_empty_finished_list"),
            ([{**EVENT,"event_date":(KO+timedelta(hours=4)).isoformat()}],
             "bsd_kickoff_missing_or_mismatch"),
            ([{**EVENT,"away_team":{"name":"Different Team"}}],
             "bsd_away_name_mismatch"),
            ([{**EVENT,"home_team":{"name":"Different Team"}}],
             "bsd_home_name_mismatch"),
            ([{**EVENT,"home_team":{"name":"Different Team"},
               "away_team":{"name":"Other Team"}}],
             "bsd_no_exact_match"),
        ]
        for matches,expected in examples:
            with self.subTest(expected=expected):
                calls=[]
                def fetch(url, token):
                    calls.append(url)
                    return {"results":matches,"next":None,"count":len(matches)}
                outcome,reason=find_result(SIGNAL,fetch=fetch,token="SYNTHETIC_TOKEN")
                self.assertIsNone(outcome)
                self.assertEqual(reason,expected)
                self.assertEqual(len(calls),1)

    def test_no_guessing_when_names_ambiguous_or_not_finished(self):
        signal={**SIGNAL,"home":"Córdoba CF","away":"SC Farense"}
        exact={**EVENT,"home_team":{"name":"Córdoba"},
               "away_team":{"name":"Farense"}}
        def fetch(url,token):
            return {"results":[exact,exact],"next":None}
        self.assertEqual(find_result(signal,fetch=fetch,token="SYNTHETIC")[1],
                         "bsd_ambiguous_match")
        self.assertIsNone(regulation_result(
            signal,{**exact,"status":"live"})[0])

    def test_without_token_no_remote_calls(self):
        with patch.dict(os.environ,{"BSD_API_KEY":""}):
            def forbidden(*a):
                self.fail("Should not call BSD without key")
            self.assertEqual(find_result(SIGNAL,fetch=forbidden)[1],"bsd_not_configured")


if __name__=="__main__":
    unittest.main()
