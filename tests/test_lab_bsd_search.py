"""Isolated date-index lookup safety tests. No secrets and no external HTTP."""
import unittest

from h1lab.bsd import ROOT, BSDProviderError
from h1lab.lab_bsd_search import BSDDateFallback, summary


def signal(day="2026-10-27", home="Home FC", away="Away FC"):
    return {"match_key": day + ",1,2", "home": home, "away": away,
            "kickoff_utc": day + "T17:00:00+00:00"}


def event(eid, *, home="Home FC", away="Away FC", status="finished", score=(2, 1)):
    return {"id": eid, "home_team": {"name": home}, "away_team": {"name": away},
            "event_date": "2026-10-27T17:00:00+00:00",
            "status": status, "home_score": score[0], "away_score": score[1]}


def missing(*args, **kwargs):
    return None, "bsd_no_exact_match"


class BSDDateSearchTests(unittest.TestCase):
    def test_date_recovers_strict_fixture_missed_by_fuzzy_index(self):
        calls = []
        def fetch(url, token):
            self.assertEqual(token, "test-token")
            calls.append(url)
            if "/events/123/" in url:
                return event(123)
            return {"results": [event(123)], "next": None}
        finder = BSDDateFallback(token="test-token", fetch=fetch, primary=missing)
        result, reason = finder.lookup(signal())
        self.assertEqual(reason, "verified_bsd_ft_via_date")
        self.assertEqual(result["home_goals"], 2)
        self.assertEqual(result["away_goals"], 1)
        self.assertEqual(result["source"], ROOT + "123/")
        self.assertEqual(summary(finder)["date_list_requests"], 1)
        self.assertEqual(summary(finder)["date_detail_requests"], 1)
        self.assertIn("status=finished", calls[0])
        self.assertIn("date_from=2026-10-27", calls[0])

    def test_cache_same_day_reuses_page_but_not_result_identity(self):
        calls = []
        def fetch(url, token):
            calls.append(url)
            return {"results": [event(12)], "next": None}
        f = BSDDateFallback(token="test-token", fetch=fetch, primary=missing)
        self.assertEqual(f.lookup(signal(away="Other"))[1], "bsd_no_exact_match_in_date")
        self.assertEqual(f.lookup(signal(away="Different"))[1], "bsd_no_exact_match_in_date")
        self.assertEqual(len(calls), 1)

    def test_date_budget_blocks_new_days(self):
        def fetch(url, token):
            return {"results": [], "next": None}
        f = BSDDateFallback(token="test", fetch=fetch, primary=missing, max_days=1)
        self.assertEqual(f.lookup(signal())[1], "bsd_no_exact_match_in_date")
        self.assertEqual(f.lookup(signal(day="2026-10-28"))[1], "bsd_date_budget_deferred")
        self.assertEqual(f.date_requests, 1)

    def test_paginated_complete_and_missing_fixture(self):
        urls = []
        def fetch(url, token):
            urls.append(url)
            if "offset=0" in url:
                return {"results": [event(12, away="Other")], "next": ROOT + "?offset=200"}
            return {"results": [event(123)], "next": None}
        f = BSDDateFallback(token="test", fetch=fetch, primary=missing)
        result, reason = f.lookup(signal())
        self.assertEqual(reason, "bsd_detail_mismatch")  # fake fetch also returns list on detail
        self.assertEqual(len(urls), 3)
        self.assertEqual(f.date_requests, 2)

    def test_incomplete_pagination_never_certifies_partial_match(self):
        def fetch(url, token):
            return {"results": [event(123)], "next": ROOT + "?offset=200"}
        f = BSDDateFallback(token="test", fetch=fetch, primary=missing, max_pages=1)
        result, reason = f.lookup(signal())
        self.assertIsNone(result)
        self.assertEqual(reason, "bsd_date_incomplete_pagination")
        self.assertEqual(f.details_requested, 0)

    def test_ambiguous_identical_teams_never_auto_select(self):
        def fetch(url, token):
            return {"results": [event(123), event(124)], "next": None}
        f = BSDDateFallback(token="test", fetch=fetch, primary=missing)
        self.assertEqual(f.lookup(signal())[1], "bsd_date_ambiguous_match")

    def test_bad_detail_score_and_identity_are_rejected(self):
        def fetch(url, token):
            if "/events/123/" in url:
                return event(123, score=(None, 2))
            return {"results": [event(123)], "next": None}
        f = BSDDateFallback(token="test", fetch=fetch, primary=missing)
        res, reason = f.lookup(signal())
        self.assertIsNone(res)
        self.assertEqual(reason, "bsd_date_invalid_regulation_score")

    def test_provider_error_no_secret_or_retries(self):
        queries = []
        def fetch(url, token):
            queries.append(url)
            raise BSDProviderError("secret-token in error")
        f = BSDDateFallback(token="test", fetch=fetch, primary=missing)
        self.assertEqual(f.lookup(signal())[1], "bsd_date_unavailable")
        self.assertEqual(f.lookup(signal())[1], "bsd_date_unavailable")
        self.assertEqual(len(queries), 1)

    def test_primary_hit_is_unchanged(self):
        def primary(s, **kwargs):
            return {"match_key": s["match_key"], "status": "final", "home_goals": 1,
                    "away_goals": 0, "source": ROOT + "123/"}, "verified_bsd_ft"
        def fail_fetch(*_):
            raise AssertionError("Should not call date fallback")
        f = BSDDateFallback(token="test", fetch=fail_fetch, primary=primary)
        self.assertEqual(f.lookup(signal())[1], "verified_bsd_ft")
        self.assertEqual(f.date_requests, 0)

    def test_primary_provider_error_does_not_multiply_calls(self):
        def primary(s, **kwargs):
            raise BSDProviderError("rate_limited")
        f = BSDDateFallback(token="test", primary=primary)
        self.assertEqual(f.lookup(signal())[1], "bsd_primary_unavailable")
        self.assertEqual(f.date_requests, 0)

    def test_invalid_budget_fails(self):
        for count in (-1, 5):
            with self.assertRaises(ValueError):
                BSDDateFallback(token="test", max_days=count)
        for pages in (0, 5):
            with self.assertRaises(ValueError):
                BSDDateFallback(token="test", max_pages=pages)


if __name__ == "__main__":
    unittest.main()
