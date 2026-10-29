"""Explicit human approval and one-call API-Football fixture batches; all synthetic."""
import copy
import unittest
from datetime import datetime, timezone

from h1lab.lab_api_football import APIFootballResults, fetch_ids
from h1lab.lab_api_football_reviewed import plan_reviewed_ids
from h1lab.lab_ft_day_identity import build_index

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
    return {**{k: s[k] for k in ("match_key", "home", "away", "kickoff_utc")},
            "provider": "api_football", "status": "APPROVED", "provider_fixture_id": fixture_id,
            "provider_home_team_id": 300 + i, "provider_away_team_id": 400 + i,
            "provider_competition_id": 77,
            "provider_kickoff_utc": KO, "competition_anchor_fixture_id": 6000,
            "reviewed_by": "human-reviewer",
            "reviewed_at_utc": "2026-10-28T12:00:00+00:00"}


def event(i, fixture_id, status="FT", h=1, a=2):
    return {"fixture": {"id": fixture_id, "date": KO, "status": {"short": status}},
            "league": {"id": 77, "name": "Test League"},
            "teams": {"home": {"id": 300 + i, "name": f"Express {i}"},
                      "away": {"id": 400 + i, "name": "Kataka"}},
            "goals": {"home": h, "away": a},
            "score": {"fulltime": {"home": h, "away": a}}}


def _proof():
    # Synthetic complete provider list with a separate settled fixture in
    # the same competition; each team only plays once in the 90m window.
    rows = [event(i, 5000+i) for i in (1, 2, 3)]
    rows.append(event(10, 6000))
    day_index = build_index({"schema_version": 1, "days": {}},
                            {"2026-10-27": rows}, NOW)
    registry = {"schema_version": 1, "entries": {
        "api_football:6000": {"match_key": "previous-verified",
                              "status": "CONFIRMED_FT_SOURCE_ID"}}}
    return day_index, registry


def checked_plan(keys, matches, review, approved, now=NOW, *,
                 day_index=None, registry=None):
    basic_index, basic_registry = _proof()
    return plan_reviewed_ids(keys, matches, review, approved, now,
                             day_index=day_index if day_index is not None else basic_index,
                             confirmed_registry=registry if registry is not None else basic_registry)


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
        ids = checked_plan(list(matches), matches, review,
                                {"schema_version": 1, "pairs": {}}, NOW)
        self.assertEqual(ids, {})
        p = APIFootballResults(key="dummy", max_days=0, reviewed_targets=ids,
                              id_fetch=lambda ids, key: self.fail("No ID calls"))
        self.assertEqual(p.id_requests, 0)

    def test_disabled_adapter_cannot_query_even_approved_ids(self):
        matches, review, approved = fixtures()
        targets = checked_plan(list(matches), matches, review, approved, NOW)
        p = APIFootballResults(key="present-but-disabled", max_days=0,
                              reviewed_targets=targets,
                              id_fetch=lambda ids, key: self.fail("Disabled adapter called"))
        self.assertEqual(p.lookup(signal(1))[1], "api_football_reviewed_id_disabled")
        self.assertEqual(p.id_requests, 0)

    def test_three_human_approved_ids_one_batch_and_strict_90min_ft(self):
        matches, review, approved = fixtures()
        targets = checked_plan(list(matches), matches, review, approved, NOW)
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

    def test_id_fetch_unavailable_has_actual_reason_not_old_name_reason(self):
        matches, review, approved = fixtures()
        key = signal(1)["match_key"]
        targets = checked_plan([key], matches, review, approved, NOW)
        def fail(_ids, _key):
            raise OSError("transient provider failure")
        p = APIFootballResults(key="test", reviewed_targets=targets,
                              id_fetch=fail, max_days=3)
        result, reason = p.lookup(signal(1))
        self.assertIsNone(result)
        self.assertEqual(reason, "api_football_reviewed_id_unavailable")
        self.assertEqual(p.reviewed_outcomes[key], reason)
        self.assertEqual(p.summary()["reviewed_outcomes"][key], reason)
        self.assertEqual(p.id_requests, 1)
        self.assertEqual(p.summary()["requests"], 1)
        # A retry inside the same run does not consume a second request.
        result, reason = p.lookup(signal(1))
        self.assertEqual(reason, "api_football_reviewed_id_missing")
        self.assertEqual(p.id_requests, 1)
        self.assertEqual(p.reviewed_outcomes[key], reason)

    def test_id_response_missing_fixture_is_distinct_from_unavailable(self):
        matches, review, approved = fixtures()
        key = signal(1)["match_key"]
        targets = checked_plan([key], matches, review, approved, NOW)
        p = APIFootballResults(key="test", reviewed_targets=targets,
                              id_fetch=lambda _ids, _key: {}, max_days=3)
        result, reason = p.lookup(signal(1))
        self.assertIsNone(result)
        self.assertEqual(reason, "api_football_reviewed_id_missing")
        self.assertEqual(p.reviewed_outcomes[key], reason)
        self.assertEqual(p.id_requests, 1)

    def test_reviewed_id_does_not_override_team_orientation_and_competition(self):
        matches, review, approved = fixtures()
        targets = checked_plan(list(matches), matches, review, approved, NOW)
        for bad in ("reverse", "league", "aet", "pen", "kickoff",
                    "fixture_id", "goals_disagree", "score_missing",
                    "goals_missing", "status_missing", "missing_team_id"):
            with self.subTest(bad=bad):
                e = event(1, 5001)
                if bad == "reverse":
                    e["teams"]["home"]["id"], e["teams"]["away"]["id"] = 401, 301
                if bad == "league":
                    e["league"]["id"] = 88
                if bad == "aet":
                    e["fixture"]["status"]["short"] = "AET"
                if bad == "pen":
                    e["fixture"]["status"]["short"] = "PEN"
                if bad == "status_missing":
                    e["fixture"]["status"].pop("short")
                if bad == "fixture_id":
                    e["fixture"]["id"] = 999999
                if bad == "missing_team_id":
                    e["teams"]["away"].pop("id")
                if bad == "goals_disagree":
                    e["goals"]["home"] = 4
                if bad == "score_missing":
                    e["score"]["fulltime"] = None
                if bad == "goals_missing":
                    e["goals"] = {}
                if bad == "kickoff":
                    e["fixture"]["date"] = "2026-10-27T17:00:00+00:00"
                p = APIFootballResults(key="test", reviewed_targets=targets,
                    id_fetch=lambda ids, key: {5001: e})
                result, reason = p.lookup(signal(1))
                self.assertIsNone(result)
                self.assertNotEqual(reason, "verified_api_football_ft_reviewed_pair")
                self.assertEqual(p.reviewed_outcomes[signal(1)["match_key"]], reason)

    def test_approval_must_match_real_review_and_no_colliding_ids(self):
        matches, review, approved = fixtures()
        mutant = copy.deepcopy(approved)
        mutant["pairs"][signal(2)["match_key"]]["provider_fixture_id"] = 5001
        self.assertNotIn(signal(1)["match_key"],
                         checked_plan(list(matches), matches, review, mutant, NOW))
        approved["pairs"][signal(1)["match_key"]]["provider_home_team_id"] = 999
        self.assertNotIn(signal(1)["match_key"],
                         checked_plan(list(matches), matches, review, approved, NOW))
        approved["pairs"][signal(1)["match_key"]]["provider_home_team_id"] = 301
        review["games"][0]["possible_duplicates"] = [{"match_key": "potential"}]
        self.assertNotIn(signal(1)["match_key"],
                         checked_plan(list(matches), matches, review, approved, NOW))

    def test_weak_candidates_in_two_other_games_do_not_block_strong_approved(self):
        matches, review, approved = fixtures()
        primary = signal(1)["match_key"]
        review["games"][0]["candidates"][0]["match_strength"] = "STRONG"
        for index in (2, 3):
            extra = dict(signal(1), match_key=f"2026-10-27,other-{index}",
                         home=f"Unrelated {index}", away="Another Side")
            bad = dict(candidate(1, 5001), match_strength="WEAK_REVIEW_ONLY")
            review["games"].append({**extra, "possible_duplicates": [],
                                    "candidates": [bad]})
        index, registry = _proof()
        decisions = {}
        eligible = plan_reviewed_ids([primary], matches, review, approved, NOW,
                day_index=index, confirmed_registry=registry, decisions=decisions)
        self.assertIn(primary, eligible)
        self.assertEqual(decisions[primary]["status"], "ELIGIBLE")
        self.assertEqual(
            decisions[primary]["ignored_weak_diagnostic_match_keys"],
            ["2026-10-27,other-2", "2026-10-27,other-3"])
        # A second independent strong match must still block and explain why.
        review["games"][-1]["candidates"][0]["match_strength"] = "STRONG"
        eligible = plan_reviewed_ids([primary], matches, review, approved, NOW,
                day_index=index, confirmed_registry=registry, decisions=decisions)
        self.assertNotIn(primary, eligible)
        self.assertEqual(decisions[primary]["reason"],
                         "ANOTHER_STRONG_MATCH_CLAIMS_SAME_FIXTURE")
        self.assertEqual(decisions[primary]["competing_match_keys"],
                         ["2026-10-27,other-3"])

    def test_rejected_approval_always_has_explicit_reason(self):
        matches, review, approved = fixtures()
        key = signal(1)["match_key"]
        approved["pairs"][key]["provider_kickoff_utc"] = "2026-10-28T18:00:00+00:00"
        index, registry = _proof()
        decisions = {}
        eligible = plan_reviewed_ids([key], matches, review, approved, NOW,
                day_index=index, confirmed_registry=registry, decisions=decisions)
        self.assertNotIn(key, eligible)
        self.assertEqual(decisions[key]["status"], "REJECTED")
        self.assertEqual(decisions[key]["reason"], "PROVIDER_KICKOFF_OUTSIDE_90M_WINDOW")

    def test_new_approval_not_in_current_queue_reports_deferred(self):
        matches, review, approved = fixtures()
        index, registry = _proof()
        decisions = {}
        self.assertEqual(plan_reviewed_ids(
            [], matches, review, approved, NOW, day_index=index,
            confirmed_registry=registry, decisions=decisions), {})
        self.assertEqual({x["reason"] for x in decisions.values()},
                         {"NOT_SELECTED_IN_CURRENT_FT_QUEUE"})

    def test_cannot_approve_wrong_provider_or_wrong_match_key(self):
        matches, review, approved = fixtures()
        key = signal(1)["match_key"]
        approved["pairs"][key]["provider"] = "goal"
        self.assertNotIn(key, checked_plan(list(matches), matches, review, approved))
        approved["pairs"][key]["provider"] = "api_football"
        approved["pairs"][key]["match_key"] = "another-match"
        self.assertNotIn(key, checked_plan(list(matches), matches, review, approved))

    def test_express_requires_confirmed_kataka_team_or_reviewed_second_source(self):
        matches, review, approved = fixtures()
        old_key = signal(1)["match_key"]
        key = "2026-10-27,33791,86126"
        matches[key] = dict(matches.pop(old_key), match_key=key,
                            home="Express Red Eagles", away="Kataka FC")
        review["games"][0]["match_key"] = key
        review["games"][0]["home"] = "Express Red Eagles"
        approved["pairs"][key] = dict(approved["pairs"].pop(old_key),
                                      match_key=key, home="Express Red Eagles")
        self.assertNotIn(key, checked_plan(list(matches), matches, review, approved))
        approved["pairs"][key]["independent_public_ft"] = {
            "url": "https://www.example.org/ft/express-kataka",
            "home_goals": 1, "away_goals": 2}
        self.assertIn(key, checked_plan(list(matches), matches, review, approved))
        target = checked_plan(list(matches), matches, review, approved)
        p = APIFootballResults(key="fake", reviewed_targets=target,
                              id_fetch=lambda ids, secret: {5001:event(1,5001,h=3,a=2)})
        result, reason = p.lookup(matches[key])
        self.assertIsNone(result)
        self.assertEqual(reason, "api_football_reviewed_public_score_disagrees")

    def test_day_list_must_be_complete_and_fixture_from_same_provider(self):
        matches, review, approved = fixtures()
        empty = {"schema_version": 1, "days": {}}
        self.assertEqual(checked_plan(list(matches), matches, review, approved,
                                     day_index=empty), {})
        partial, reg = _proof()
        partial["days"]["2026-10-27"]["status"] = "INCOMPLETE"
        self.assertEqual(checked_plan(list(matches), matches, review, approved,
                                     day_index=partial, registry=reg), {})

    def test_same_team_twice_in_90min_blocks_reviewed_fixture(self):
        matches, review, approved = fixtures()
        day_index, registry = _proof()
        rows = day_index["days"]["2026-10-27"]["fixtures"]
        clash = dict(rows[0], fixture_id=7000, away_team_id=777,
                     away="Other opponent")
        rows.append(clash)
        day_index["days"]["2026-10-27"]["total_fixtures"] += 1
        self.assertNotIn(signal(1)["match_key"],
            checked_plan(list(matches), matches, review, approved,
                         day_index=day_index, registry=registry))

    def test_unproven_competition_and_confirmed_registry_collision_block(self):
        matches, review, approved = fixtures()
        approved["pairs"][signal(1)["match_key"]]["competition_anchor_fixture_id"] = 8000
        self.assertNotIn(signal(1)["match_key"],
                         checked_plan(list(matches), matches, review, approved))
        approved["pairs"][signal(1)["match_key"]]["competition_anchor_fixture_id"] = 6000
        index, registry = _proof()
        registry["entries"]["api_football:5001"] = {
            "match_key": "another-final", "status": "CONFIRMED_FT_SOURCE_ID"}
        self.assertNotIn(signal(1)["match_key"],
                         checked_plan(list(matches), matches, review, approved,
                                      day_index=index, registry=registry))

    def test_reserves_cannot_be_approved_against_senior_or_u21(self):
        matches, review, approved = fixtures()
        key = signal(1)["match_key"]
        matches[key]["home"] = "Express 1 Reserves"
        review["games"][0]["home"] = "Express 1 Reserves"
        approved["pairs"][key]["home"] = "Express 1 Reserves"
        self.assertNotIn(key, checked_plan(list(matches), matches, review, approved))
        matches[key]["home"] = "Express 1 U21"
        review["games"][0]["home"] = "Express 1 U21"
        approved["pairs"][key]["home"] = "Express 1 U21"
        self.assertNotIn(key, checked_plan(list(matches), matches, review, approved))

    def test_reuse_of_already_confirmed_ft_fixture_id_is_blocked(self):
        matches, review, approved = fixtures()
        matches["old-confirmed"] = {"status": "FINAL", "result": {
            "evidence": "api_football_only",
            "source": "https://v3.football.api-sports.io/fixtures?id=5001"}}
        targets = checked_plan(list(matches), matches, review, approved, NOW)
        self.assertNotIn(signal(1)["match_key"], targets)

    def test_batch_more_than_twenty_or_duplicate_ids_rejected(self):
        for ids in ([], list(range(21)), [10, 10], ["bad"], [0]):
            with self.subTest(ids=ids):
                with self.assertRaises(ValueError):
                    fetch_ids(ids, "fake-key")
        with self.assertRaises(ValueError):
            checked_plan([], {}, {}, {"schema_version": 2, "pairs": {}}, NOW)


if __name__ == "__main__":
    unittest.main()
