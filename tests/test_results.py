import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from h1lab.results import choose_result, norm_team, verified_score, sync

UTC = timezone.utc
KO = datetime(2026, 10, 27, 19, 45, tzinfo=UTC)
SIGNAL = {
    "home": "Borussia Dortmund",
    "away": "SV Werder Bremen",
    "kickoff_utc": KO.isoformat(),
    "match_key": "test,194,203",
}
EVENT = {
    "idEvent": "123456",
    "strSport": "Soccer",
    "strHomeTeam": "Borussia Dortmund",
    "strAwayTeam": "Werder Bremen",
    "strTimestamp": "2026-10-27T19:45:00",
    "dateEvent": "2026-10-27",
    "strStatus": "FT",
    "strPostponed": "no",
    "intHomeScore": "2",
    "intAwayScore": "1",
    "intHomeScoreExtra": None,
    "intAwayScoreExtra": None,
    "strResult": "",
}


class ResultMatching(unittest.TestCase):
    def test_normalization_preserves_age_groups(self):
        self.assertEqual(norm_team("SV Werder Bremen"), norm_team("Werder Bremen"))
        self.assertNotEqual(norm_team("Bristol City U21"), norm_team("Bristol City"))

    def test_verified_regulation_final(self):
        found, reason = verified_score(SIGNAL, dict(EVENT))
        self.assertEqual(reason, "verified_ft")
        self.assertEqual(found["home_goals"], 2)
        self.assertEqual(found["away_goals"], 1)
        self.assertEqual(found["match_key"], SIGNAL["match_key"])

    def test_pending_and_extra_time_never_settle(self):
        for override in (
            {"strStatus": "NS"},
            {"strStatus": "AET"},
            {"intHomeScoreExtra": "1"},
            {"strResult": "Winner after extra time"},
            {"strResult": "won on penalties"},
            {"strPostponed": "yes"},
        ):
            with self.subTest(override=override):
                found, reason = verified_score(SIGNAL, {**EVENT, **override})
                self.assertIsNone(found)
                self.assertNotEqual(reason, "verified_ft")

    def test_wrong_teams_and_kickoff_rejected(self):
        for override in (
            {"strHomeTeam": "Bayern Munich"},
            {"strAwayTeam": "Werder Bremen U21"},
            {"strTimestamp": "2026-10-28T19:45:00"},
        ):
            found, reason = verified_score(SIGNAL, {**EVENT, **override})
            self.assertIsNone(found)

    def test_missing_score_and_unknown_sport(self):
        self.assertIsNone(verified_score(SIGNAL, {**EVENT, "intHomeScore": None})[0])
        self.assertIsNone(verified_score(SIGNAL, {**EVENT, "strSport": "Basketball"})[0])

    def test_no_event_keeps_pending(self):
        self.assertEqual(choose_result(SIGNAL, []), (None, "no_event"))

    def test_more_than_one_exact_match_is_ambiguous(self):
        self.assertEqual(choose_result(SIGNAL, [EVENT, EVENT])[1], "ambiguous_event")

    def test_sync_is_idempotent_with_verified_score(self):
        state = {"signals": [SIGNAL], "alerts": [], "tickets": [], "last_id": 1}
        now = KO + timedelta(hours=4)
        with patch("h1lab.results.read_state", return_value=state), \
             patch("h1lab.results.read_rows", return_value=[]), \
             patch("h1lab.results.load_results", return_value={}), \
             patch("h1lab.results.read_audit", return_value={}), \
             patch("h1lab.results.write_rows") as write_rows, \
             patch("h1lab.core.dump_json") as dump_audit, \
             patch("h1lab.results.save") as save:
            sync(now=now, search=lambda _: [EVENT])
            write_rows.assert_called_once()
            self.assertEqual(write_rows.call_args.args[0][0]["home_goals"], 2)
            dump_audit.assert_called_once()
            save.assert_called_once()

    def test_future_fixture_is_not_queried(self):
        state = {"signals": [SIGNAL], "alerts": [], "tickets": [], "last_id": 1}
        with patch("h1lab.results.read_state", return_value=state), \
             patch("h1lab.results.read_rows", return_value=[]), \
             patch("h1lab.results.load_results", return_value={}), \
             patch("h1lab.results.read_audit", return_value={}), \
             patch("h1lab.results.write_rows") as write_rows, \
             patch("h1lab.core.dump_json") as dump_audit, \
             patch("h1lab.results.save"):
            sync(now=KO + timedelta(minutes=15),
                 search=lambda _: self.fail("future fixture should not be queried"))
            write_rows.assert_not_called()
            dump_audit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
