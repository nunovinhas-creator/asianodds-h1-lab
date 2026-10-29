"""Synthetic, no-network adversarial tests for zero-call dual FT corroboration."""
import copy
import unittest
from types import SimpleNamespace
from datetime import datetime, timezone
from h1lab.lab_ft_dual_consensus import TwoProviderConsensus
from h1lab.lab_results import reconcile

DAY = "2026-10-28"
KO = "2026-10-28T18:00:00+00:00"
NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
KEY = "2026-10-28,1,2"
SIGNAL = {"match_key": KEY, "home":"AS Hellas Verona",
          "away":"Bologna FC", "kickoff_utc":KO}


def fixtures():
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
            "homeTeamFtScore":"2","awayTeamFtScore":"1",
            "homeTeamScore":"2","awayTeamScore":"1"}
    return af, goal


def review():
    af, goal = fixtures()
    def cand(provider, ident):
        return dict(provider=provider,provider_event_id=str(ident),
            provider_home="Hellas Verona",provider_away="Bologna",
            provider_competition="Serie A",provider_kickoff_utc=KO,
            match_strength="STRONG",orientation="SAME_ORDER",
            review_only=True)
    return {"schema_version":1,"games":[dict(SIGNAL,possible_duplicates=[],
        candidates=[cand("api_football",123456),cand("goal",876543)])]}


def engine(*, mut=None, hold=()):
    af, goal = fixtures()
    rev = review()
    matches = {KEY:dict(SIGNAL,status="PENDING")}
    if mut:
        mut(af,goal,rev,matches)
    obj = TwoProviderConsensus(review=rev,matches=matches,
        goal=SimpleNamespace(cache={DAY:[goal]}),
        api_football=SimpleNamespace(days={DAY:[af]}),
        openfoot=SimpleNamespace(days={}),score_hold_keys=hold,now=NOW)
    return obj


class ConsensusTests(unittest.TestCase):
    def test_two_sources_agree_without_a_new_network_request(self):
        obj = engine()
        final, reason = obj.lookup(SIGNAL)
        self.assertEqual(reason,"verified_two_provider_regulation_ft")
        self.assertEqual((final["home_goals"],final["away_goals"]),(2,1))
        self.assertEqual(final["match_key"],KEY)
        self.assertEqual(set(obj.confirmations[KEY]),{"api_football","goal"})
        self.assertEqual(obj.summary()["verified_in_run"],1)

    def test_score_disagreement_is_never_final(self):
        obj = engine(mut=lambda a,g,r,m:g.update(
            homeTeamFtScore="3",homeTeamScore="3"))
        final, why=obj.lookup(SIGNAL)
        self.assertIsNone(final)
        self.assertEqual(why,"dual_provider_score_conflict")
        self.assertEqual(obj.outcomes[KEY]["status"],"SCORE_CONFLICT")

    def test_reconcile_marks_conflict_even_if_other_provider_had_no_result(self):
        obj=engine(mut=lambda a,g,r,m:g.update(
            homeTeamFtScore="3",homeTeamScore="3"))
        no=lambda _:(None,"no_match")
        state={"alerts":[SIGNAL],"signals":[]}
        ledger, _, queries = reconcile(state,[],
            {"schema_version":1,"matches":{}},now=NOW,
            bsd_lookup=no,tsdb_lookup=no,
            dual_lookup=obj.lookup,max_checks=1)
        self.assertEqual(queries,1)
        self.assertEqual(ledger["matches"][KEY]["status"],"SCORE_CONFLICT")
        self.assertNotIn("result",ledger["matches"][KEY])

    def test_absent_second_date_cache_is_not_enough(self):
        obj=engine()
        obj.adapters["goal"].cache.clear()
        self.assertIsNone(obj.lookup(SIGNAL)[0])

    def test_same_provider_twice_cannot_fake_independent_sources(self):
        obj=engine()
        obj.review[KEY]["candidates"][1]["provider"]="api_football"
        self.assertIsNone(obj.lookup(SIGNAL)[0])

    def test_age_kickoff_category_competition_and_score_status(self):
        mutations=[
            lambda a,g,r,m:g.update(kickoffUtc="2026-10-28T19:20:00+00:00"),
            lambda a,g,r,m:g.update(matchStatus="LIVE"),
            lambda a,g,r,m:g.update(matchPeriod="EXTRA_TIME"),
            lambda a,g,r,m:g.update(homeTeamFtScore=None),
            lambda a,g,r,m:a["fixture"]["status"].update(short="AET"),
            lambda a,g,r,m:a["score"]["fulltime"].update(home=9),
            lambda a,g,r,m:g.update(competition={"name":"Another League"}),
            lambda a,g,r,m:g.update(awayTeamName="Bologna Women"),
            lambda a,g,r,m:r["games"][0].update(possible_duplicates=[{"match_key":"duplicate"}]),
            lambda a,g,r,m:r["games"][0]["candidates"][0].update(orientation="REVERSED"),
            lambda a,g,r,m:m[KEY].update(home="Different Club"),
            lambda a,g,r,m:m.update(other={"status":"FINAL","result":{
                "evidence":"goal_only","source":"https://api.goal-api.com/v1/fixtures/876543"}}),
        ]
        for change in mutations:
            with self.subTest(change=str(change)):
                obj=engine(mut=change)
                final,_=obj.lookup(SIGNAL)
                self.assertIsNone(final)

    def test_goals_withheld_under_conflict_hold(self):
        obj=engine(hold=[KEY])
        self.assertIsNone(obj.lookup(SIGNAL)[0])
        self.assertEqual(obj.reasons["official_score_hold"],1)

    def test_colliding_strong_review_claim_blocks_consensus(self):
        def collide(a,g,r,m):
            row=copy.deepcopy(r["games"][0])
            row["match_key"]="another"
            r["games"].append(row)
        self.assertIsNone(engine(mut=collide).lookup(SIGNAL)[0])

    def test_unselected_game_can_be_recovered_from_full_day_cache_at_zero_calls(self):
        obj=engine()
        no=lambda _:(None,"no_match")
        state={"alerts":[SIGNAL],"signals":[]}
        ledger,report,queries=reconcile(state,[],
            {"schema_version":1,"matches":{}}, now=NOW,
            bsd_lookup=no,tsdb_lookup=no,max_checks=0,evidence_retry=True,
            dual_lookup=obj.lookup,dual_postcheck_keys=[KEY])
        self.assertEqual(queries,0)
        self.assertEqual(report["ft_queue"]["selected"],0)
        self.assertEqual(report["ft_queue"]["dual_postcheck_scanned"],1)
        self.assertEqual(report["ft_queue"]["dual_postcheck_confirmed"],1)
        self.assertEqual(ledger["matches"][KEY]["status"],"FINAL")
        self.assertEqual(ledger["matches"][KEY]["result"]["evidence"],
            "dual_provider_only")

    def test_unselected_conflict_stays_in_quarantine(self):
        obj=engine(mut=lambda a,g,r,m:g.update(
            homeTeamFtScore="3",homeTeamScore="3"))
        no=lambda _:(None,"no_match")
        state={"alerts":[SIGNAL],"signals":[]}
        ledger,report,queries=reconcile(state,[],
            {"schema_version":1,"matches":{}}, now=NOW,
            bsd_lookup=no,tsdb_lookup=no,max_checks=0,evidence_retry=True,
            dual_lookup=obj.lookup,dual_postcheck_keys=[KEY])
        self.assertEqual(queries,0)
        self.assertEqual(report["ft_queue"]["dual_postcheck_conflicts"],1)
        self.assertEqual(ledger["matches"][KEY]["status"],"SCORE_CONFLICT")
        self.assertNotIn("result",ledger["matches"][KEY])

    def test_invalid_batch_cannot_be_over_500_keys(self):
        no=lambda _:(None,"no_match")
        state={"alerts":[SIGNAL],"signals":[]}
        with self.assertRaises(ValueError):
            reconcile(state,[],{"schema_version":1,"matches":{}},
                now=NOW,bsd_lookup=no,tsdb_lookup=no,
                max_checks=0,dual_postcheck_keys=[KEY]*501)

    def test_reconcile_produces_actual_final_for_matching_corrob(self):
        obj=engine()
        no=lambda _:(None,"no_match")
        state={"alerts":[SIGNAL],"signals":[]}
        ledger, _, queries=reconcile(state,[],{"schema_version":1,"matches":{}},
            now=NOW,bsd_lookup=no,tsdb_lookup=no,
            dual_lookup=obj.lookup,max_checks=1)
        self.assertEqual(queries,1)
        row=ledger["matches"][KEY]
        self.assertEqual(row["status"],"FINAL")
        self.assertEqual((row["result"]["home_goals"],row["result"]["away_goals"]),(2,1))
        self.assertIn(KEY,obj.confirmations)


if __name__ == "__main__":
    unittest.main()
