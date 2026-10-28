"""Synthetic complete-day API-Football identity proof, with no HTTP or scores."""
import unittest
from copy import deepcopy
from datetime import datetime, timezone

from h1lab.lab_ft_day_identity import build_index, fixture_index, check_day_identity

NOW = datetime(2026, 10, 28, 23, 40, tzinfo=timezone.utc)
DAY = "2026-10-27"


def event(fid=11, hid=1, aid=2, ko="2026-10-27T18:00:00+00:00"):
    return {"fixture": {"id": fid, "date": ko, "status": {"short": "FT"}},
            "league": {"id": 77, "name": "Reserve League"},
            "teams": {"home": {"id": hid, "name": "Home Reserves"},
                      "away": {"id": aid, "name": "Away Reserves"}},
            "goals": {"home": 2, "away": 1},
            "score": {"fulltime": {"home": 2, "away": 1}}}


def approval():
    return {"provider_fixture_id": 11,
            "provider_home_team_id": 1, "provider_away_team_id": 2,
            "provider_competition_id": 77,
            "provider_kickoff_utc": "2026-10-27T18:00:00+00:00"}


class FullDayIndexTests(unittest.TestCase):
    def test_complete_no_scores_persisted_and_replay(self):
        first = build_index({"schema_version": 1, "days": {}},
                            {DAY: [event()]}, NOW)
        row = first["days"][DAY]
        self.assertEqual(row["status"], "COMPLETE")
        self.assertEqual(row["total_fixtures"], 1)
        self.assertEqual(len(row["fixtures"]), 1)
        self.assertNotIn("goals", str(row).lower())
        self.assertNotIn("score", str(row).lower())
        self.assertIsNone(check_day_identity(first, approval()))
        second = build_index(first, {}, NOW)
        self.assertEqual(first, second)

    def test_incomplete_day_cannot_certify_no_team_collision(self):
        bad = event()
        del bad["league"]["id"]
        idx = build_index({"schema_version": 1, "days": {}},
                          {DAY: [bad]}, NOW)
        self.assertEqual(idx["days"][DAY]["status"], "INCOMPLETE")
        self.assertIsNone(fixture_index(idx, DAY))
        self.assertEqual(check_day_identity(idx, approval()),
                         "DAY_IDENTITY_COMPLETE_LIST_MISSING")

    def test_team_collision_blocks_both_sides_within_90m(self):
        for aid in (1, 2):
            idx = build_index({"schema_version": 1, "days": {}},
                              {DAY: [event(), event(fid=12, hid=aid, aid=50,
                                ko="2026-10-27T19:20:00+00:00")]}, NOW)
            self.assertEqual(check_day_identity(idx, approval()),
                             "DAY_IDENTITY_TEAM_COLLISION")

    def test_matches_outside_window_do_not_block(self):
        idx = build_index({"schema_version": 1, "days": {}},
                          {DAY: [event(), event(fid=12, hid=1, aid=50,
                            ko="2026-10-27T19:31:00+00:00")]}, NOW)
        self.assertIsNone(check_day_identity(idx, approval()))

    def test_inconsistent_team_id_or_event_id_rejected(self):
        idx = build_index({"schema_version": 1, "days": {}},
                          {DAY: [event()]}, NOW)
        changed = dict(approval(), provider_away_team_id=8)
        self.assertEqual(check_day_identity(idx, changed),
                         "DAY_IDENTITY_APPROVAL_DIFFERS_FROM_COMPLETE_LIST")
        changed = dict(approval(), provider_fixture_id=999)
        self.assertEqual(check_day_identity(idx, changed),
                         "DAY_IDENTITY_FIXTURE_ABSENT_OR_DUPLICATE")

    def test_duplicate_provider_ids_mark_entire_day_incomplete(self):
        idx = build_index({"schema_version": 1, "days": {}},
                          {DAY: [event(), event()]}, NOW)
        self.assertEqual(idx["days"][DAY]["status"], "INCOMPLETE")
        self.assertIsNone(fixture_index(idx, DAY))

    def test_failed_day_fetch_preserves_prior_proof(self):
        good = build_index({"schema_version": 1, "days": {}},
                           {DAY: [event()]}, NOW)
        same = build_index(good, {DAY: None}, NOW)
        self.assertEqual(good, same)

    def test_source_score_mutations_never_change_day_identity_proof(self):
        original = event()
        changed = deepcopy(original)
        changed["score"]["fulltime"] = {"home": 99, "away": 0}
        changed["goals"] = {"home": 99, "away": 0}
        a = build_index({"schema_version": 1, "days": {}},
                        {DAY: [original]}, NOW)
        b = build_index({"schema_version": 1, "days": {}},
                        {DAY: [changed]}, NOW)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
