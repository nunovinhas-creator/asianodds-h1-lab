"""H1 retry policy v2: 24h horizon, terminal non-certified expiry, nothing certified is touched."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from h1lab import results as R
from h1lab.core import public_data
from h1lab.results import EXPIRED_STATUS, H1_RETRY_HORIZON, expire_stale_pending, plan_due_signals, sync

KO = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def sig(key, ko=KO, **extra):
    return {"match_key": key, "home": "Home " + key, "away": "Away " + key,
            "kickoff_utc": ko.isoformat(), "line": 2.5, "under_odds": 1.9,
            "signal_id": "s-" + key, **extra}


def pending_audit(at):
    return {"checked_at": at.isoformat(timespec="seconds"), "status": "pending",
            "reason": "bsd:bsd_empty_finished_list;thesportsdb:thesportsdb_circuit_open",
            "thesportsdb_reason": "thesportsdb_circuit_open"}


class ExpiryTests(unittest.TestCase):
    def test_boundary_is_exactly_24h_after_kickoff(self):
        s = [sig("a")]
        audit = {}
        self.assertEqual(expire_stale_pending(s, set(), audit, KO + H1_RETRY_HORIZON), [])
        self.assertEqual(expire_stale_pending(s, set(), audit, KO + H1_RETRY_HORIZON + timedelta(seconds=1)), ["a"])

    def test_expiry_keeps_every_counter_and_is_not_a_loss_or_a_result(self):
        old = pending_audit(KO + timedelta(hours=20))
        audit = {"a": copy.deepcopy(old)}
        now = KO + timedelta(hours=30)
        self.assertEqual(expire_stale_pending([sig("a")], set(), audit, now), ["a"])
        got = audit["a"]
        for field, value in old.items():
            if field != "status":
                self.assertEqual(got[field], value, field)       # attempt evidence preserved
        self.assertEqual(got["status"], EXPIRED_STATUS)
        self.assertEqual((got["status_before_expiry"], got["checked_before_expiry"]), ("pending", True))
        self.assertEqual(got["expiry_reason"], "h1_24h_retry_window_elapsed")
        self.assertEqual(got["retry_policy_version"], 2)
        for forbidden in ("home_goals", "away_goals", "profit", "loss", "result"):
            self.assertNotIn(forbidden, got)

    def test_never_checked_fixture_is_flagged_not_invented(self):
        audit = {}
        expire_stale_pending([sig("n")], set(), audit, KO + timedelta(hours=25))
        self.assertEqual(audit["n"]["status_before_expiry"], "no_audit_entry")
        self.assertFalse(audit["n"]["checked_before_expiry"])
        self.assertNotIn("checked_at", audit["n"])      # freshness monitors must not see a fake check

    def test_idempotent_and_never_restamps(self):
        audit = {"a": pending_audit(KO + timedelta(hours=5))}
        expire_stale_pending([sig("a")], set(), audit, KO + timedelta(hours=26))
        first = copy.deepcopy(audit)
        self.assertEqual(expire_stale_pending([sig("a")], set(), audit, KO + timedelta(days=9)), [])
        self.assertEqual(audit, first)

    def test_certified_and_settled_are_never_touched(self):
        settled = {"checked_at": KO.isoformat(), "status": "settled", "reason": "verified_lab_final"}
        audit = {"done": copy.deepcopy(settled), "row": {"status": "pending"}}
        out = expire_stale_pending([sig("done"), sig("row")], {"row"}, audit, KO + timedelta(days=40))
        self.assertEqual(out, [])
        self.assertEqual(audit["done"], settled)
        self.assertEqual(audit["row"], {"status": "pending"})

    def test_roi_fifo_and_triples_are_identical_with_or_without_expired_entries(self):
        signals = [sig("a"), sig("b", KO + timedelta(hours=1)), sig("c", KO + timedelta(hours=2))]
        state = {"signals": signals, "alerts": [], "tickets": [], "last_id": 3}
        results = {"a": {"home_goals": 1, "away_goals": 0}}
        now = KO + timedelta(days=3)
        before = public_data(copy.deepcopy(state), results, now)
        audit = {}
        expire_stale_pending(signals, set(results), audit, now)
        self.assertEqual({"b", "c"}, set(audit))
        self.assertEqual(public_data(copy.deepcopy(state), results, now), before)


class PlanTests(unittest.TestCase):
    def test_expired_games_stop_consuming_slots_and_fresh_ones_get_them(self):
        now = KO + timedelta(days=4)
        old = [sig(f"old{i}", now - timedelta(hours=30 + i)) for i in range(30)]
        fresh = [sig(f"fresh{i}", now - timedelta(hours=5 + i)) for i in range(10)]
        audit = {s["match_key"]: pending_audit(now - timedelta(hours=6)) for s in old + fresh}
        with patch.object(R, "H1_RETRY_HORIZON", timedelta(days=30)):
            legacy, d0 = plan_due_signals(old + fresh, set(), audit, now, limit=20)
        self.assertTrue(all(s["match_key"].startswith("old") for s in legacy))     # v1 starved the fresh ones
        expire_stale_pending(old + fresh, set(), audit, now)
        chosen, d1 = plan_due_signals(old + fresh, set(), audit, now, limit=20)
        self.assertEqual({s["match_key"] for s in chosen}, {s["match_key"] for s in fresh})
        self.assertEqual(len(chosen), 10)
        self.assertEqual((d0["eligible"], d1["eligible"]), (40, 10))

    def test_sync_makes_no_provider_call_for_an_expired_fixture(self):
        state = {"signals": [sig("x")], "alerts": [], "tickets": [], "last_id": 1}
        saved = {}
        calls = []
        with patch("h1lab.results.read_state", return_value=state), \
             patch("h1lab.results.read_rows", return_value=[]), \
             patch("h1lab.results.load_results", return_value={}), \
             patch("h1lab.results.read_audit", return_value={"x": pending_audit(KO + timedelta(hours=5))}), \
             patch("h1lab.results.write_rows") as write_rows, \
             patch("h1lab.core.dump_json", side_effect=lambda path, data: saved.update(data)), \
             patch("h1lab.results.save"), \
             patch.dict("os.environ", {"BSD_API_KEY": "synthetic"}), \
             patch("h1lab.bsd.find_result", side_effect=lambda s: calls.append(("bsd", s)) or (None, "x")):
            sync(now=KO + timedelta(hours=40), search=lambda s: calls.append(("tsdb", s)) or [])
        self.assertEqual(calls, [])
        write_rows.assert_not_called()
        self.assertEqual(saved["x"]["status"], EXPIRED_STATUS)


class LabEvidenceTests(unittest.TestCase):
    def test_in_window_lab_final_is_still_importable_after_h1_expiry_and_late_proof_is_not(self):
        from h1lab import lab_promotion as lp
        signal = sig("g")
        ledger = {"matches": {"g": {
            "status": "FINAL", "home": signal["home"], "away": signal["away"], "kickoff_utc": signal["kickoff_utc"],
            "result": {"home_goals": 1, "away_goals": 0, "evidence": "bsd_only",
                       "source": "https://sports.bzzoiro.com/api/v2/events/1/", "identity_match": "EXACT"}}}}
        now = KO + timedelta(days=3)          # processing happens long after the H1 window
        planned, rejected = lp.propose({"signals": [signal]}, ledger, [], now)
        self.assertEqual(len(planned), 1, rejected)          # expiry in the H1 audit does not block the transport
        self.assertEqual(rejected, {})

    def test_late_dual_provider_proof_keeps_being_rejected_with_a_specific_reason(self):
        from h1lab import lab_promotion as lp
        why = lp.dual_evidence_rejection({"match_key": "g", "kickoff_utc": KO.isoformat()},
                                         {"result": {}}, KO + timedelta(days=2), None)
        self.assertEqual(why, "attestation_journal_missing_or_unsupported")
        self.assertNotEqual(why, "unrecognized_evidence")


class MonitorTests(unittest.TestCase):
    def test_health_monitor_uses_the_same_horizon(self):
        from scripts.audit_health import h1_first_check_coverage
        now = KO + timedelta(hours=30)
        c = h1_first_check_coverage([sig("u")], set(), {}, now)
        self.assertEqual((c["expired_without_first_check"], c["first_checks_due"]), (1, 0))


class RealDataInvariants(unittest.TestCase):
    """Invariants only (no live counts): a normal publication cannot make these false."""

    @unittest.skipUnless((Path(__file__).resolve().parents[1] / "data/state.json").exists(), "repository data not present")
    def test_expiry_over_the_tracked_state_never_touches_certified_results(self):
        import csv, json
        root = Path(__file__).resolve().parents[1]
        state = json.loads((root / "data/state.json").read_text(encoding="utf-8"))
        audit = json.loads((root / "data/result_audit.json").read_text(encoding="utf-8"))
        resolved = {r["match_key"] for r in csv.DictReader((root / "data/results.csv").open(encoding="utf-8"))}
        now = datetime.now(timezone.utc)
        copy_ = copy.deepcopy(audit)
        expired = expire_stale_pending(state["signals"], resolved, copy_, now)
        self.assertFalse(set(expired) & resolved)
        for key in resolved:
            self.assertEqual(copy_.get(key), audit.get(key))
        for key in set(audit) - set(expired):
            self.assertEqual(copy_[key], audit[key])
        for key in expired:
            self.assertEqual(copy_[key]["checked_at"] if "checked_at" in audit.get(key, {}) else None,
                             audit.get(key, {}).get("checked_at"))


class RollbackTests(unittest.TestCase):
    """Persisted expired_unverified states survive a horizon change; reopening is explicit only."""

    def expired_world(self):
        signals = [sig("a"), sig("b", KO + timedelta(hours=1)), sig("fresh", KO + timedelta(hours=40))]
        audit = {"a": pending_audit(KO + timedelta(hours=5)), "b": pending_audit(KO + timedelta(hours=6))}
        now = KO + timedelta(hours=60)
        expire_stale_pending(signals, set(), audit, now)
        return signals, audit, now

    def test_lengthening_the_horizon_does_not_reopen_or_requery_expired_games(self):
        signals, audit, now = self.expired_world()
        with patch.object(R, "H1_RETRY_HORIZON", timedelta(days=30)):
            chosen, diag = plan_due_signals(signals, set(), audit, now, limit=20)
            self.assertEqual([s["match_key"] for s in chosen], ["fresh"])      # no duplicate queries
            self.assertEqual(expire_stale_pending(signals, set(), audit, now), [])
        self.assertEqual(audit["a"]["status"], EXPIRED_STATUS)

    def test_reopen_is_explicit_audited_and_restores_the_previous_state(self):
        signals, audit, now = self.expired_world()
        before = copy.deepcopy(audit["a"])
        out = R.reopen_expired(signals, set(), audit, ["a"], now, reason="manual review #107")
        self.assertEqual(out, ["a"])
        got = audit["a"]
        self.assertEqual(got["status"], "pending")
        self.assertEqual(got["checked_at"], before["checked_at"])
        self.assertEqual(got["reopen_reason"], "manual review #107")
        self.assertEqual(got["expired_history"][0]["expired_at"], before["expired_at"])
        self.assertEqual(audit["b"]["status"], EXPIRED_STATUS)                 # untouched siblings
        self.assertNotIn("home_goals", got)

    def test_reopen_refuses_certified_unknown_non_expired_and_missing_reason(self):
        signals, audit, now = self.expired_world()
        audit["fresh"] = {"status": "pending"}
        for keys, resolved in ((["fresh"], set()), (["nope"], set()), (["a"], {"a"})):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                R.reopen_expired(signals, resolved, audit, keys, now, reason="x")
        with self.assertRaises(ValueError):
            R.reopen_expired(signals, set(), audit, ["a"], now, reason="")
        self.assertEqual(audit["a"]["status"], EXPIRED_STATUS)

    def test_reopened_games_are_expired_again_under_24h_policy(self):
        signals, audit, now = self.expired_world()
        R.reopen_expired(signals, set(), audit, ["a"], now, reason="x")
        self.assertEqual(expire_stale_pending(signals, set(), audit, now), ["a"])
        self.assertEqual(len(audit["a"]["expired_history"]), 1)

    def test_cli_is_dry_run_by_default_and_touches_only_the_audit(self):
        import json, tempfile
        from scripts.h1_reopen_expired import main
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            signals, audit, now = self.expired_world()
            (root / "data/state.json").write_text(json.dumps({"signals": signals}))
            (root / "data/result_audit.json").write_text(json.dumps(audit))
            (root / "data/results.csv").write_text("match_key,status,home_goals,away_goals,source\n")
            before = (root / "data/result_audit.json").read_text()
            main(["--root", tmp, "--key", "a", "--reason", "test"])
            self.assertEqual((root / "data/result_audit.json").read_text(), before)      # dry run
            main(["--root", tmp, "--key", "a", "--reason", "test", "--apply"])
            self.assertEqual(json.loads((root / "data/result_audit.json").read_text())["a"]["status"], "pending")
            self.assertEqual((root / "data/results.csv").read_text(), "match_key,status,home_goals,away_goals,source\n")


if __name__ == "__main__":
    unittest.main()
