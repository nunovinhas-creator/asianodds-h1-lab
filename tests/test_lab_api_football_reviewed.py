"""Explicit human approval and one-call API-Football fixture batches; all synthetic."""
import copy
import unittest
from datetime import datetime, timezone

from h1lab.lab_api_football import APIFootballResults, fetch_ids
from h1lab.lab_api_football_reviewed import plan_reviewed_ids

NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
KO = "2026-10-27T16:00:00+00:00"


def signal(i):
    return {"match_key": f"2026-10-27,{i},55", "home": f"Express Red Eagles {i}",
            "away": "Kataka FC", "kickoff_utc": KO}


def candidate(i, fixture_id):
    return {"provider": "api_football", "provider_event_id": str(fixture_id),
            "provider_home_team_id": 300 + i, "provider_away_team_id": 400 + i,
            "provider_competition_id": 77, "orientation": "SAME_ORDER",
            "provider_kickoff_utc": KO, "review_only": True,
            "provider_home": f"Express {i}", "provider_away": "Kataka"}


def approval(i, fixture_id):
    s = signal(i)
    return {**{k: s[k] for k in ("home", "away", "kickoff_utc")},
            "status": "APPROVED", "provider_fixture_id": fixture_id,
            "provider_home_team_id": 300 + i, "provider_away_team_id": 400 + i,
            "provider_competition_id": 77,
            "provider_kickoff_utc": KO,
            "reviewed_by": "human-reviewer",
            "reviewed_at_utc": "2026-10-28T12:00:00+00:00"}


def event(i, fixture_id, status="FT", h=1, a=2):
    return {"fixture": {"id": fixture_id, "date": KO, "status": {"short": status}},
            "league": {"id": 77, "name": "Test League"},
            "teams": {"home": {"id": 300 + i, "name": f"Express {i}"},
                      "away": {"id": 400 + i, "name": "Kataka"}},
            "goals": {"home": h, "away": a},
            "score": {"fulltime": {"home": h, "away": a}}}


def fixtures():
    matches = {signal(i)["match_key"]: dict(signal(i), status="PENDING")
               for i in (1, 2, 3)}
    review = {"schema_version": 1, "games": [
        {**signal(i), "possible_duplicates": [], "candidates": [candidate(i, 5000 + i)]}
        for i in (1, 2, 3)]}
    approved = {"schema_version": 1, "pairs": {
        signal(i)["match_key"]: approval(i, 5000 + i) for i in (1, 2, 3)}}
    return matches, review, approved


class ReviewedBatchTests(unittest.TestCase):
    def test_no_approval_no_calls_and_no_automatic_alias_match(self):
        matches, review, _ = fixtures()
        ids = plan_reviewed_ids(list(matches), matches, review,
                                {"schema_version": 1, "pairs": {}}, NOW)
        self.assertEqual(ids, {})
        p = APIFootballResults(key="dummy", max_days=0, reviewed_targets=ids,
                              id_fetch=lambda ids, key: self.fail("No ID calls"))
        self.assertEqual(p.id_requests, 0)

    def test_three_human_approved_ids_one_batch_and_strict_90min_ft(self):
        matches, review, approved = fixtures()
        targets = plan_reviewed_ids(list(matches), matches, review, approved, NOW)
        self.assertEqual(len(targets), 3)
        calls = []
        def fetch(ids, key):
            calls.append(tuple(ids))
            return {5000 + i: event(i, 5000 + i) for i in (1, 2, 3)}
        p = APIFootballResults(key="fake", max_days=3,
                              reviewed_targets=targets, id_fetch=fetch)
        for i in (3, 1, 2):
            result, reason = p.lookup(signal(i))
            self.assertEqual(reason, "verified_api_football_ft_reviewed_pair")
            self.assertEqual((result["home_goals"], result["away_goals"]), (1, 2))
            self.assertEqual(result["identity_match"], "REVIEWED_PAIR")
        self.assertEqual(calls, [(5001, 5002, 5003)])
        self.assertEqual(p.id_requests, 1)
        self.assertEqual(p.summary()["requests"], 1)

    def test_reviewed_id_does_not_override_team_orientation_and_competition(self):
        matches, review, approved = fixtures()
        targets = plan_reviewed_ids(list(matches), matches, review, approved, NOW)
        for bad in ("reverse", "league", "aet", "kickoff"):
            with self.subTest(bad=bad):
                e = event(1, 5001)
                if bad == "reverse":
                    e["teams"]["home"]["id"], e["teams"]["away"]["id"] = 401, 301
                if bad == "league":
                    e["league"]["id"] = 88
                if bad == "aet":
                    e["fixture"]["status"]["short"] = "AET"
                if bad == "kickoff":
                    e["fixture"]["date"] = "2026-10-27T17:00:00+00:00"
                p = APIFootballResults(key="test", reviewed_targets=targets,
                    id_fetch=lambda ids, key: {5001: e})
                result, reason = p.lookup(signal(1))
                self.assertIsNone(result)
                self.assertNotEqual(reason, "verified_api_football_ft_reviewed_pair")

    def test_approval_must_match_real_review_and_no_colliding_ids(self):
        matches, review, approved = fixtures()
        mutant = copy.deepcopy(approved)
        mutant["pairs"][signal(2)["match_key"]]["provider_fixture_id"] = 5001
        self.assertNotIn(signal(1)["match_key"],
                         plan_reviewed_ids(list(matches), matches, review, mutant, NOW))
        approved["pairs"][signal(1)["match_key"]]["provider_home_team_id"] = 999
        self.assertNotIn(signal(1)["match_key"],
                         plan_reviewed_ids(list(matches), matches, review, approved, NOW))
        approved["pairs"][signal(1)["match_key"]]["provider_home_team_id"] = 301
        review["games"][0]["possible_duplicates"] = [{"match_key": "potential"}]
        self.assertNotIn(signal(1)["match_key"],
                         plan_reviewed_ids(list(matches), matches, review, approved, NOW))

    def test_reuse_of_already_confirmed_ft_fixture_id_is_blocked(self):
        matches, review, approved = fixtures()
        matches["old-confirmed"] = {"status": "FINAL", "result": {
            "evidence": "api_football_only",
            "source": "https://v3.football.api-sports.io/fixtures?id=5001"}}
        targets = plan_reviewed_ids(list(matches), matches, review, approved, NOW)
        self.assertNotIn(signal(1)["match_key"], targets)

    def test_batch_more_than_twenty_or_duplicate_ids_rejected(self):
        for ids in ([], list(range(21)), [10, 10], ["bad"], [0]):
            with self.subTest(ids=ids):
                with self.assertRaises(ValueError):
                    fetch_ids(ids, "fake-key")
        with self.assertRaises(ValueError):
            plan_reviewed_ids([], {}, {}, {"schema_version": 2, "pairs": {}}, NOW)


if __name__ == "__main__":
    unittest.main()
