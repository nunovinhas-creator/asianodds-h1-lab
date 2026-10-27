"""LAB FT reconciliation tests: synthetic providers only; no HTTP calls."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from h1lab.lab_results import build_catalog, reconcile
from scripts.lab_results import read_v4

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
KICKOFF = "2026-10-27T15:00:00+00:00"


def alert(key="2026-10-27,1,2", home="Home Club", away="Away Club", kickoff=KICKOFF):
    return {"match_key": key, "home": home, "away": away, "kickoff_utc": kickoff,
            "event_id": "test:123", "h1": False}


def state(*items):
    return {"alerts": list(items), "signals": []}


def final(s, h=2, a=1, provider="bsd"):
    return {"match_key": s["match_key"], "status": "final", "home_goals": h,
            "away_goals": a, "source": "https://example.org/" + provider}


def no_result(_):
    return None, "no_exact_match"


def run(st, v4=None, previous=None, now=NOW, bsd=no_result,
        tsdb=no_result, limit=20):
    return reconcile(st, v4 or [], previous or {"schema_version": 1, "matches": {}},
                     now=now, bsd_lookup=bsd, tsdb_lookup=tsdb, max_checks=limit)


class LabFTTests(unittest.TestCase):
    def test_all_alerted_games_including_no_h1_signal(self):
        st = state(alert(), alert("2026-10-27,3,4"), alert())
        calls = []
        def bsd(s):
            calls.append(s["match_key"])
            return final(s), "verified_bsd_ft"
        ledger, report, queried = run(st, bsd=bsd)
        self.assertEqual(report["matches"], 2)
        self.assertEqual(report["h1_signals_count_in_state"], 0)
        self.assertEqual(report["final_recorded"], 2)
        self.assertEqual(queried, 2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(ledger["matches"]["2026-10-27,1,2"]["observed_alerts"], 2)
        self.assertEqual(report["status"], "LAB_FT_OBSERVATION_ONLY_NOT_CERTIFIED")

    def test_v4_only_is_counted_without_fake_team_names(self):
        _, report, queried = run(state(alert()), [
            {"match_key": "2026-10-27,5,6", "kickoff_utc": KICKOFF}
        ])
        self.assertEqual(report["matches"], 2)
        self.assertEqual(report["source_only_v4_matches"], 1)
        self.assertEqual(report["status_counts"]["INSUFFICIENT_IDENTITY"], 1)
        self.assertEqual(queried, 1)

    def test_no_lookup_before_three_hours_after_kickoff(self):
        _, report, queried = run(state(alert(kickoff="2026-10-28T10:00:00+00:00")))
        self.assertEqual(queried, 0)
        self.assertEqual(report["status_counts"]["PENDING"], 1)

    def test_dual_source_agreement_records_confirmation(self):
        ledger, _, _ = run(state(alert()), bsd=lambda s:(final(s), "ok"),
                           tsdb=lambda s:(final(s, provider="tsdb"), "ok"))
        value = ledger["matches"]["2026-10-27,1,2"]
        self.assertEqual(value["status"], "FINAL")
        self.assertEqual(value["result"]["evidence"], "bsd_and_thesportsdb")
        self.assertNotIn("roi", value)

    def test_conflicting_provider_scores_never_settle(self):
        ledger, report, _ = run(state(alert()), bsd=lambda s:(final(s), "ok"),
                                tsdb=lambda s:(final(s, 0, 0), "ok"))
        self.assertEqual(report["final_recorded"], 0)
        self.assertEqual(report["status_counts"]["SCORE_CONFLICT"], 1)
        self.assertNotIn("result", ledger["matches"]["2026-10-27,1,2"])

    def test_provider_error_is_sanitized(self):
        def fail(_):
            raise RuntimeError("Secret value is sensitive")
        ledger, _, _ = run(state(alert()), bsd=fail, tsdb=no_result)
        row = ledger["matches"]["2026-10-27,1,2"]
        self.assertEqual(row["status"], "PROVIDER_ERROR")
        self.assertEqual(row["provider_reasons"]["bsd"], "provider_unavailable")
        self.assertNotIn("Secret", json.dumps(row))

    def test_lookup_never_accepts_invalid_scores_or_wrong_key(self):
        ledger, _, _ = run(state(alert()), bsd=lambda s:(final(s, True, 1), "ok"),
                           tsdb=lambda s:(final({"match_key": "OTHER"}), "ok"))
        self.assertNotEqual(ledger["matches"]["2026-10-27,1,2"]["status"], "FINAL")

    def test_retry_interval_and_final_is_idempotent(self):
        first, _, queried = run(state(alert()))
        self.assertEqual(queried, 1)
        second, _, queried = run(state(alert()), previous=first, now=NOW+timedelta(hours=1))
        self.assertEqual(queried, 0)
        self.assertEqual(first, second)
        third, _, queried = run(state(alert()), previous=second, now=NOW+timedelta(hours=4),
                                bsd=lambda s:(final(s), "verified"))
        self.assertEqual(queried, 1)
        fourth, _, queried = run(state(alert()), previous=third, now=NOW+timedelta(hours=10))
        self.assertEqual(queried, 0)
        self.assertEqual(third, fourth)

    def test_same_match_conflicting_team_name_stays_quarantined(self):
        st = state(alert(), alert(away="Other Team"))
        ledger, report, queried = run(st, bsd=lambda s:(final(s), "ok"))
        self.assertEqual(queried, 0)
        self.assertEqual(report["status_counts"]["IDENTITY_CONFLICT"], 1)
        self.assertNotIn("result", ledger["matches"]["2026-10-27,1,2"])

    def test_change_to_final_identity_quarantines_score(self):
        first, _, _ = run(state(alert()), bsd=lambda s:(final(s), "ok"))
        changed, report, checked = run(state(alert(away="Changed")), previous=first)
        self.assertEqual(checked, 0)
        self.assertEqual(report["status_counts"]["IDENTITY_CONFLICT"], 1)
        self.assertNotIn("result", changed["matches"]["2026-10-27,1,2"])

    def test_expired_is_not_a_loss(self):
        ledger, report, attempts = run(state(alert()), now=NOW+timedelta(days=50))
        self.assertEqual(attempts, 0)
        self.assertEqual(report["status_counts"]["EXPIRED_UNVERIFIED"], 1)
        self.assertEqual(report["unverified"], 1)

    def test_max_checks_is_hard_capped(self):
        st = state(*(alert("2026-10-27,%d,%d" % (i, i+100)) for i in range(6)))
        _, report, attempts = run(st, limit=2)
        self.assertEqual(attempts, 2)
        self.assertEqual(report["pending_due_checks"], 4)
        with self.assertRaises(ValueError):
            run(st, limit=31)

    def test_real_tracked_universe_exceeds_signal_only_scope(self):
        root = Path(__file__).resolve().parents[1]
        sample = json.loads((root / "data/state.json").read_text(encoding="utf-8"))
        catalog, errors = build_catalog(sample["alerts"], read_v4())
        self.assertFalse(errors)
        self.assertGreaterEqual(len(catalog), len({x["match_key"] for x in sample["alerts"]}))
        self.assertGreaterEqual(len(catalog), len({x["match_key"] for x in sample["signals"]}))
        self.assertTrue(any(not item.get("h1") for item in sample["alerts"]))
        # No provider traffic; production files remain unchanged.
        _, report, attempts = run(sample, read_v4(), limit=0)
        self.assertEqual(attempts, 0)
        self.assertEqual(report["matches"], len(catalog))


if __name__ == "__main__":
    unittest.main()
