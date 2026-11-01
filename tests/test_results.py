import unittest
from io import BytesIO
from urllib.error import HTTPError
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from h1lab.results import (
    TheSportsDBProviderError, api_events, choose_result, norm_team,
    parse_provider_events, verified_score, sync, plan_due_signals,
)

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

    def test_unchecked_eligible_games_are_prioritised_before_retries(self):
        now = KO + timedelta(days=5)
        signals = [
            {**SIGNAL, "match_key": f"old-retry-{i}",
             "kickoff_utc": (KO + timedelta(hours=i)).isoformat()}
            for i in range(4)
        ]
        signals += [
            {**SIGNAL, "match_key": f"first-{i}",
             "kickoff_utc": (KO + timedelta(hours=5 + i)).isoformat()}
            for i in range(25)
        ]
        audit = {f"old-retry-{i}": {
            "checked_at": (now - timedelta(hours=5)).isoformat(),
            "status": "pending",
        } for i in range(4)}
        chosen, diag = plan_due_signals(signals, set(), audit, now)
        self.assertEqual(len(chosen), 20)
        self.assertEqual([s["match_key"] for s in chosen],
                         [f"first-{i}" for i in range(20)])
        self.assertEqual(diag, {"eligible": 29, "first_checks_due": 25,
                                "retries_due": 4, "deferred_by_limit": 9})

    def test_first_check_plan_respects_cooldown_grace_and_horizon(self):
        now = KO + timedelta(days=6)
        signals = [
            {**SIGNAL, "match_key": "eligible-old",
             "kickoff_utc": (now - timedelta(days=5)).isoformat()},
            {**SIGNAL, "match_key": "recent-retry",
             "kickoff_utc": (now - timedelta(days=3)).isoformat()},
            {**SIGNAL, "match_key": "older-retry",
             "kickoff_utc": (now - timedelta(days=4)).isoformat()},
            {**SIGNAL, "match_key": "future",
             "kickoff_utc": (now + timedelta(days=1)).isoformat()},
            {**SIGNAL, "match_key": "in-grace",
             "kickoff_utc": (now - timedelta(hours=2)).isoformat()},
            {**SIGNAL, "match_key": "expired",
             "kickoff_utc": (now - timedelta(days=31)).isoformat()},
            {**SIGNAL, "match_key": "resolved",
             "kickoff_utc": (now - timedelta(days=2)).isoformat()},
        ]
        audit = {
            "recent-retry": {"checked_at": (now - timedelta(hours=2)).isoformat()},
            "older-retry": {"checked_at": (now - timedelta(hours=5)).isoformat()},
        }
        chosen, diag = plan_due_signals(signals, {"resolved"}, audit, now, limit=2)
        self.assertEqual([s["match_key"] for s in chosen],
                         ["eligible-old", "older-retry"])
        self.assertEqual(diag["eligible"], 2)
        self.assertEqual(diag["deferred_by_limit"], 0)

    def test_unchecked_first_check_selection_is_stable_and_idempotent(self):
        now = KO + timedelta(days=3)
        signal = {**SIGNAL, "match_key": "not-yet-checked"}
        retry = {**SIGNAL, "match_key": "previously-checked"}
        audit = {"previously-checked": {
            "checked_at": (now - timedelta(hours=5)).isoformat()}}
        selected, _ = plan_due_signals([retry, signal], set(), audit, now, 1)
        self.assertEqual(selected[0]["match_key"], "not-yet-checked")
        audit["not-yet-checked"] = {"checked_at": now.isoformat()}
        selected, counts = plan_due_signals([retry, signal], set(), audit, now, 1)
        self.assertEqual(selected[0]["match_key"], "previously-checked")
        self.assertEqual(counts["first_checks_due"], 0)

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


    def test_200_with_provider_errors_is_not_an_empty_search(self):
        for payload in (
            {"event": None, "errors": {"access": "forbidden"}},
            {"event": [], "error": "limit"},
            {"event": None, "message": "API blocked"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(TheSportsDBProviderError) as raised:
                    parse_provider_events(payload)
                self.assertTrue(raised.exception.stop_cycle)
        self.assertEqual(parse_provider_events({"event": None}), [])
        self.assertEqual(parse_provider_events({"event": []}), [])

    def test_thesportsdb_http_429_is_classified_without_body(self):
        with patch("h1lab.results.urlopen", side_effect=HTTPError(
            "https://example.invalid", 429, "rate limit", None, None
        )):
            with self.assertRaises(TheSportsDBProviderError) as raised:
                api_events(SIGNAL)
        self.assertEqual(raised.exception.reason, "thesportsdb_http_429")
        self.assertTrue(raised.exception.stop_cycle)

    def test_tsdb_semantic_error_from_http_200_is_not_no_event(self):
        response = BytesIO(b'{"event":null,"errors":{"rate":"blocked"}}')
        response.status = 200
        with patch("h1lab.results.urlopen", return_value=response):
            with self.assertRaises(TheSportsDBProviderError) as raised:
                api_events(SIGNAL)
        self.assertEqual(raised.exception.reason, "thesportsdb_semantic_rejection")

    def test_blocked_tsdb_cycle_does_not_repeat_blocked_provider_calls(self):
        signals = [{**SIGNAL, "match_key": f"blocked-{i}",
                    "kickoff_utc": (KO + timedelta(minutes=i)).isoformat()}
                   for i in range(4)]
        attempts = []
        def blocked_search(signal):
            attempts.append(signal["match_key"])
            raise TheSportsDBProviderError("thesportsdb_http_403", stop_cycle=True)

        with patch.dict("os.environ", {"BSD_API_KEY": "fixture-token"}), \
             patch("h1lab.bsd.find_result", return_value=(None, "bsd_no_exact_match")) as bsd, \
             patch("h1lab.results.read_state", return_value={"signals": signals}), \
             patch("h1lab.results.read_rows", return_value=[]), \
             patch("h1lab.results.load_results", return_value={}), \
             patch("h1lab.results.read_audit", return_value={}), \
             patch("h1lab.results.save"), \
             patch("h1lab.core.dump_json") as dump:
            sync(now=KO + timedelta(days=1), search=blocked_search)
        self.assertEqual(attempts, ["blocked-0"])
        self.assertEqual(bsd.call_count, 4)
        audit = dump.call_args.args[1]
        self.assertIn("thesportsdb:thesportsdb_http_403", audit["blocked-0"]["reason"])
        self.assertIn("thesportsdb:thesportsdb_circuit_open", audit["blocked-1"]["reason"])
        self.assertEqual(len(audit), 4)
        self.assertTrue(all(item["status"] == "pending" for item in audit.values()))

    def test_skip_without_any_supplier_does_not_create_false_cooldown(self):
        signals = [{**SIGNAL, "match_key": f"unattempted-{i}",
                    "kickoff_utc": (KO + timedelta(minutes=i)).isoformat()}
                   for i in range(3)]
        attempts = []
        def blocked_search(signal):
            attempts.append(signal["match_key"])
            raise TheSportsDBProviderError("thesportsdb_http_429", stop_cycle=True)

        with patch.dict("os.environ", {"BSD_API_KEY": ""}), \
             patch("h1lab.results.read_state", return_value={"signals": signals}), \
             patch("h1lab.results.read_rows", return_value=[]), \
             patch("h1lab.results.load_results", return_value={}), \
             patch("h1lab.results.read_audit", return_value={}), \
             patch("h1lab.results.save"), \
             patch("h1lab.core.dump_json") as dump:
            sync(now=KO + timedelta(days=1), search=blocked_search)
        self.assertEqual(attempts, ["unattempted-0"])
        self.assertEqual(set(dump.call_args.args[1]), {"unattempted-0"})


if __name__ == "__main__":
    unittest.main()
