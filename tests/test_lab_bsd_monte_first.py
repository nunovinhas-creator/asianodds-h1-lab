"""Regression: MASTER BRAIN must recover the user's real Monte-Carlos BSD ID.

The factual fixture identifier 599528 is present in the Monte-Carlos SQLite
archive. This test uses a synthetic BSD HTTP response; it does NOT claim a
new provider call has succeeded in production.
"""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from h1lab.lab_bsd_priority import lookup_bsd_monte_first
from h1lab.lab_monte_bsd import MonteBSDCrosswalk
from h1lab.lab_identity import core_tokens, pair_level
from h1lab.results import norm_team
from h1lab.bsd import ROOT

KO = "2026-10-28T20:30:00+00:00"
SIGNAL = {"match_key":"2026-10-28,935,36428",
          "home":"FC do Porto","away":"Académico de Viseu",
          "kickoff_utc":KO}
SOURCE_HOME = "FC Porto"
SOURCE_AWAY = "Académico Viseu FC"
BSD_ID = 599528


class BSDMonteFirstTests(unittest.TestCase):
    def test_Portuguese_articles_are_not_different_clubs(self):
        self.assertEqual(core_tokens("FC do Porto"), core_tokens("FC Porto"))
        self.assertEqual(core_tokens("Académico de Viseu"),
                         core_tokens("Académico Viseu FC"))
        self.assertIsNotNone(pair_level("FC do Porto", "Académico de Viseu",
                                       SOURCE_HOME, SOURCE_AWAY))
        self.assertNotEqual(core_tokens("FC Porto Women"),
                            core_tokens("FC Porto"))

    def test_monte_archived_id_before_any_broad_date_search(self):
        requested = []
        def fake_bsd(url, token):
            requested.append(url)
            self.assertEqual(token, "synthetic-bsd-token")
            self.assertEqual(url, ROOT + str(BSD_ID) + "/")
            # Fixture and numeric BSD ID are real Monte-Carlos archive
            # coordinates; provider response is synthetic for regression.
            return {"id":BSD_ID,
                    "home_team":{"name":SOURCE_HOME},
                    "away_team":{"name":SOURCE_AWAY},
                    "event_date":KO,
                    "status":"finished",
                    "home_score":1,"away_score":0}
        monte = MonteBSDCrosswalk(token="synthetic-bsd-token",
                                  fetch=fake_bsd, sleep=lambda s:None,
                                  max_event_requests=2)
        monte.index = {
            (norm_team(SOURCE_HOME), norm_team(SOURCE_AWAY), KO[:10]):
            [(BSD_ID,datetime.fromisoformat(KO))]
        }
        monte.load_reason = "read_only_loaded"
        class Forbidden:
            def lookup(self, signal):
                raise AssertionError("Do not query BSD by name/date before known BSD id")
        result, why = lookup_bsd_monte_first(SIGNAL,monte,Forbidden())
        self.assertIsNotNone(result)
        self.assertEqual((result["home_goals"],result["away_goals"]),(1,0))
        self.assertEqual(result["source"], ROOT + str(BSD_ID) + "/")
        self.assertEqual(result["match_key"],SIGNAL["match_key"])
        self.assertEqual(len(requested),1)
        self.assertEqual(monte.events_requested,1)
        self.assertEqual(why,"verified_bsd_ft_from_monte_core_name")

    def test_lacking_archive_id_falls_back_without_guessing(self):
        calls=[]
        missing=SimpleNamespace(lookup=lambda s:(calls.append("monte") or None,
                                                  "monte_no_exact_archive_match"))
        fallback=SimpleNamespace(lookup=lambda s:(calls.append("date") or None,
                                                   "bsd_no_exact_match_in_date"))
        result,reason=lookup_bsd_monte_first(SIGNAL,missing,fallback)
        self.assertIsNone(result)
        self.assertEqual(reason,"bsd_no_exact_match_in_date")
        self.assertEqual(calls,["monte","date"])

    def test_invalid_direct_id_or_provider_failure_must_not_retry_date(self):
        for blocked_reason in ("monte_bsd_void","monte_core_ambiguous_match",
                               "monte_replaced_by_cycle","monte_bsd_provider_unavailable",
                               "monte_bsd_rate_limited","monte_bsd_budget_deferred"):
            with self.subTest(reason=blocked_reason):
                monte=SimpleNamespace(lookup=lambda _: (None,blocked_reason))
                class Forbidden:
                    def lookup(self,_):
                        self.fail("No extra provider attempts")
                result,reason=lookup_bsd_monte_first(SIGNAL,monte,Forbidden())
                self.assertIsNone(result)
                self.assertEqual(reason,blocked_reason)

    def test_no_identifier_is_guessed_from_asianodds_team_ids(self):
        observed=[]
        def fake_bsd(url, token):
            observed.append(url)
            raise AssertionError("Never try AsianOdds team IDs as BSD event IDs")
        monte=MonteBSDCrosswalk(token="synthetic",fetch=fake_bsd,
                                max_event_requests=2)
        monte.index={}
        monte.load_reason="read_only_loaded"
        class NoData:
            def lookup(self,_):
                return None,"bsd_no_exact_match_in_date"
        result,reason=lookup_bsd_monte_first(SIGNAL,monte,NoData())
        self.assertIsNone(result)
        self.assertEqual(observed,[])


if __name__ == "__main__":
    unittest.main()
