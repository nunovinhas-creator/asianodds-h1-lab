"""Synthetic, no-network adversarial tests for zero-call dual FT corroboration."""
import copy
import unittest
from types import SimpleNamespace
from datetime import datetime, timezone
from h1lab.lab_ft_dual_consensus import TwoProviderConsensus
from h1lab.lab_ft_attestations import merge as merge_attestations, empty as empty_attestations, valid
from h1lab.v6_ft_events import quality as ft_science_quality, snapshot as ft_science_snapshot
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


def engine(*, mut=None, hold=(), prior=None):
    af, goal = fixtures()
    rev = review()
    matches = {KEY:dict(SIGNAL,status="PENDING")}
    if mut:
        mut(af,goal,rev,matches)
    obj = TwoProviderConsensus(review=rev,matches=matches,
        goal=SimpleNamespace(cache={DAY:[goal]}),
        api_football=SimpleNamespace(days={DAY:[af]}),
        openfoot=SimpleNamespace(days={}),score_hold_keys=hold,now=NOW,
        prior_attestations=prior)
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

    def test_separate_runs_can_recover_without_repeating_first_provider(self):
        first=engine()
        first.adapters["goal"].cache.clear()
        self.assertIsNone(first.lookup(SIGNAL)[0])
        self.assertEqual(set(first.captured[KEY]),{"api_football"})
        journal,stats=merge_attestations(empty_attestations(),first.captured,now=NOW)
        self.assertEqual(stats["inserted"],1)
        self.assertEqual(stats["total_claims"],1)
        self.assertEqual(journal["records"][KEY]["api_football"]["home_goals"],2)
        second=engine(prior=journal)
        second.adapters["api_football"].days.clear()
        final,reason=second.lookup(SIGNAL)
        self.assertEqual(reason,"verified_two_provider_regulation_ft")
        self.assertEqual((final["home_goals"],final["away_goals"]),(2,1))
        self.assertEqual(set(second.confirmations[KEY]),{"goal","api_football"})
        journal2,stats2=merge_attestations(journal,second.captured,now=NOW)
        self.assertEqual(stats2["inserted"],1)
        self.assertEqual(set(journal2["records"][KEY]),{"api_football","goal"})
        self.assertEqual(journal["records"][KEY]["api_football"],
                         journal2["records"][KEY]["api_football"])

    def test_changing_provider_ft_is_quarantined_not_overwritten(self):
        first=engine()
        first.adapters["goal"].cache.clear()
        first.lookup(SIGNAL)
        journal,_=merge_attestations(empty_attestations(),first.captured,now=NOW)
        old=journal["records"][KEY]["api_football"]
        def corrected(a,g,r,m):
            a["score"]["fulltime"]["home"]=3
            a["goals"]["home"]=3
        second=engine(mut=corrected,prior=journal)
        self.assertIsNone(second.lookup(SIGNAL)[0])
        self.assertEqual(second.revisions[KEY],["api_football"])
        journal2,stats=merge_attestations(journal,second.captured,now=NOW)
        self.assertEqual(stats["revisions_quarantined"],1)
        self.assertEqual(journal2["records"][KEY]["api_football"],old)
        self.assertIn(KEY,journal2["conflicts"])
        self.assertIsNone(engine(prior=journal2).lookup(SIGNAL)[0])

    def test_damaged_or_future_saved_proof_cannot_complete_consensus(self):
        first=engine()
        first.adapters["goal"].cache.clear()
        first.lookup(SIGNAL)
        old,_=merge_attestations(empty_attestations(),first.captured,now=NOW)
        damaged=copy.deepcopy(old)
        damaged["records"][KEY]["api_football"]["home_goals"]=99
        second=engine(prior=damaged)
        second.adapters["api_football"].days.clear()
        self.assertIsNone(second.lookup(SIGNAL)[0])
        self.assertGreater(second.invalid_saved["identity_or_timestamp_invalid"],0)
        future=copy.deepcopy(old)
        proof=future["records"][KEY]["api_football"]
        candidate=review()["games"][0]["candidates"][0]
        self.assertTrue(valid(old["records"][KEY]["api_football"],
                              key=KEY,candidate=candidate,now=NOW))
        self.assertFalse(valid(proof,key=KEY,candidate=candidate,
            now=datetime(2026,10,28,18,30,tzinfo=timezone.utc)))

    def test_score_hold_still_applies_to_cross_run_proofs(self):
        first=engine()
        first.adapters["goal"].cache.clear()
        first.lookup(SIGNAL)
        journal,_=merge_attestations(empty_attestations(),first.captured,now=NOW)
        second=engine(prior=journal,hold=[KEY])
        second.adapters["api_football"].days.clear()
        self.assertIsNone(second.lookup(SIGNAL)[0])
        self.assertEqual(second.reasons["official_score_hold"],1)
        self.assertEqual(set(second.captured[KEY]),{"goal"})

    def test_science_keeps_source_provenance_without_certifying_capture_clock(self):
        old={"status":"PENDING","home":"Home","away":"Away",
             "kickoff_utc":KO,"reason":"no_verified_ft_yet"}
        self.assertNotIn("dual_provider_corroboration",ft_science_snapshot(old))
        row={**old,"status":"FINAL","result":{"home_goals":2,
             "away_goals":1,"source":"https://v3.football.api-sports.io/fixtures?id=123456",
             "evidence":"dual_provider_only"},
             "dual_provider_corroboration":{
                "attestation_sha256":{"goal":"a"*64,"api_football":"b"*64},
                "first_observed_at_utc":{"goal":KO,"api_football":KO},
                "chronology_certified":False}}
        self.assertEqual(ft_science_quality(row),
            "TWO_PROVIDER_FT_CHRONOLOGY_NOT_CERTIFIED")
        self.assertIn("dual_provider_corroboration",ft_science_snapshot(row))

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
