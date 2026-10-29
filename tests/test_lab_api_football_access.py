"""Provider-history gate: no HTTP and no inferred access restrictions."""
import unittest
from datetime import datetime, timezone, timedelta
from h1lab.lab_api_football_access import evolve_access, restriction_for_day, restriction_for_fixture_id
from h1lab.lab_ft_rotation import choose_days

NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
OLD = "2026-10-27"
OK = "2026-10-28"


def error(text, *, category="PROVIDER_ERRORS", status=200):
    return {"category": category, "http_status": status, "provider_errors": text}


class ProviderHistoryAccessTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
