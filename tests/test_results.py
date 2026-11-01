import unittest
from io import BytesIO
from urllib.error import HTTPError
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from h1lab.results import (
    TheSportsDBProviderError, api_events, choose_result, norm_team,
    parse_provider_events, verified_score, sync, plan_due_signals,
    recent_tsdb_access_denial, TSDBPacer, TSDB_MIN_INTERVAL_SECONDS,
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
    """Queue-order, cooldown and 429 semantics. These fixtures are days old, so they pin the
    legacy 30-day horizon; the 24h retry policy v2 has its own tests in test_h1_retry_horizon."""

    def setUp(self):
        patcher = patch("h1lab.results.H1_RETRY_HORIZON", timedelta(days=30))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_normalization_preserves_age_groups(self):
        self.assertEqual(norm_team("SV Werder Bremen"), norm_team("Werder Bremen"))
        self.assertNotEqual(norm_team("Bristol City U21"), norm_team("Bristol City"))

    def test_club_designator_normalization_does_not_merge_youth_or_reserves(self):
        self.assertEqual(norm_team("FC Córdoba CF"), norm_team("Córdoba"))
        self.assertEqual(norm_team("SC Farense"), norm_team("Farense"))
        self.assertNotEqual(norm_team("SC Farense U19"), norm_team("SC Farense"))
        self.assertNotEqual(norm_team("Real Madrid CF"), norm_team("Real Madrid B"))
        self.assertNotEqual(norm_team("Milan"), norm_team("Inter Milan"))
        self.assertEqual(norm_team("CF"), "cf")

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

    def test_tsdb_pacer_bounded_start_to_start_spacing(self):
        fake_time=[100.0]
        sleeps=[]
        def sleep(amount):
            sleeps.append(amount)
            fake_time[0] += amount
        pacer=TSDBPacer(clock=lambda: fake_time[0], sleep=sleep)
        pacer.before_call()
        self.assertEqual(sleeps,[])
        fake_time[0] += 0.7
        pacer.before_call()
        self.assertAlmostEqual(sleeps[0],TSDB_MIN_INTERVAL_SECONDS-0.7)
        fake_time[0] += TSDB_MIN_INTERVAL_SECONDS+0.1
        pacer.before_call()
        self.assertEqual(len(sleeps),1)

    def test_tsdb_pacing_only_before_real_nonblocked_fallback_calls(self):
        now=KO+timedelta(days=2)
        signals=[{**SIGNAL,"match_key":f"paced-{i}"} for i in range(4)]
        events=[]
        class FakePacer:
            def before_call(self):
                events.append("pace")
        def reject(signal):
            events.append(signal["match_key"])
            if signal["match_key"]=="paced-1":
                raise TheSportsDBProviderError("thesportsdb_http_429",stop_cycle=True)
            return []
        with patch.dict("os.environ",{"BSD_API_KEY":"synthetic"}), \
             patch("h1lab.bsd.find_result",return_value=(None,"bsd_empty_finished_list")), \
             patch("h1lab.results.read_state",return_value={"signals":signals}), \
             patch("h1lab.results.read_rows",return_value=[]), \
             patch("h1lab.results.load_results",return_value={}), \
             patch("h1lab.results.read_audit",return_value={}), \
             patch("h1lab.results.save"), \
             patch("h1lab.core.dump_json"):
            sync(now=now,search=reject,pace=FakePacer())
        # No artificial waiting/calls after a real HTTP 429, but BSD
        # continues independent checks for the remaining H1 candidates.
        self.assertEqual(events,["pace","paced-0","pace","paced-1"])
        with self.assertRaises(ValueError):
            TSDBPacer(interval=-1)

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


    def test_prior_real_429_gates_only_four_hours_without_refresh(self):
        now = KO + timedelta(days=2)
        denial = now - timedelta(hours=1)
        audit = {
            "real_429": {
                "checked_at": denial.isoformat(),
                "status": "pending",
                "reason": "bsd:bsd_no_exact_match;thesportsdb:thesportsdb_http_429",
            },
            "skip_after": {
                "checked_at": (now - timedelta(minutes=3)).isoformat(),
                "status": "pending",
                "reason": "bsd:bsd_no_exact_match;thesportsdb:thesportsdb_circuit_open",
                "thesportsdb_reason": "thesportsdb_circuit_open",
            },
        }
        gate = recent_tsdb_access_denial(audit, now)
        self.assertEqual(gate["reason"], "thesportsdb_http_429")
        self.assertEqual(gate["observed_at_utc"], denial.isoformat(timespec="seconds"))
        self.assertEqual(gate["retry_not_before_utc"],
                         (denial + timedelta(hours=4)).isoformat(timespec="seconds"))
        self.assertIsNone(recent_tsdb_access_denial(
            audit, denial + timedelta(hours=4)))

    def test_non_provider_denials_and_bad_clock_never_renew_gate(self):
        now = KO + timedelta(days=2)
        for reason in ("thesportsdb_unavailable", "thesportsdb_circuit_open",
                       "thesportsdb_http_404", "thesportsdb_no_event",
                       {"error": "thesportsdb_http_429"}):
            for stamp in (now.isoformat(), "not-a-time",
                          (now+timedelta(hours=1)).isoformat(),
                          now.replace(tzinfo=None).isoformat()):
                audit = {"x":{"checked_at":stamp,"thesportsdb_reason":reason}}
                self.assertIsNone(recent_tsdb_access_denial(audit, now))
        # Genuine 401/403 access refusals, unlike a generic error, qualify.
        for reason in ("thesportsdb_http_401", "thesportsdb_http_403"):
            self.assertEqual(recent_tsdb_access_denial(
                {"x":{"checked_at":now.isoformat(),"thesportsdb_reason":reason}},
                now)["reason"], reason)

    def test_persisted_429_skips_tsdb_but_bsd_still_checks_every_selected_fixture(self):
        now = KO + timedelta(days=2)
        signals = [{**SIGNAL,"match_key":f"next-cycle-{i}"} for i in range(3)]
        previous = {"old":{"checked_at":(now-timedelta(hours=1)).isoformat(),
                           "reason":"bsd:bsd_no_exact_match;thesportsdb:thesportsdb_http_429"}}
        with patch.dict("os.environ",{"BSD_API_KEY":"synthetic"}), \
             patch("h1lab.bsd.find_result",return_value=(None,"bsd_no_exact_match")) as bsd, \
             patch("h1lab.results.read_state",return_value={"signals":signals}), \
             patch("h1lab.results.read_rows",return_value=[]), \
             patch("h1lab.results.load_results",return_value={}), \
             patch("h1lab.results.read_audit",return_value=previous), \
             patch("h1lab.results.save"), \
             patch("h1lab.core.dump_json") as written:
            sync(now=now, search=lambda x:self.fail("No TSDB HTTP during 429 cooldown"))
        self.assertEqual(bsd.call_count,3)
        new_audit=written.call_args.args[1]
        for signal in signals:
            row=new_audit[signal["match_key"]]
            self.assertEqual(row["thesportsdb_reason"],"thesportsdb_circuit_open")
            self.assertEqual(row["status"],"pending")
        # A later look-up at the end of the original four hours is permitted.
        self.assertIsNone(recent_tsdb_access_denial(
            new_audit, now + timedelta(hours=3)))

    def test_no_bsd_and_persisted_denial_does_not_mark_unqueried_as_checked(self):
        now = KO + timedelta(days=2)
        previous = {"old":{"checked_at":(now-timedelta(minutes=40)).isoformat(),
                           "reason":"bsd:bsd_no_exact_match;thesportsdb:thesportsdb_http_429"}}
        with patch.dict("os.environ",{"BSD_API_KEY":""}), \
             patch("h1lab.results.read_state",return_value={"signals":[SIGNAL]}), \
             patch("h1lab.results.read_rows",return_value=[]), \
             patch("h1lab.results.load_results",return_value={}), \
             patch("h1lab.results.read_audit",return_value=previous), \
             patch("h1lab.results.save"), \
             patch("h1lab.core.dump_json") as written:
            sync(now=now,search=lambda x:self.fail("TSDB blocked by true prior 429"))
        written.assert_not_called()
        self.assertNotIn(SIGNAL["match_key"],previous)

    def test_429_is_audited_even_if_independent_bsd_verifies_final(self):
        now = KO + timedelta(days=2)
        bsd_score={"match_key":SIGNAL["match_key"],"status":"final",
                   "home_goals":2,"away_goals":1,
                   "source":"https://sports.bzzoiro.com/api/v2/events/123/"}
        def blocked(_):
            raise TheSportsDBProviderError("thesportsdb_http_429",stop_cycle=True)
        with patch.dict("os.environ",{"BSD_API_KEY":"synthetic"}), \
             patch("h1lab.bsd.find_result",return_value=(bsd_score,"verified_bsd_ft")), \
             patch("h1lab.results.read_state",return_value={"signals":[SIGNAL]}), \
             patch("h1lab.results.read_rows",return_value=[]), \
             patch("h1lab.results.load_results",return_value={}), \
             patch("h1lab.results.read_audit",return_value={}), \
             patch("h1lab.results.write_rows") as stored, \
             patch("h1lab.results.save"), \
             patch("h1lab.core.dump_json") as written:
            sync(now=now,search=blocked)
        self.assertEqual(stored.call_count,1)
        record=written.call_args.args[1][SIGNAL["match_key"]]
        self.assertEqual(record["reason"],"confirmed_bsd_only")
        self.assertEqual(record["thesportsdb_reason"],"thesportsdb_http_429")
        self.assertIsNotNone(recent_tsdb_access_denial(
            written.call_args.args[1],now))


if __name__ == "__main__":
    unittest.main()
