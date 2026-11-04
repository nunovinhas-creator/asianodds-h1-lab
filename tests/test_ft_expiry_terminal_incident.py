"""P0 #107: EXPIRED_UNVERIFIED -> IDENTITY_CONFLICT -> EXPIRED_UNVERIFIED (2026-11-01,1009,964).

Proven mechanism (commits d06b6394ee91 and a1374a9d322c on main):

* the H1 channel announced CD Cobresal vs CD Everton twice with two kickoffs (17:15 on 30/10 and
  18:00 on 01/11, a reschedule), so ``build_catalog`` flags ``identity_conflict``;
* the fixture was already a 24h tombstone; the first ``reconcile`` loop overwrote the terminal
  status with IDENTITY_CONFLICT on every run, and the expiry loop re-stamped a NEW tombstone
  (``expired_at`` 20:22 -> 20:37 -> 21:12 -> 21:47 -> 00:52 -> 01:31 -> 02:11);
* whenever a run had a newly corroborated STRONG pair, ``settle_new_cached_pairs`` replayed
  ``reconcile`` WITHOUT ``horizon`` (legacy 30-day test horizon), the tombstone was not
  re-applied, and the IDENTITY_CONFLICT row was published.

Everything here is offline: every provider adapter raises if called.
"""
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from h1lab import lab_ft_same_run
from h1lab.lab_results import HORIZON, LIVE_HORIZON, reconcile
from h1lab.lab_ft_same_run import settle_new_cached_pairs

REPO = Path(__file__).resolve().parents[1]
KEY = "2026-11-01,1009,964"
# Exact tombstone on main at 86da2fabff6c (parent of d06b6394ee91).
TOMBSTONE = {"away": "CD Everton de Viña del Mar", "expired_at": "2026-11-03T20:22:34+00:00",
             "expiry_detail": "never_visited_or_history_not_recorded",
             "expiry_reason": "ft_24h_window_elapsed", "home": "CD Cobresal",
             "kickoff_utc": "2026-11-01T17:15:00+00:00", "observed_alerts": 2,
             "reason": "ft_24h_window_elapsed", "sources": ["H1_ALERT", "V4"],
             "status": "EXPIRED_UNVERIFIED"}
# Exact H1 alerts (data/state.json) and V4 rows (markets-2026-10/11.jsonl) of the fixture.
H1_ALERTS = [
    {"match_key": KEY, "home": "CD Cobresal", "away": "CD Everton de Viña del Mar",
     "kickoff_utc": "2026-11-01T17:15:00+00:00", "message_id": 51448,
     "observed_at": "2026-10-30T10:46:00+00:00"},
    {"match_key": KEY, "home": "CD Cobresal", "away": "CD Everton de Viña del Mar",
     "kickoff_utc": "2026-11-01T18:00:00+00:00", "message_id": 52268,
     "observed_at": "2026-11-01T17:21:16+00:00"},
]
V4_ROWS = [
    {"match_key": KEY, "home": None, "away": None, "kickoff_utc": "2026-11-01T17:15:00+00:00",
     "event_id": "3571094759:51448", "observed_at": "2026-10-30T10:46:00+00:00"},
    {"match_key": KEY, "home": None, "away": None, "kickoff_utc": "2026-11-01T18:00:00+00:00",
     "event_id": "3571094759:52268", "observed_at": "2026-11-01T17:21:16+00:00"},
]
NOW = datetime(2026, 11, 3, 20, 37, 10, tzinfo=timezone.utc)      # push of d06b6394ee91
# A different fixture that two cached providers corroborate in the same run: this is what
# triggered the second (offline) reconcile pass in production.
PAIR_KO = "2026-11-03T02:00:00+00:00"
PAIR_KEY = "2026-11-03,1,2"
PAIR = dict(match_key=PAIR_KEY, home="AS Hellas Verona", away="Bologna FC", kickoff_utc=PAIR_KO)
FINAL_KEY = "2026-10-31,7,8"
FINAL_ROW = {"status": "FINAL", "home": "Old Home", "away": "Old Away",
             "kickoff_utc": "2026-10-31T15:00:00+00:00", "sources": ["H1_ALERT"],
             "observed_alerts": 1,
             "result": {"home_goals": 1, "away_goals": 0,
                        "source": "https://example.invalid/ft/7-8", "evidence": "fixture"}}
FINAL_ALERT = {"match_key": FINAL_KEY, "home": "Old Home", "away": "Old Away",
               "kickoff_utc": "2026-10-31T15:00:00+00:00"}


def no_network(_signal):
    raise AssertionError("provider called")


def adapters():
    day = PAIR_KO[:10]
    af = {"fixture": {"id": 123456, "date": PAIR_KO, "status": {"short": "FT"}},
          "league": {"id": 39, "name": "Serie A"},
          "teams": {"home": {"id": 1, "name": "Hellas Verona"},
                    "away": {"id": 2, "name": "Bologna"}},
          "score": {"fulltime": {"home": 2, "away": 1}}, "goals": {"home": 2, "away": 1}}
    goal = {"apiId": "876543", "homeTeamName": "Hellas Verona", "awayTeamName": "Bologna",
            "kickoffUtc": PAIR_KO, "competition": {"name": "Serie A"},
            "matchStatus": "FINISHED", "matchPeriod": "FINISHED", "homeTeamFtScore": "2",
            "awayTeamFtScore": "1", "homeTeamScore": "2", "awayTeamScore": "1"}
    return (SimpleNamespace(days={day: [af]}), SimpleNamespace(cache={day: [goal]}),
            SimpleNamespace(days={}))


def production_cycle(previous, now, *, alerts=None, second_pass_horizon=None):
    """First pass (LIVE_HORIZON, no provider) + the same-run cached second pass."""
    state = {"alerts": alerts if alerts is not None else H1_ALERTS + [PAIR, FINAL_ALERT],
             "signals": []}
    ledger, report, attempts = reconcile(state, V4_ROWS, previous, now=now,
                                         bsd_lookup=no_network, tsdb_lookup=no_network,
                                         max_checks=0, evidence_retry=True,
                                         horizon=LIVE_HORIZON)
    assert attempts == 0
    api, goal, openfoot = adapters()
    kw = {} if second_pass_horizon is None else {"horizon": second_pass_horizon}
    ledger, report, _ = settle_new_cached_pairs(
        state, V4_ROWS, ledger, report, now,
        previous_review={"schema_version": 1, "games": []},
        api_football=api, goal=goal, openfoot=openfoot, source_version=11, **kw)
    return ledger, report


def previous_ledger():
    return {"schema_version": 1, "matches": {KEY: copy.deepcopy(TOMBSTONE),
                                             FINAL_KEY: copy.deepcopy(FINAL_ROW)}}


class ExpiryIsTerminal(unittest.TestCase):
    def test_incident_replay_keeps_the_tombstone_and_records_the_conflict_once(self):
        ledger, _ = production_cycle(previous_ledger(), NOW)
        row = ledger["matches"][KEY]
        self.assertEqual(ledger["matches"][PAIR_KEY]["status"], "FINAL",
                         "the second pass really ran (new corroborated pair)")
        self.assertEqual(row["status"], "EXPIRED_UNVERIFIED")
        self.assertEqual(row["expired_at"], TOMBSTONE["expired_at"], "never re-stamped")
        self.assertEqual(row["reason"], "ft_24h_window_elapsed")
        self.assertEqual(row["kickoff_utc"], TOMBSTONE["kickoff_utc"])
        self.assertNotIn("result", row)
        self.assertEqual(row["post_expiry_identity_conflict"],
                         {"first_observed_at": NOW.isoformat(timespec="seconds"),
                          "reason": "conflicting_observed_identity", "changed_fields": [],
                          "status_kept": "EXPIRED_UNVERIFIED"})

    def test_aba_replay_is_idempotent_over_repeated_runs(self):
        ledger, _ = production_cycle(previous_ledger(), NOW)
        first = json.dumps(ledger["matches"][KEY], sort_keys=True)
        final = json.dumps(ledger["matches"][FINAL_KEY], sort_keys=True)
        moment = NOW
        for step in range(6):        # 20:37 ... with and without the second pass
            moment += timedelta(minutes=35)
            alerts = H1_ALERTS + ([PAIR] if step % 2 else []) + [FINAL_ALERT]
            ledger, _ = production_cycle(ledger, moment, alerts=alerts)
            self.assertEqual(json.dumps(ledger["matches"][KEY], sort_keys=True), first)
            self.assertEqual(json.dumps(ledger["matches"][FINAL_KEY], sort_keys=True), final)

    def test_legacy_30_day_horizon_can_no_longer_reopen_an_expired_fixture(self):
        # Defence in depth: even a caller that forgets the horizon cannot re-open it.
        ledger, _ = production_cycle(previous_ledger(), NOW, second_pass_horizon=HORIZON)
        self.assertEqual(ledger["matches"][KEY]["status"], "EXPIRED_UNVERIFIED")
        self.assertEqual(ledger["matches"][KEY]["expired_at"], TOMBSTONE["expired_at"])

    def test_same_run_second_pass_uses_the_operational_horizon(self):
        seen = []
        real = lab_ft_same_run.reconcile

        def spy(*args, **kwargs):
            seen.append(kwargs.get("horizon"))
            return real(*args, **kwargs)
        with patch.object(lab_ft_same_run, "reconcile", side_effect=spy):
            production_cycle(previous_ledger(), NOW)
        self.assertEqual(seen, [LIVE_HORIZON])

    def test_identity_change_after_expiry_is_recorded_not_applied(self):
        alerts = [dict(H1_ALERTS[0], home="CD Cobresal B")]
        ledger, _ = production_cycle(previous_ledger(), NOW, alerts=alerts + [FINAL_ALERT])
        row = ledger["matches"][KEY]
        self.assertEqual((row["status"], row["home"]), ("EXPIRED_UNVERIFIED", "CD Cobresal"))
        self.assertEqual(row["post_expiry_identity_conflict"]["reason"],
                         "conflicting_observed_identity")

    def test_changed_identity_without_catalog_conflict_is_still_only_recorded(self):
        alerts = [dict(a, kickoff_utc="2026-11-01T18:00:00+00:00") for a in H1_ALERTS]
        v4 = [dict(r, kickoff_utc="2026-11-01T18:00:00+00:00") for r in V4_ROWS]
        state = {"alerts": alerts, "signals": []}
        ledger, _, _ = reconcile(state, v4, previous_ledger(), now=NOW, bsd_lookup=no_network,
                                 tsdb_lookup=no_network, max_checks=0, horizon=LIVE_HORIZON)
        row = ledger["matches"][KEY]
        self.assertEqual(row["status"], "EXPIRED_UNVERIFIED")
        self.assertEqual(row["kickoff_utc"], TOMBSTONE["kickoff_utc"])
        self.assertEqual(row["post_expiry_identity_conflict"]["changed_fields"], ["kickoff_utc"])
        self.assertEqual(row["post_expiry_identity_conflict"]["reason"],
                         "identity_changed_after_expiry")

    def test_quarantine_reason_survives_expiry(self):
        live = NOW - timedelta(hours=20)
        previous = {"schema_version": 1, "matches": {}}
        alerts = [dict(H1_ALERTS[0], kickoff_utc=(live - timedelta(hours=5)).isoformat()),
                  dict(H1_ALERTS[1], kickoff_utc=(live - timedelta(hours=4)).isoformat())]
        state = {"alerts": alerts, "signals": []}
        ledger, _, _ = reconcile(state, [], previous, now=live, bsd_lookup=no_network,
                                 tsdb_lookup=no_network, max_checks=0, horizon=LIVE_HORIZON)
        self.assertEqual(ledger["matches"][KEY]["status"], "IDENTITY_CONFLICT")
        later = live + timedelta(hours=30)
        ledger, _, _ = reconcile(state, [], ledger, now=later, bsd_lookup=no_network,
                                 tsdb_lookup=no_network, max_checks=0, horizon=LIVE_HORIZON)
        row = ledger["matches"][KEY]
        self.assertEqual(row["status"], "EXPIRED_UNVERIFIED")
        self.assertEqual(row["status_before_expiry"], "IDENTITY_CONFLICT")
        self.assertEqual(row["reason_before_expiry"], "conflicting_observed_identity")
        expired_at = row["expired_at"]
        ledger, _, _ = reconcile(state, [], ledger, now=later + timedelta(hours=1),
                                 bsd_lookup=no_network, tsdb_lookup=no_network, max_checks=0,
                                 horizon=LIVE_HORIZON)
        self.assertEqual(ledger["matches"][KEY]["expired_at"], expired_at)


class RealLedgerReplay(unittest.TestCase):
    """Replay over the real main inputs: no EXPIRED row re-opens, no FINAL row changes."""

    def test_real_ledger_two_passes(self):
        ledger_path = REPO / "data/lab/ft-ledger.json"
        if not ledger_path.exists():
            self.skipTest("real ledger not present")
        previous = json.loads(ledger_path.read_text(encoding="utf-8"))
        state = json.loads((REPO / "data/state.json").read_text(encoding="utf-8"))
        v4 = []
        for path in sorted((REPO / "data/lab").glob("markets-*.jsonl")):
            v4 += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                   if line.strip()]
        now = datetime.now(timezone.utc)
        ledger = previous
        for horizon in (LIVE_HORIZON, HORIZON):    # operational pass, then the legacy default
            ledger, _, attempts = reconcile(state, v4, ledger, now=now, bsd_lookup=no_network,
                                            tsdb_lookup=no_network, max_checks=0,
                                            horizon=horizon)
            self.assertEqual(attempts, 0)
        before, after = previous["matches"], ledger["matches"]
        for key, row in before.items():
            if row.get("status") == "EXPIRED_UNVERIFIED":
                self.assertEqual(after[key]["status"], "EXPIRED_UNVERIFIED", key)
                self.assertEqual(after[key].get("expired_at"), row.get("expired_at"), key)
            if row.get("status") == "FINAL":
                self.assertEqual(after[key]["status"], "FINAL", key)
                self.assertEqual(after[key]["result"], row["result"], key)


if __name__ == "__main__":
    unittest.main()
