"""No-network regression for same-run cached FT corroboration."""
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from types import SimpleNamespace

from h1lab.lab_results import reconcile
from h1lab.lab_ft_same_run import settle_new_cached_pairs

KO = "2026-10-28T18:00:00+00:00"
DAY = "2026-10-28"
NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
KEY = "2026-10-28,1,2"
SIGNAL = dict(match_key=KEY, home="AS Hellas Verona",
              away="Bologna FC", kickoff_utc=KO)


def adapters(*, conflicting=False, goal_absent=False):
    af = {"fixture":{"id":123456,"date":KO,"status":{"short":"FT"}},
          "league":{"id":39,"name":"Serie A"},
          "teams":{"home":{"id":1,"name":"Hellas Verona"},
                   "away":{"id":2,"name":"Bologna"}},
          "score":{"fulltime":{"home":2,"away":1}},
          "goals":{"home":2,"away":1}}
    goal = {"apiId":"876543","homeTeamName":"Hellas Verona",
            "awayTeamName":"Bologna","kickoffUtc":KO,
            "competition":{"name":"Serie A"},
            "matchStatus":"FINISHED","matchPeriod":"FINISHED",
            "homeTeamFtScore":"3" if conflicting else "2",
            "awayTeamFtScore":"1",
            "homeTeamScore":"3" if conflicting else "2",
            "awayTeamScore":"1"}
    return (SimpleNamespace(days={DAY:[af]}),
            SimpleNamespace(cache={} if goal_absent else {DAY:[goal]}),
            SimpleNamespace(days={}))


def baseline():
    state={"alerts":[SIGNAL], "signals":[]}
    previous={"schema_version":1,"matches":{}}
    def no_result(_):
        return None, "disabled"
    ledger,report,attempts=reconcile(
        state, [],previous,now=NOW,bsd_lookup=no_result,
        tsdb_lookup=no_result,max_checks=0,evidence_retry=True)
    assert attempts == 0
    return state,ledger,report


class SameRunRecoveryTests(unittest.TestCase):
    def run_replay(self, *, conflicting=False, goal_absent=False,
                   hold=(), previous_review=None):
        state,ledger,report=baseline()
        api,goal,openfoot=adapters(conflicting=conflicting,
                                  goal_absent=goal_absent)
        return settle_new_cached_pairs(
            state,[],ledger,report,NOW,
            previous_review=previous_review or
                {"schema_version":1,"games":[]},
            api_football=api,goal=goal,openfoot=openfoot,
            score_hold_keys=hold,source_version=11)

    def test_new_strong_pair_recovers_real_regulation_ft_without_http(self):
        ledger,report,engine=self.run_replay()
        row=ledger["matches"][KEY]
        self.assertEqual(row["status"],"FINAL")
        self.assertEqual((row["result"]["home_goals"],
                          row["result"]["away_goals"]),(2,1))
        self.assertEqual(row["result"]["evidence"],"dual_provider_only")
        self.assertEqual(report["final_recorded"],1)
        self.assertEqual(report["unverified"],0)
        self.assertEqual(report["ft_queue"]["same_run_cached_postcheck"]
                         ["eligible_new_strong_pairs"],1)
        self.assertEqual(report["ft_queue"]["same_run_cached_postcheck"]
                         ["adapter_http_requests"],0)
        self.assertEqual(set(engine.confirmations[KEY]),{"api_football","goal"})
        self.assertEqual(set(engine.captured[KEY]),{"api_football","goal"})

    def test_no_second_provider_never_promotes(self):
        ledger,report,engine=self.run_replay(goal_absent=True)
        self.assertEqual(ledger["matches"][KEY]["status"],"PENDING")
        self.assertEqual(report["final_recorded"],0)
        self.assertFalse(engine.confirmations)

    def test_independent_score_conflict_quarantines(self):
        ledger,report,_=self.run_replay(conflicting=True)
        self.assertEqual(ledger["matches"][KEY]["status"],"SCORE_CONFLICT")
        self.assertNotIn("result",ledger["matches"][KEY])
        self.assertEqual(report["ft_queue"]["dual_postcheck_conflicts"],1)
        self.assertEqual(report["ft_queue"]["same_run_cached_postcheck"]
                         ["score_conflicts"],1)

    def test_second_pass_exception_degrades_health_without_exposing_payload(self):
        with patch("h1lab.lab_ft_same_run.TwoProviderConsensus.lookup",
                   side_effect=RuntimeError("sensitive provider payload")):
            ledger,report,_=self.run_replay()
        self.assertEqual(ledger["matches"][KEY]["status"],"PENDING")
        self.assertEqual(report["execution_health"]["status"],"DEGRADED")
        self.assertEqual(report["execution_health"]["dual_postcheck_errors"],1)
        self.assertEqual(report["ft_queue"]["same_run_cached_postcheck"]
                         ["execution_errors"],1)
        self.assertNotIn("sensitive",str(report))

    def test_official_hold_blocks_even_agreed_ft(self):
        ledger,report,_=self.run_replay(hold=[KEY])
        self.assertEqual(ledger["matches"][KEY]["status"],"PENDING")
        self.assertEqual(report["final_recorded"],0)


if __name__ == "__main__":
    unittest.main()
