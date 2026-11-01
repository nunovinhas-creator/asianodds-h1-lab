"""FT V8: last-chance visit, deadline-first ordering and auditable expiry (offline)."""
import unittest
from datetime import datetime, timedelta, timezone

from h1lab.lab_results import LAST_CHANCE_WINDOW, reconcile

NOW = datetime(2026, 11, 1, 21, 30, tzinfo=timezone.utc)
H24 = timedelta(hours=24)


def game(key, remaining):
    """A fixture whose 24h window closes `remaining` from NOW."""
    ko = NOW + remaining - H24
    return {"match_key": key, "home": "Home " + key, "away": "Away " + key,
            "kickoff_utc": ko.isoformat()}


def pending(row, **extra):
    return {**row, "status": "PENDING", "lookup_source_version": 11, **extra}


def run(rows, previous=None, limit=30, now=NOW, tsdb=None, bsd=None, **kw):
    calls = []

    def lookup(name, fn):
        def inner(signal):
            calls.append((name, signal["match_key"]))
            return fn(signal) if fn else (None, "no_exact_match")
        return inner

    ledger, report, attempts = reconcile(
        {"alerts": rows, "signals": []}, [],
        previous or {"schema_version": 1, "matches": {}},
        now=now, max_checks=limit, horizon=H24, evidence_retry=True,
        lookup_source_version=11,
        bsd_lookup=lookup("bsd", bsd), tsdb_lookup=lookup("tsdb", tsdb), **kw)
    return ledger, report, attempts, calls


def prev(*entries):
    return {"schema_version": 1, "matches": {e["match_key"]: e for e in entries}}


class LastChanceTests(unittest.TestCase):
    def test_visit_gate_that_outlives_the_window_gets_one_last_visit(self):
        row = game("a", timedelta(hours=1, minutes=30))
        entry = pending(row, queue_visited_at=(NOW - timedelta(minutes=30)).isoformat())
        ledger, report, attempts, calls = run([row], prev(entry))
        self.assertEqual(attempts, 1)
        self.assertEqual(report["ft_queue"]["last_chance_selected"], ["a"])
        got = ledger["matches"]["a"]
        self.assertEqual(got["last_chance_visit_at"], NOW.isoformat(timespec="seconds"))
        self.assertEqual(got["last_visit_outcome"], "NO_SNAPSHOT")
        # Exactly once: the flag blocks a second waiver on the next run.
        _, report2, attempts2, _ = run([row], ledger, now=NOW + timedelta(minutes=30))
        self.assertEqual(attempts2, 0)
        self.assertEqual(report2["ft_queue"]["last_chance_selected"], [])

    def test_no_waiver_when_more_than_the_window_remains(self):
        row = game("b", LAST_CHANCE_WINDOW + timedelta(minutes=1))
        entry = pending(row, queue_visited_at=(NOW - timedelta(minutes=30)).isoformat())
        _, _, attempts, calls = run([row], prev(entry))
        self.assertEqual((attempts, calls), (0, []))

    def test_no_waiver_when_normal_cooldown_ends_inside_the_window(self):
        row = game("c", timedelta(hours=1, minutes=30))
        entry = pending(row, queue_visited_at=(NOW - timedelta(hours=3)).isoformat())
        _, report, attempts, _ = run([row], prev(entry))
        self.assertEqual(attempts, 0)
        self.assertEqual(report["ft_queue"]["last_chance_eligible"], [])

    def test_waives_only_the_local_visit_gate_not_the_evidence_gate(self):
        row = game("d", timedelta(hours=1))
        entry = pending(row, queue_visited_at=(NOW - timedelta(minutes=30)).isoformat(),
                        evidence_checked_at=(NOW - timedelta(hours=1)).isoformat(),
                        stable_confirmations=2)  # really queried: 24h evidence wait
        _, _, attempts, calls = run([row], prev(entry))
        self.assertEqual((attempts, calls), (0, []))

    def test_never_after_the_window_and_never_in_legacy_mode(self):
        row = game("e", -timedelta(seconds=1))
        entry = pending(row, queue_visited_at=(NOW - timedelta(minutes=30)).isoformat())
        ledger, _, attempts, calls = run([row], prev(entry))
        self.assertEqual((attempts, calls), (0, []))
        self.assertEqual(ledger["matches"]["e"]["status"], "EXPIRED_UNVERIFIED")
        live = game("f", timedelta(hours=1))
        legacy, _, n = reconcile({"alerts": [live], "signals": []}, [],
                                 prev(pending(live, queue_visited_at=(NOW - timedelta(minutes=30)).isoformat())),
                                 now=NOW, max_checks=30, horizon=H24,
                                 bsd_lookup=lambda s: (None, "x"), tsdb_lookup=lambda s: (None, "x"))[:3]
        self.assertNotIn("last_chance_visit_at", legacy["matches"]["f"])

    def test_cap_of_30_is_never_exceeded_and_most_urgent_goes_first(self):
        rows = [game(f"g{i:02d}", timedelta(minutes=10 + i)) for i in range(35)]
        entries = [pending(r, queue_visited_at=(NOW - timedelta(minutes=30)).isoformat()) for r in rows]
        _, report, attempts, calls = run(rows, prev(*entries))
        self.assertEqual(attempts, 30)
        self.assertEqual(len({k for _, k in calls}), 30)
        self.assertEqual(len(calls), 60)  # 2 providers x 30 games: no extra lookups
        self.assertEqual(report["ft_queue"]["last_chance_selected"], [f"g{i:02d}" for i in range(30)])
        self.assertEqual(report["ft_queue"]["deferred_by_capacity"], 5)

    def test_nearly_expired_game_outranks_a_less_urgent_first_visit(self):
        urgent = game("urgent", timedelta(hours=1))
        fresh = game("fresh", timedelta(hours=20))
        entry = pending(urgent, queue_visited_at=(NOW - timedelta(minutes=30)).isoformat())
        _, report, _, _ = run([fresh, urgent], prev(entry), limit=1)
        self.assertEqual(report["ft_queue"]["selected_keys"], ["urgent"])

    def test_provider_cooldown_is_recorded_not_bypassed(self):
        row = game("h", timedelta(hours=1))
        entry = pending(row, queue_visited_at=(NOW - timedelta(minutes=30)).isoformat())
        ledger, _, _, calls = run([row], prev(entry),
                                  tsdb=lambda s: (None, "tsdb_http_429_cooldown_deferred"))
        got = ledger["matches"]["h"]
        self.assertEqual(got["last_provider_visit"]["reasons"]["thesportsdb"],
                         "tsdb_http_429_cooldown_deferred")
        self.assertEqual(got["last_visit_outcome"], "NO_SNAPSHOT")
        self.assertEqual(got["queue_visits_total"], 1)
        # lookups are adapter invocations (the adapter owns the cooldown), not HTTP proof
        self.assertEqual(got["provider_lookups_invoked_total"], len(calls))


class ExpiryAuditTrailTests(unittest.TestCase):
    def test_expiry_keeps_real_visit_counters_and_is_idempotent(self):
        row = game("x", timedelta(hours=1))
        ledger, _, _, _ = run([row], prev(pending(row, queue_visited_at=(NOW - timedelta(minutes=30)).isoformat(),
                                                   queue_visits_total=2, provider_lookups_invoked_total=4)))
        self.assertEqual(ledger["matches"]["x"]["queue_visits_total"], 3)
        later = NOW + timedelta(hours=2)
        expired, _, attempts, calls = run([row], ledger, now=later)
        self.assertEqual((attempts, calls), (0, []))
        tomb = expired["matches"]["x"]
        self.assertEqual(tomb["status"], "EXPIRED_UNVERIFIED")
        self.assertEqual(tomb["expiry_reason"], "ft_24h_window_elapsed")
        self.assertEqual(tomb["expired_at"], later.isoformat(timespec="seconds"))
        trail = tomb["audit_trail"]
        self.assertEqual(trail["queue_visits_total"], 3)
        self.assertEqual(trail["provider_lookups_invoked_total"], 4 + 2)
        self.assertEqual(trail["last_visit_outcome"], "NO_SNAPSHOT")
        self.assertNotIn("result", tomb)
        again, _, _, _ = run([row], expired, now=later + timedelta(days=3))
        self.assertEqual(again["matches"]["x"], tomb)

    def test_never_visited_and_legacy_tombstones_are_not_backfilled(self):
        fresh = game("n", -timedelta(minutes=1))
        ledger, _, _, calls = run([fresh], prev(pending(fresh)))
        self.assertEqual(calls, [])
        self.assertNotIn("audit_trail", ledger["matches"]["n"])
        old = game("o", -timedelta(days=2))
        legacy = {**old, "status": "EXPIRED_UNVERIFIED", "reason": "ft_24h_window_elapsed",
                  "sources": ["H1_ALERT"], "observed_alerts": 1}
        out, _, _, _ = run([old], prev(legacy))
        self.assertEqual(out["matches"]["o"], legacy)
        self.assertNotIn("expired_at", out["matches"]["o"])

    def test_certified_final_and_expired_are_never_reclassified(self):
        row = game("fin", -timedelta(days=3))
        final = {**row, "status": "FINAL", "result": {"home_goals": 1, "away_goals": 0, "source": "https://example.org/x", "evidence": "bsd_only"}}
        expired = {**game("exp", -timedelta(hours=30)), "status": "EXPIRED_UNVERIFIED",
                   "reason": "ft_24h_window_elapsed", "sources": ["H1_ALERT"], "observed_alerts": 1}
        out, _, attempts, calls = run([row, game("exp", -timedelta(hours=30))], prev(final, expired),
                                      bsd=lambda s: ({"match_key": s["match_key"], "status": "final", "home_goals": 9, "away_goals": 9, "source": "https://example.org/y"}, "ok"))
        self.assertEqual((attempts, calls), (0, []))
        self.assertEqual(out["matches"]["fin"]["status"], "FINAL")
        self.assertEqual(out["matches"]["fin"]["result"], final["result"])
        self.assertEqual(out["matches"]["exp"]["status"], "EXPIRED_UNVERIFIED")

    def test_two_runs_from_the_same_ledger_are_deterministic(self):
        row = game("p", timedelta(hours=1))
        base = prev(pending(row, queue_visited_at=(NOW - timedelta(minutes=30)).isoformat()))
        a = run([row], base)[0]
        b = run([row], base)[0]
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
