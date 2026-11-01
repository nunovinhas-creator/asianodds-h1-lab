"""Provider-history gate: no HTTP and no inferred access restrictions."""
import unittest
from datetime import datetime, timezone, timedelta
from h1lab.lab_api_football_access import (evolve_access, restriction_for_day,
    restriction_for_fixture_id, restore_access_from_audit, account_suspension_cooldown)
from h1lab.lab_ft_rotation import choose_days

NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
OLD = "2026-10-27"
OK = "2026-10-28"


def error(text, *, category="PROVIDER_ERRORS", status=200):
    return {"category": category, "http_status": status, "provider_errors": text}


class ProviderHistoryAccessTests(unittest.TestCase):
    def test_real_free_plan_denial_blocks_only_the_rejected_date(self):
        msg = "plan: Free plans do not have access to this date, try from 2026-10-29 to 2026-10-31."
        state = evolve_access({"schema_version": 1}, {"2026-10-28": error(msg)},
                              NOW + timedelta(days=1))
        self.assertEqual(restriction_for_day(state, "2026-10-28", NOW),
                         "PROVIDER_CONFIRMED_DAY_HISTORY_RESTRICTION")
        self.assertIsNone(restriction_for_day(state, "2026-10-29", NOW))
        self.assertIsNone(restriction_for_fixture_id(state, "2026-10-28", NOW))

    def test_restore_reuses_real_denial_without_retimestamp_or_id_restriction(self):
        stamp = NOW.isoformat()
        audit = {"schema_version":1, "runs":[{"utc":stamp,"providers":{
            "api_football":{"date_errors":{OLD:error(
                "Free plans do not have access to this date")}}}}]}
        later = NOW + timedelta(hours=1)
        restored = restore_access_from_audit({"schema_version":1}, audit, later)
        note = restored["confirmed_restrictions"][OLD]
        self.assertEqual(note["checked_at_utc"], NOW.isoformat(timespec="seconds"))
        self.assertEqual(restore_access_from_audit(restored, audit, later),restored)
        self.assertIsNone(restriction_for_fixture_id(restored, OLD, later))
        matches = {"old":{"kickoff_utc":OLD+"T12:00:00Z"},
                   "new":{"kickoff_utc":OK+"T12:00:00Z"}}
        planned = choose_days(list(matches),matches,{
            "schema_version":1,"api_football_history_access":restored},later,{"api_football"})
        self.assertEqual(planned["api_football"],[OK])

    def test_quota_denial_and_future_or_naive_audit_do_not_suspend_history(self):
        for stamp in (NOW.isoformat(), (NOW+timedelta(days=1)).isoformat(),
                      NOW.replace(tzinfo=None).isoformat()):
            audit={"schema_version":1,"runs":[{"utc":stamp,"providers":{
                "api_football":{"date_errors":{OLD:error(
                    "Free plan dates do not have access: daily quota exhausted")}}}}]}
            out=restore_access_from_audit({"schema_version":1},audit,NOW)
            self.assertEqual(out["confirmed_restrictions"],{})

    def test_timeouts_and_generic_http_errors_never_block(self):
        initial = {"schema_version": 1, "confirmed_restrictions": {}}
        for e in (
            error("", category="HTTP_ERROR", status=403),
            error("free plan exceeded daily request quota"),
            error("free plan dates inaccessible", category="TIMEOUT"),
            error("rate limit: free plan dates unavailable"),
            error("You are not authorized", category="HTTP_ERROR", status=401),
            error("invalid JSON", category="INVALID_JSON"),
            error("Season 2024 not allowed"),
        ):
            with self.subTest(error=e):
                state = evolve_access(initial, {OLD: e}, NOW)
                self.assertIsNone(restriction_for_day(state, OLD, NOW))
                self.assertEqual(state["confirmed_restrictions"], {})

    def test_explicit_yesterday_to_tomorrow_rule_blocks_older_days(self):
        message = "Free plan fixtures dates only available from yesterday to tomorrow"
        state = evolve_access({"schema_version": 1},
            {OLD: error(message)}, NOW)
        self.assertEqual(restriction_for_day(state, OLD, NOW),
                         "PROVIDER_CONFIRMED_CALENDAR_HISTORY_LIMIT")
        self.assertIsNone(restriction_for_day(state, OK, NOW))
        self.assertEqual(restriction_for_day(state, OK, NOW+timedelta(days=1)),
                         "PROVIDER_CONFIRMED_CALENDAR_HISTORY_LIMIT")
        self.assertEqual(state["confirmed_restrictions"][OLD]["scope"], "CALENDAR_WINDOW")

    def test_unqualified_explicit_historical_plan_refusal_blocks_only_failed_day(self):
        msg = "Free plan: historical date 2026-10-27 is not available"
        state = evolve_access({"schema_version": 1},
            {OLD: error(msg)}, NOW)
        self.assertEqual(restriction_for_day(state, OLD, NOW),
                         "PROVIDER_CONFIRMED_DAY_HISTORY_RESTRICTION")
        # The distinct ID endpoint is only prudentially deferred for this date;
        # there is no evidence for a rolling one-day plan window.
        self.assertIsNone(restriction_for_day(state, OK, NOW))
        self.assertIsNone(restriction_for_day(state, "2026-10-26", NOW))

    def test_date_list_denial_cannot_disable_single_fixture_lookup(self):
        state = evolve_access({"schema_version": 1},
            {OLD: error("Free plan fixtures dates only available from yesterday to tomorrow")}, NOW)
        self.assertIsNotNone(restriction_for_day(state, OLD, NOW))
        self.assertIsNone(restriction_for_fixture_id(state, OLD, NOW))
        # In particular, never incorrectly turn a date-list error into an
        # ID endpoint refusal for the human-reviewed fixture 1612137.

    def test_nonrestrictive_http_403_does_not_trigger_by_age(self):
        state = evolve_access({"schema_version": 1},
            {OLD: error("User forbidden", category="HTTP_ERROR", status=403)}, NOW)
        self.assertIsNone(restriction_for_day(state, OLD, NOW))

    def test_rotation_fills_available_days_without_wasting_slot(self):
        matches = {f"2026-10-{x:02d},game": {
            "kickoff_utc":f"2026-10-{x:02d}T12:00:00+00:00"}
            for x in (26, 27, 28, 29)}
        keys=list(matches)
        previous = {"schema_version": 1, "providers": {"api_football": {}},
            "usage": {}, "api_football_history_access": evolve_access(
                {"schema_version": 1}, {OLD: error(
                    "Free plan fixtures dates only available from yesterday to tomorrow")}, NOW)}
        planned = choose_days(keys, matches, previous, NOW, {"api_football"})
        self.assertEqual(planned["api_football"], ["2026-10-28", "2026-10-29"])
        self.assertEqual(planned["goal"], [])

    def test_without_provider_proof_rotation_remains_unchanged(self):
        matches = {f"2026-10-{x:02d},game": {
            "kickoff_utc":f"2026-10-{x:02d}T12:00:00+00:00"}
            for x in (26, 27, 28, 29)}
        previous = {"schema_version": 1, "providers": {"api_football": {}}, "usage": {}}
        planned = choose_days(list(matches), matches, previous, NOW, {"api_football"})
        self.assertIn("2026-10-27", planned["api_football"])

    def test_invalid_fresh_error_does_not_erase_prior_verified_limit(self):
        old = evolve_access({"schema_version": 1},
            {OLD:error("Free plan fixture dates only yesterday to tomorrow")}, NOW)
        new = evolve_access(old, {OK:error("server timeout", category="TIMEOUT")}, NOW)
        self.assertEqual(new["confirmed_restrictions"], old["confirmed_restrictions"])


    def test_provider_confirmed_account_suspension_blocks_all_endpoints_temporarily(self):
        stamp = datetime(2026, 11, 1, 11, 36, 24, tzinfo=timezone.utc)
        audit = {"schema_version": 1, "runs": [{
            "utc": stamp.isoformat(),
            "providers": {"api_football": {"id_errors": {
                "2026-10-31,135,106": error(
                    "access: Your account is suspended, check on [url]")
            }}},
        }]}
        decision = account_suspension_cooldown(audit, stamp + timedelta(minutes=30))
        self.assertEqual(decision["reason"], "PROVIDER_CONFIRMED_ACCOUNT_SUSPENSION")
        self.assertEqual(decision["observed_at_utc"], "2026-11-01T11:36:24+00:00")
        self.assertEqual(decision["retry_not_before_utc"], "2026-11-01T15:36:24+00:00")
        self.assertIsNone(account_suspension_cooldown(
            audit, stamp + timedelta(hours=4)))
        # A new run without an actual provider response must never reset TTL.
        audit["runs"].append({"utc": (stamp + timedelta(hours=2)).isoformat(),
                              "providers": {"api_football": {"requests": 0}}})
        self.assertEqual(account_suspension_cooldown(
            audit, stamp + timedelta(hours=3)), decision)

    def test_non_account_denials_do_not_block_api_football(self):
        now = datetime(2026, 11, 1, 11, tzinfo=timezone.utc)
        messages = [
            error("Free plans do not have access to this date"),
            error("Free plans do not have access to the Ids parameter"),
            error("daily quota exceeded"),
            error("generic forbidden", category="HTTP_ERROR", status=403),
            error("Your account is suspended", category="TIMEOUT"),
            error("suspended account", category="PROVIDER_ERRORS", status=200),
        ]
        for item in messages:
            with self.subTest(item=item):
                audit = {"schema_version":1, "runs":[{
                    "utc":now.isoformat(), "providers":{
                        "api_football":{"date_errors":{"2026-10-30":item}}}}]}
                self.assertIsNone(account_suspension_cooldown(audit, now))

    def test_suspension_requires_persisted_credible_clock(self):
        now = datetime(2026, 11, 1, 11, tzinfo=timezone.utc)
        denied = error("access: Your account is suspended")
        for stamp in ("not-time", "2026-11-01T13:00:00Z",
                      "2026-10-31T00:00:00Z", "2026-11-01T11:00:00"):
            audit = {"schema_version":1, "runs":[{
                "utc":stamp, "providers":{"api_football":{
                    "id_errors":{"some-fixture":denied}}}}]}
            with self.subTest(stamp=stamp):
                self.assertIsNone(account_suspension_cooldown(audit, now))

    def test_real_audit_replays_account_denial_without_network(self):
        import json
        from pathlib import Path
        audit_file = Path(__file__).resolve().parents[1]/"data/lab/ft-api-audit.json"
        audit = json.loads(audit_file.read_text(encoding="utf-8"))
        # The real cached denial may age out naturally; test at its original
        # observation instant rather than depending on wall clock in CI.
        confirmed = []
        for run in audit["runs"]:
            for detail in (run.get("providers", {}).get("api_football", {})
                           .get("id_errors") or {}).values():
                if (isinstance(detail, dict) and "account is suspended" in
                    detail.get("provider_errors", "").lower()):
                    confirmed.append(run["utc"])
        self.assertTrue(confirmed, "Real persisted provider denial must exist")
        stamp = datetime.fromisoformat(confirmed[-1].replace("Z","+00:00"))
        result = account_suspension_cooldown(audit, stamp + timedelta(minutes=1))
        self.assertEqual(result["reason"], "PROVIDER_CONFIRMED_ACCOUNT_SUSPENSION")

if __name__ == "__main__":
    unittest.main()
