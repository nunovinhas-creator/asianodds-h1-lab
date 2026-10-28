"""H1/LAB promotion: isolated, no-network, fail-closed regression tests."""
import copy
import unittest
from datetime import datetime, timezone

from h1lab.lab_promotion import candidate, propose, _safe_source
from h1lab.core import public_data

NOW = datetime(2026, 10, 28, 15, tzinfo=timezone.utc)
KO = "2026-10-27T17:00:00+00:00"
KEY = "2026-10-27,1001,1002"
URL = "https://sports.bzzoiro.com/api/v2/events/123456/"


def signal(key=KEY, home="Club A", away="Club B", kickoff=KO):
    return {"signal_id": key, "match_key": key, "home": home, "away": away,
            "kickoff_utc": kickoff, "line": 3.0,
            "under_odds": 1.88, "observed_at": "2026-10-27T10:00:00+00:00"}


def lab(signal_, status="FINAL", score=(1, 1), evidence="bsd_only", url=URL):
    return {"status": status,
            "home": signal_["home"], "away": signal_["away"],
            "kickoff_utc": signal_["kickoff_utc"],
            "result": {"home_goals": score[0], "away_goals": score[1],
                       "evidence": evidence, "source": url}}


class H1LabPromotionTests(unittest.TestCase):
    def test_exact_h1_final_imported_without_mutating_either_input(self):
        s = signal()
        previous = [{"match_key": "old", "status": "final", "home_goals": 1,
                     "away_goals": 2, "source": URL}]
        state = {"signals": [s], "tickets": [], "alerts": []}
        ledger = {"matches": {KEY: lab(s)}}
        frozen = copy.deepcopy((state, ledger, previous))
        planned, reasons = propose(state, ledger, previous, NOW)
        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0][0]["match_key"], KEY)
        self.assertEqual(planned[0][1], "bsd_only")
        self.assertEqual(frozen, (state, ledger, previous))
        self.assertNotIn(KEY, {r["match_key"] for r in previous})

    def test_unverified_and_mutated_identity_never_promoted(self):
        s = signal()
        for altered in ({"status":"PENDING"},
                        {"status":"SOURCE_ORDER_CONFLICT"},
                        {"home":"Club C"},
                        {"away":"Club C"},
                        {"kickoff_utc":"2026-10-27T17:01:00+00:00"}):
            with self.subTest(altered=altered):
                row = {**lab(s), **altered}
                self.assertIsNone(candidate(s, row, NOW)[0])

    def test_score_validation_and_source_security(self):
        s = signal()
        for h,a in ((True, 1),(-1,0),(1.5,0),(100,1)):
            row=lab(s,score=(h,a))
            self.assertIsNone(candidate(s,row,NOW)[0])
        for url in ("http://example.com/score", "https://localhost/score",
                    "https://127.0.0.1/score", "https://user:pass@example.com/score",
                    "file:///etc/shadow", "https://example.local/score"):
            with self.subTest(url=url):
                self.assertFalse(_safe_source(url))
                self.assertIsNone(candidate(s,lab(s,url=url),NOW)[0])

    def test_future_and_3h_grace_blocked(self):
        s=signal()
        self.assertIsNone(candidate(s,lab(s),datetime(2026,10,27,19,tzinfo=timezone.utc))[0])

    def test_existing_h1_final_immutable_even_if_lab_disagrees(self):
        s=signal()
        recorded = [{"match_key":KEY,"status":"final","home_goals":"3",
                     "away_goals":"0","source":URL}]
        planned, rejection = propose({"signals":[s]}, {"matches":{KEY:lab(s)}},recorded,NOW)
        self.assertEqual(planned,[])
        self.assertEqual(rejection["existing_h1_ft_disagrees"],1)
        self.assertEqual(recorded[0]["home_goals"],"3")

    def test_reviewed_public_requires_two_provenance_links(self):
        s=signal()
        row=lab(s,score=(4,0),evidence="reviewed_public_only",
                url="https://www.official-example.com/match/abc")
        self.assertIsNone(candidate(s,row,NOW)[0])
        row["reviewed_public_resolution"]={
            "method":"reviewed_two_independent_public_ft",
            "corroboration_urls":["https://www.official-example.com/match/abc",
                                  "https://news-example.net/match/abc"]}
        self.assertIsNotNone(candidate(s,row,NOW)[0])

    def test_provably_reversed_sportscore_slug_rejected(self):
        s=signal(home="Club A",away="Club B")
        row=lab(s,evidence="sportscore_only",
                url="https://sportscore.com/football/match/club-b-vs-club-a/123/")
        self.assertEqual(candidate(s,row,NOW)[1],"sportscore_source_order_conflict")

    def test_duplicate_signal_identity_rejected(self):
        s=signal()
        plan, rejected=propose({"signals":[s,s.copy()]},{"matches":{KEY:lab(s)}},[],NOW)
        self.assertEqual(plan,[])
        self.assertEqual(rejected["duplicate_signal_identity"],2)

    def test_three_confirmed_legs_create_a_settled_triple(self):
        signal_rows = [signal(key=f"2026-10-27,{i},{i+100}") for i in (1,2,3)]
        signal_rows[0]["line"]=3.0
        signal_rows[1]["line"]=3.0
        signal_rows[2]["line"]=2.75
        signal_rows[0]["under_odds"]=2.06
        state={"alerts":[],"signals":signal_rows,
               "tickets":[{"ticket_id":"T-test","signal_ids":[s["signal_id"] for s in signal_rows]}]}
        ledger={"matches":{signal_rows[0]["match_key"]:lab(signal_rows[0],score=(2,1)),
                           signal_rows[1]["match_key"]:lab(signal_rows[1],score=(1,1)),
                           signal_rows[2]["match_key"]:lab(signal_rows[2],score=(1,0))}}
        planned,_=propose(state,ledger,[],NOW)
        self.assertEqual(len(planned),3)
        result={x["match_key"]:{"home_goals":x["home_goals"],
                               "away_goals":x["away_goals"],"source":x["source"]}
                for x,_ in planned}
        view=public_data(state,result,NOW)
        self.assertEqual(view["triples"]["settled"],1)
        self.assertAlmostEqual(view["triples"]["profit_units"],2.5344,places=4)

if __name__=="__main__":
    unittest.main()
