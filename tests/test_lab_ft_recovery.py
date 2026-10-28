"""Pure LAB recovery regression tests: no HTTP, no H1 mutation."""
import copy
import unittest
from datetime import datetime, timezone

from h1lab.lab_results import reconcile

KEY = "2026-10-27,9999001,9999002"
HOME = "Montevideo City Torque Reserve"
AWAY = "Albion FC Reserves"
KICKOFF = "2026-10-27T13:00:00+00:00"


def game(key=KEY, home=HOME, away=AWAY, kickoff=KICKOFF):
    return {"match_key": key, "home": home, "away": away,
            "kickoff_utc": kickoff}


def final(signal, home=2, away=1):
    return ({"match_key": signal["match_key"], "status": "final",
             "home_goals": home, "away_goals": away,
             "source": "https://example.org/independent-ft"}, "verified_independent_ft")


def none(signal):
    return None, "no_exact_match"


def quarantined(previous_time="2026-10-28T08:09:07+00:00"):
    return {"schema_version": 1, "matches": {KEY: {
        **game(), "status": "SOURCE_ORDER_CONFLICT",
        "reason": "sportscore_source_url_reverses_home_away",
        "checked_at": previous_time, "lookup_source_version": 4,
        "attempts": 3}}}


class SafeRecoveryTests(unittest.TestCase):
    def call(self, previous, now, **kw):
        return reconcile({"alerts": [game()], "signals": []}, [],
                         previous, now=now, max_checks=30,
                         bsd_lookup=kw.get("bsd_lookup", none),
                         tsdb_lookup=kw.get("tsdb_lookup", none),
                         sportscore_lookup=kw.get("sportscore_lookup", none),
                         force_recheck=kw.get("force_recheck", False))

    def test_quarantined_never_calls_sportscore_and_requires_independent_ft(self):
        def forbidden(_):
            raise AssertionError("Quarantined SportScore source must not be called")
        now = datetime(2026, 10, 28, 14, tzinfo=timezone.utc)
        old = quarantined()
        copy_old = copy.deepcopy(old)
        updated, report, checked = self.call(old, now, bsd_lookup=final,
                                             sportscore_lookup=forbidden)
        row = updated["matches"][KEY]
        self.assertEqual((checked, row["status"]), (1, "FINAL"))
        self.assertEqual(row["result"]["evidence"], "bsd_only")
        self.assertEqual(row["source_order_resolution"]["verified_by"], ["bsd"])
        self.assertEqual(report["source_order_audit"]["recovered_with_independent_ft"], 1)
        self.assertEqual(old, copy_old)
        self.assertEqual(row["provider_reasons"]["sportscore"], "quarantined_source_not_reused")

    def test_quarantine_stays_blocked_if_independent_provider_finds_nothing(self):
        updated, report, checked = self.call(
            quarantined(), datetime(2026, 10, 28, 14, tzinfo=timezone.utc))
        self.assertEqual(checked, 1)
        self.assertEqual(updated["matches"][KEY]["status"], "SOURCE_ORDER_CONFLICT")
        self.assertNotIn("result", updated["matches"][KEY])
        self.assertEqual(report["timing_counts"]["BLOCKED_REVIEW"], 1)

    def test_independent_score_disagreement_does_not_settle(self):
        updated, _, checked = self.call(
            quarantined(), datetime(2026, 10, 28, 14, tzinfo=timezone.utc),
            bsd_lookup=final,
            tsdb_lookup=lambda signal: final(signal, home=1, away=2))
        row = updated["matches"][KEY]
        self.assertEqual(checked, 1)
        self.assertEqual(row["status"], "SOURCE_ORDER_CONFLICT")
        self.assertEqual(row["reason"], "independent_sources_disagree_manual_review")
        self.assertNotIn("result", row)

    def test_force_recheck_is_one_run_only_and_does_not_touch_existing_final(self):
        original = quarantined()
        original["matches"]["2026-10-27,42,43"] = {
            **game("2026-10-27,42,43", "Known Home", "Known Away"),
            "status": "FINAL", "result": {
                "home_goals": 3, "away_goals": 0,
                "source": "https://example.org/original",
                "evidence": "bsd_only"}}
        original_result = copy.deepcopy(original["matches"]["2026-10-27,42,43"]["result"])
        now = datetime(2026, 10, 28, 9, tzinfo=timezone.utc)
        updates, _, checked = reconcile(
            {"alerts": [game(), game("2026-10-27,42,43", "Known Home", "Known Away")],
             "signals": []}, [], original, now=now, bsd_lookup=none,
            tsdb_lookup=none, force_recheck=True)
        self.assertEqual(checked, 1)
        self.assertEqual(updates["matches"]["2026-10-27,42,43"]["result"], original_result)
        self.assertEqual(updates["matches"][KEY]["status"], "SOURCE_ORDER_CONFLICT")
        with self.assertRaises(ValueError):
            self.call(quarantined(), now, force_recheck=1)

    def test_forced_backlog_outranks_new_due_games_under_30_game_cap(self):
        now = datetime(2026, 10, 28, 11, tzinfo=timezone.utc)
        alerts, previous = [], {"schema_version": 1, "matches": {}}
        for i in range(21):
            item = game(f"2026-10-27,{1000+i},{2000+i}", f"Old Home {i}",
                        f"Old Away {i}")
            alerts.append(item)
            previous["matches"][item["match_key"]] = {
                **item, "status": "PENDING",
                "checked_at": "2026-10-28T10:40:00+00:00",
                "lookup_source_version": 11}
        for i in range(20):
            alerts.append(game(f"2026-10-27,{3000+i},{4000+i}",
                               f"Fresh Home {i}", f"Fresh Away {i}"))
        inspected = []
        def probe(signal):
            inspected.append(signal["match_key"])
            return None, "no_match"
        _, _, attempted = reconcile({"alerts": alerts, "signals": []}, [],
            previous, now=now, bsd_lookup=probe, tsdb_lookup=none,
            force_recheck=True, max_checks=25)
        self.assertEqual(attempted, 25)
        self.assertEqual(set(inspected[:21]),
                         {f"2026-10-27,{1000+i},{2000+i}" for i in range(21)})


if __name__ == "__main__":
    unittest.main()
