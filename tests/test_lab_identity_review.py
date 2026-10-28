"""FT identity candidate diagnostics: no automatic results, new requests, or invented evidence."""
import copy
import json
import unittest
from datetime import datetime, timezone

from h1lab.lab_identity_review import build_queue

NOW = datetime(2026, 10, 28, 19, tzinfo=timezone.utc)
KO = "2026-10-27T16:00:00+00:00"


def row(key, home="İçel İdmanyurdu Spor", away="Mus Spor FC",
        kickoff=KO, status="PENDING"):
    return {"match_key": key, "home": home, "away": away,
            "kickoff_utc": kickoff, "status": status, "attempts": 2,
            "checked_at": "2026-10-28T15:00:00+00:00",
            "provider_reasons": {"goal": "goal_identity_no_core_match"}}


def goal(home="Icel Idmanyurdu Spor", away="Mus Spor",
         kickoff=KO, identifier="123456"):
    return {"homeTeam": {"name": home}, "awayTeam": {"name": away},
            "kickoffUtc": kickoff, "apiId": identifier,
            "homeTeamFtScore": "99", "awayTeamFtScore": "96"}


class IdentityQueue(unittest.TestCase):
    def test_candidate_only_from_existing_cache_never_scores(self):
        key = "2026-10-27,10017282,84806"
        original = {"schema_version": 1, "matches": {key: row(key)}}
        snapshot = copy.deepcopy(original)
        d = build_queue(original, NOW, {"goal": {"2026-10-27": [goal()]}})
        self.assertEqual(original, snapshot)
        self.assertEqual(d["total_eligible"], 1)
        c = d["games"][0]["candidates"][0]
        self.assertEqual(c["provider"], "goal")
        self.assertEqual(c["provider_event_id"], "123456")
        self.assertEqual(c["orientation"], "SAME_ORDER")
        self.assertNotIn("score", json.dumps(c))
        self.assertEqual(d["games"][0]["review_state"], "HUMAN_REVIEW_REQUIRED_NO_SCORE")
        self.assertEqual(d["status"], "FT_IDENTITY_REVIEW_ONLY_NO_AUTOMATIC_MATCH")

    def test_reversed_fixture_requires_review(self):
        key = "2026-10-27,10017282,84806"
        d = build_queue({"matches": {key: row(key)}}, NOW,
                        {"goal": {"2026-10-27": [goal("Mus Spor", "Icel Idmanyurdu Spor")]}})
        self.assertEqual(d["games"][0]["candidates"][0]["orientation"],
                         "REVERSED_TO_REVIEW")
        self.assertIn("HOME_AWAY_ORIENTATION_REVIEW", d["games"][0]["review_flags"])

    def test_age_qualifier_mismatch_not_suggested(self):
        key = "2026-10-27,1,2"
        r = row(key, "Benfica U19", "Sporting U19")
        d = build_queue({"matches": {key: r}}, NOW,
                        {"goal": {"2026-10-27": [goal("Benfica U21", "Sporting U19")]}})
        self.assertFalse(d["games"][0]["candidates"])

    def test_duplicate_possible_but_no_merge(self):
        a, b = "2026-10-27,25158,84806", "2026-10-27,10017282,84806"
        data = {"matches": {a: row(a, "Mersin Idmanyurdu SK"),
                            b: row(b)}}
        d = build_queue(data, NOW, {})
        self.assertEqual(d["total_eligible"], 2)
        self.assertEqual(len(data["matches"]), 2)
        self.assertTrue(all(x["possible_duplicates"] for x in d["games"]))
        self.assertTrue(all(x["ft_status"] == "PENDING" for x in d["games"]))

    def test_carried_candidate_not_a_fresh_observation(self):
        key = "2026-10-27,10017282,84806"
        data = {"matches": {key: row(key)}}
        initial = build_queue(data, NOW, {"goal": {"2026-10-27": [goal()]}})
        next_run = build_queue(data, NOW, {}, previous=initial)
        c = next_run["games"][0]["candidates"][0]
        self.assertFalse(c["observed_this_run"])
        self.assertEqual(c["first_seen_at"], initial["generated_at"])

    def test_identity_change_invalidates_carried_candidates(self):
        key = "2026-10-27,10017282,84806"
        first = build_queue({"matches": {key: row(key)}}, NOW,
                            {"goal": {"2026-10-27": [goal()]}})
        later = build_queue({"matches": {key: row(key, away="Different Club")}},
                            NOW, {}, previous=first)
        self.assertEqual(later["games"][0]["candidates"], [])

    def test_final_future_and_grace_are_not_in_queue(self):
        a, b, c = "a", "b", "c"
        games = {a: row(a, status="FINAL"),
                 b: row(b, kickoff="2026-10-29T16:00:00+00:00"),
                 c: row(c, kickoff="2026-10-28T18:00:00+00:00")}
        d = build_queue({"matches": games}, NOW, {})
        self.assertEqual(d["games"], [])
        self.assertEqual(d["total_eligible"], 0)

    def test_incomplete_bsd_date_cannot_create_candidates(self):
        key = "2026-10-27,10017282,84806"
        event = {"id": 123, "home_team": {"name": "Icel Idmanyurdu Spor"},
                 "away_team": {"name": "Mus Spor"}, "event_date": KO}
        d = build_queue({"matches": {key: row(key)}}, NOW,
                        {"bsd": {"2026-10-27": ([event], "bsd_date_incomplete_pagination")}})
        self.assertFalse(d["games"][0]["candidates"])

    def test_reasons_and_cup_regulation_review_without_score(self):
        key = "2026-10-27,10017282,84806"
        r = row(key)
        r["provider_reasons"]["sportscore"] = "cup_regulation_unverified"
        d = build_queue({"matches": {key: r}}, NOW, {})
        self.assertIn("REGULATION_90M_UNVERIFIED", d["games"][0]["review_flags"])
        self.assertNotIn("home_goals", json.dumps(d))

    def test_invalid_source_identifier_is_not_interpolated_into_link(self):
        key = "2026-10-27,10017282,84806"
        d = build_queue({"matches": {key: row(key)}}, NOW,
                        {"goal": {"2026-10-27": [goal(identifier="123?token=secret")]}})
        c = d["games"][0]["candidates"][0]
        self.assertEqual(c["provider_event_id"], "")
        self.assertEqual(c["reference_url"], "")


if __name__ == "__main__":
    unittest.main()
