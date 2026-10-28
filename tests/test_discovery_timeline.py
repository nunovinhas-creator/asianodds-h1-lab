"""Synthetic regression tests. No claims of real statistical validation."""
import json
import tempfile
import unittest
from pathlib import Path

from h1lab.discovery_timeline import build
from scripts.lab_discoveries import main


def hypothesis(n=10, hits=6, diff=.10, state="EXPLORATORIO"):
    return {
        "id": "P5-fixture", "label": "Duas mensagens e λ sobe",
        "definition": {"op": "HAS", "a": "G_MULTI_ALERT"}, "state": state,
        "outcomes": {"OVER_2_5": {
            "matches": 25, "known": n, "hits": hits, "misses": n-hits,
            "rate": hits/n, "reference_known": 15, "reference_rate": hits/n-diff,
            "diff": diff, "ci95": [.25, .85], "diff_ci95": [-.1, .3],
            "p_two_sided": .2, "q_bh": 1, "temporal_stability": "NOT_ENOUGH_PER_HALF",
            "ft_coverage": .8, "evidence": "NOT_SIGNIFICANT_AFTER_FDR"}}}


def report(t, **kwargs):
    return {"status": "LAB_EXPLORATORY_RESEARCH_NOT_BETTING", "generated_at": t,
            "patterns": [hypothesis(**kwargs)], "combinations_top": [], "frozen": []}


T1 = "2026-10-28T10:00:00+00:00"
T2 = "2026-10-28T11:00:00+00:00"
T3 = "2026-10-28T12:00:00+00:00"


class DiscoveryTests(unittest.TestCase):
    def test_explicit_baseline_and_rerun_without_events(self):
        first, view, events = build(report(T1), {"entries": []}, {"matches": {}})
        self.assertEqual(events, [])
        self.assertEqual(view["baseline_at"], T1)
        state, public, events = build(report(T2), {"entries": []}, {"matches": {}}, first)
        self.assertEqual(events, [])
        self.assertEqual(state, first)
        self.assertEqual(public["timeline"], [])

    def test_new_ft_improvement_and_stability(self):
        start, _, _ = build(report(T1), {"entries": []}, {"matches": {}})
        upd, pub, ev = build(report(T2, n=12, hits=9, diff=.18), {"entries": []}, {"matches": {}}, start)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["kind"], "IMPROVED")
        self.assertEqual(ev[0]["ft_delta"], 2)
        self.assertEqual(ev[0]["changes"]["known"], {"from": 10, "to": 12})
        self.assertEqual(pub["patterns"]["P5-fixture|OVER_2_5"]["points"][0]["kind"], "BASELINE")
        again, _, ev2 = build(report(T3, n=12, hits=9, diff=.18), {"entries": []}, {"matches": {}}, upd)
        self.assertEqual(ev2, [])
        self.assertEqual(again, upd)

    def test_degraded_new_evidence_no_false_ranking_event(self):
        initial, _, _ = build(report(T1), {"entries": []}, {"matches": {}})
        low, _, ev = build(report(T2, n=12, hits=7, diff=.01), {"entries": []}, {"matches": {}}, initial)
        self.assertEqual(ev[0]["kind"], "DEGRADED")
        # Reference changed despite no further FT: not an improved discovery.
        _, _, next_events = build(report(T3, n=12, hits=7, diff=.04),
                                  {"entries": []}, {"matches": {}}, low)
        self.assertEqual(next_events[0]["kind"], "RECALCULATED")

    def test_sign_reversal_is_not_improvement(self):
        base, _, _ = build(report(T1, diff=-.10), {"entries": []}, {"matches": {}})
        _, _, events = build(report(T2, n=11, hits=7, diff=.19),
                             {"entries": []}, {"matches": {}}, base)
        self.assertEqual(events[0]["kind"], "SIGN_REVERSAL")

    def test_candidate_and_rejection_are_only_engine_states(self):
        base, _, _ = build(report(T1), {"entries": []}, {"matches": {}})
        candidate, _, ev = build(report(T2, state="CANDIDATO"), {"entries": []}, {"matches": {}}, base)
        self.assertEqual(ev[0]["kind"], "CANDIDATE")
        rejected, _, ev = build(report(T3, state="REJEITADO"), {"entries": []}, {"matches": {}}, candidate)
        self.assertEqual(ev[0]["kind"], "REJECTED")
        self.assertEqual(rejected["patterns"]["P5-fixture|OVER_2_5"]["latest"]["state"], "REJEITADO")

    def test_new_pattern_not_backdated_and_retained_when_unranked(self):
        base, _, _ = build(report(T1), {"entries": []}, {"matches": {}})
        nxt, _, ev = build({"status": "LAB_EXPLORATORY_RESEARCH_NOT_BETTING",
                             "generated_at": T2, "patterns": [], "combinations_top": [],
                             "frozen": []}, {"entries": []}, {"matches": {}}, base)
        self.assertEqual(ev, [])
        self.assertIn("P5-fixture|OVER_2_5", nxt["patterns"])
        new = hypothesis()
        new["id"] = "P5-new"
        _, _, ev = build({"status": "LAB_EXPLORATORY_RESEARCH_NOT_BETTING",
                          "generated_at": T3, "patterns": [new], "combinations_top": [],
                          "frozen": []}, {"entries": []}, {"matches": {}}, nxt)
        self.assertEqual(ev[0]["kind"], "NEW_PATTERN")

    def test_prospective_ft_requires_pre_kickoff_and_ninety_minutes(self):
        first = {"entries": [
            {"match_key": "a", "match_label": "A vs B", "kickoff_utc": "2026-10-28T10:00:00+00:00",
             "first_detected_at": "2026-10-28T09:00:00+00:00",
             "observed_through": "2026-10-28T09:59:00+00:00",
             "category_at_first_detection": "RISING_WITH_FLAT", "rule_version": 1},
            {"match_key": "b", "match_label": "C vs D", "kickoff_utc": "2026-10-28T10:00:00+00:00",
             "first_detected_at": "2026-10-28T10:01:00+00:00",
             "observed_through": "2026-10-28T09:00:00+00:00",
             "category_at_first_detection": "FALLING"}]}
        ledger = {"matches": {
            "a": {"status": "FINAL", "checked_at": "2026-10-28T11:31:00+00:00",
                  "result": {"home_goals": 2, "away_goals": 1, "evidence": "synthetic"}},
            "b": {"status": "FINAL", "checked_at": "2026-10-28T11:31:00+00:00",
                  "result": {"home_goals": 3, "away_goals": 2}}}}
        initial, public, _ = build(report(T1), first, ledger)
        self.assertEqual(public["prospective"]["settled_total"], 1)
        self.assertEqual(public["prospective"]["by_first_detection_category"]["RISING_WITH_FLAT"],
                         {"known_ft": 1, "over_2_5": 1, "btts_yes": 1})
        self.assertTrue(initial["prospective_settled"]["a"]["over_2_5"])
        ledger["matches"]["a"]["result"]["home_goals"] = 0
        with self.assertRaisesRegex(ValueError, "immutable prospective FT conflict"):
            build(report(T2), first, ledger, initial)

    def test_missing_ft_never_red(self):
        first = {"entries": [{"match_key": "a", "match_label": "A vs B",
                 "kickoff_utc": "2026-10-28T10:00:00+00:00",
                 "first_detected_at": "2026-10-28T09:00:00+00:00",
                 "observed_through": "2026-10-28T09:05:00+00:00",
                 "category_at_first_detection": "FLAT_EACH_EPISODE"}]}
        _, public, _ = build(report(T1), first, {"matches": {"a": {"status": "PENDING"}}})
        self.assertEqual(public["prospective"]["settled_total"], 0)
        self.assertEqual(public["prospective"]["detected_total"], 1)

    def test_runner_archives_events_without_duplicates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for path, data in [
                ("docs/lab/pattern-research.json", report(T1)),
                ("data/lab/pattern-watch-first-seen.json", {"entries": []}),
                ("data/lab/ft-ledger.json", {"matches": {}})]:
                p = root / path
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(data), encoding="utf-8")
            main(["--root", td])
            self.assertFalse(list((root / "data/lab").glob("discovery-events-*")))
            path = root / "docs/lab/pattern-research.json"
            path.write_text(json.dumps(report(T2, n=11, hits=7)), encoding="utf-8")
            main(["--root", td])
            archive = root / "data/lab/discovery-events-2026-10.jsonl"
            line = archive.read_text(encoding="utf-8")
            self.assertEqual(len(line.splitlines()), 1)
            main(["--root", td])
            self.assertEqual(archive.read_text(encoding="utf-8"), line)


if __name__ == "__main__":
    unittest.main()
