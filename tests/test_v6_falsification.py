"""V6 falsification: 10 codes, no posthoc promotion and no backdating."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from h1lab.v6_falsification import TEST_IDS, evaluate, score_rows, ten_tests
from h1lab.v6_shadow import append_journal, read_journal
from h1lab.v6_hypotheses import ensure_registered
from h1lab.v6_science_memory import fact, append_events, read_stream

T0 = datetime(2026, 10, 29, 21, tzinfo=timezone.utc)


def row(match_key, *, registered=True, pattern=True, market=.56, context=None,
        ko="2026-10-29T18:00:00+00:00"):
    return {
        "event_id": "t:" + match_key, "match_key": match_key,
        "known_at": ("2026-10-28T15:00:00+00:00" if registered else
                     "2026-10-28T14:00:00+00:00"),
        "observed_at": "2026-10-28T13:45:00+00:00",
        "kickoff_utc": ko, "message_count_at_capture":2,
        "market_probability_over_2_5":market,
        "price_quality":{"status":"USABLE","after":{"line":2.75}, "lambda_after":2.9},
        "pattern_original_posthoc":pattern,"pattern_strict_posthoc":pattern,
        **({"falsification_context":context} if context else {})}


def context(*, category="RISING_WITH_FLAT", episode=2, competition="CUP", agreements=(True,)):
    return {"schema":"V6-FALSIFICATION-CONTEXT-1",
            "watch_category":category,
            "episodes":episode,"episode_directions":{"up":1,"down":0,"flat":1},
            "first_lead_minutes":90,
            "competition_group_heuristic":competition,
            "cross_market_agreements":list(agreements)}


def evidence(key, source_hash, *, checked="2026-10-29T20:00:00+00:00",
             status="CONFIRMED", over=True):
    return {"id":"EV:"+key,"event":{
        "match_key":key,"previous_evidence_event_id":None,
        "event_id":"FT:"+key, "state":status,
        "frozen_source_sha256":source_hash,
        "ft_checked_at":checked,
        "ft":{"over_2_5":over,"home_goals":2 if over else 1,"away_goals":1 if over else 0}
    }}


class TenFalsifications(unittest.TestCase):
    def test_all_ten_codes_even_with_no_finals(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg,_=ensure_registered(tmp, datetime(2026,10,28,14,41,35,tzinfo=timezone.utc))
            append_journal(tmp,T0,[row("a",context=context())])
            all_rows=read_journal(tmp)
            report=evaluate(all_rows,[],reg,T0)
            self.assertEqual(tuple(t["code"] for t in report["checks"]),TEST_IDS)
            self.assertEqual(len(report["checks"]),10)
            self.assertEqual(report["check_result_counts"],{"INSUFFICIENT_N":10})
            self.assertEqual(report["overall"],"INCONCLUSIVO")
            self.assertEqual(report["sample"]["selected_scored"],0)

    def test_pre_registration_not_confirmatory_and_not_retrodated(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg,_=ensure_registered(tmp,datetime(2026,10,28,14,41,35,tzinfo=timezone.utc))
            append_journal(tmp,T0,[row("before",registered=False),row("after",registered=True)])
            records=read_journal(tmp)
            events=[evidence(r["match_key"],r["sha256"]) for r in records]
            prospective,scored,excluded=score_rows(records,events,reg,T0)
            self.assertEqual([r["key"] for r in scored],["after"])
            self.assertEqual(excluded["captured_before_formal_registration"],1)

    def test_missing_or_unchecked_ft_is_not_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg,_=ensure_registered(tmp,datetime(2026,10,28,14,41,35,tzinfo=timezone.utc))
            append_journal(tmp,T0,[row("a")])
            frozen=read_journal(tmp)
            events=[evidence("a",frozen[0]["sha256"],checked=None)]
            _,scored,ex=score_rows(frozen,events,reg,T0)
            self.assertFalse(scored)
            self.assertEqual(ex["ft_not_temporally_proven"],1)

    def test_no_reconstruction_of_missing_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg,_=ensure_registered(tmp,datetime(2026,10,28,14,41,35,tzinfo=timezone.utc))
            append_journal(tmp,T0,[row("old")])
            frozen=read_journal(tmp)
            events=[evidence("old",frozen[0]["sha256"])]
            prospective, scored, _=score_rows(frozen,events,reg,T0)
            tests=ten_tests(prospective,scored,registry=reg,now=T0)
            by={t["code"]:t for t in tests}
            self.assertEqual(by["F01_EPISODE_INDEPENDENCE"]["n"],0)
            self.assertEqual(by["F03_1X2_AH_CONSISTENCY"]["result"],"INSUFFICIENT_N")
            self.assertEqual(by["F05_COMPETITION_CONTEXT"]["diagnostics"]["groups"]["UNKNOWN"]["n"],1)

    def test_matching_never_reuses_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg,_=ensure_registered(tmp,datetime(2026,10,28,14,41,35,tzinfo=timezone.utc))
            base=[row("s1",context=context()),row("s2",context=context()),
                  row("control",pattern=False,context=context())]
            append_journal(tmp,T0,base)
            frozen=read_journal(tmp)
            events=[evidence(r["match_key"],r["sha256"]) for r in frozen]
            ps,ss,_=score_rows(frozen,events,reg,T0)
            checks=ten_tests(ps,ss,registry=reg,now=T0)
            matched=next(c for c in checks if c["code"]=="F09_MATCHED_MARKET_PEERS")
            self.assertEqual(matched["n"],1)
            self.assertEqual(matched["result"],"INSUFFICIENT_N")

    def test_future_or_postkickoff_freeze_not_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg,_=ensure_registered(tmp,datetime(2026,10,28,14,41,35,tzinfo=timezone.utc))
            append_journal(tmp,T0,[row("future",ko="2026-11-10T18:00:00+00:00"),
                                   row("bad",ko="2026-10-28T14:00:00+00:00")])
            _,ss,ex=score_rows(read_journal(tmp),[],reg,T0)
            self.assertFalse(ss)
            self.assertEqual(ex["not_completed_prospective_freeze"],2)

    def test_empty_checks_never_pass_from_historical_11_of_10(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg,_=ensure_registered(tmp,datetime(2026,10,28,14,41,35,tzinfo=timezone.utc))
            result=evaluate([],[],reg,T0)
            self.assertTrue(all(r["result"]=="INSUFFICIENT_N" for r in result["checks"]))
            self.assertEqual(result["overall"],"INCONCLUSIVO")


if __name__=="__main__":
    unittest.main()
