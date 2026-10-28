"""LAB V5 research engine: market maths, features, hypotheses, prospective
validation, similarity and the real tracked data. No network, no H1 writes."""
import copy
import json
import math
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from h1lab import lab_stats, market_math, pattern_engine, similarity
from h1lab.pattern_features import PATTERNS, match_features
from h1lab.timeline import collect_timelines, read_sources

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def iso(d):
    return d.isoformat(timespec="seconds")


def alert(i, *, ko, obs, up, mid=None, line=2.5):
    """One H1-format Total alert. ``up``: line 2.5->2.75 (implied goals up) or 2.5->2.25."""
    after = line + (0.25 if up else -0.25)
    return {"event_id": "c:%d" % (mid or i), "observed_at": iso(obs), "match_key": "k%03d" % i,
            "home": "Home %d" % i, "away": "Away %d" % i, "kickoff_utc": iso(ko), "market": "total",
            "total_before": line, "over_before": 1.90, "under_before": 1.90,
            "total_after": after, "over_after": 1.95 if up else 1.85, "under_after": 1.85 if up else 1.95,
            "competition": "Test League", "h1": False, "message_id": mid or i, "source_url": "x"}


def synthetic(n, start, *, effect=True, first_id=0):
    alerts, ledger = [], {}
    for j in range(n):
        i = first_id + j
        ko = start + timedelta(hours=4 * j)
        up = i % 2 == 0
        alerts.append(alert(i, ko=ko, obs=ko - timedelta(hours=3), up=up))
        over = up if effect else (j % 4 in (0, 3))
        h, a = (2, 1) if over else (1, 0)
        ledger["k%03d" % i] = {"status": "FINAL", "checked_at": iso(ko + timedelta(hours=4)),
                               "result": {"home_goals": h, "away_goals": a, "source": "https://x"}}
    return alerts, ledger


def timelines(alerts):
    return collect_timelines(alerts, [])[0]


class MarketMath(unittest.TestCase):
    def test_even_half_line_is_fifty_fifty(self):
        lam = market_math.implied_lambda(2.5, 1.9, 1.9)
        self.assertAlmostEqual(market_math.prob_total_over(lam), 0.5, places=3)

    def test_cross_line_drift_is_not_a_drop_in_goals(self):
        # Audit A3 example: Over price rises 1.86 -> 1.96 while the line rises.
        before = market_math.implied_lambda(3.0, 1.86, 1.98)
        after = market_math.implied_lambda(3.25, 1.96, 1.88)
        self.assertGreater(after, before)

    def test_monotone_and_quarter_lines(self):
        lams = [market_math.implied_lambda(l, 1.9, 1.9) for l in (2.0, 2.25, 2.5, 2.75, 3.0)]
        self.assertEqual(lams, sorted(lams))
        self.assertLess(market_math.implied_lambda(2.5, 1.7, 2.1), market_math.implied_lambda(2.5, 2.1, 1.7) and 99)

    def test_invalid_inputs(self):
        for args in ((2.4, 1.9, 1.9), (2.5, 1.0, 1.9), (2.5, True, 1.9), (2.5, float("nan"), 1.9), (None, 2, 2)):
            self.assertIsNone(market_math.implied_lambda(*args))
        self.assertIsNone(market_math.margin(1.9, 0.9))
        self.assertAlmostEqual(market_math.margin(1.9, 1.9), 2 / 1.9 - 1)


class Stats(unittest.TestCase):
    def test_fisher_known_value(self):
        self.assertAlmostEqual(lab_stats.fisher(3, 4, 1, 4), 0.4857, places=3)
        self.assertAlmostEqual(lab_stats.fisher(3, 4, 1, 4, "greater"), 0.2429, places=3)

    def test_bh_and_wilson(self):
        q = lab_stats.bh_qvalues([0.01, 0.04, 0.03, 0.5])
        self.assertAlmostEqual(q[0], 0.04)
        self.assertTrue(all(0 <= x <= 1 for x in q))
        lo, hi = lab_stats.wilson(5, 10)
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)


class Features(unittest.TestCase):
    def test_post_kickoff_never_a_feature(self):
        ko = T0
        a = [alert(1, ko=ko, obs=ko - timedelta(hours=2), up=True),
             alert(1, ko=ko, obs=ko + timedelta(minutes=20), up=False, mid=2)]
        f = match_features(timelines(a)[0])
        self.assertEqual((f["prekickoff_messages"], f["post_kickoff_messages"]), (1, 1))
        self.assertNotIn("M_TOTAL_LINE_DOWN", f["patterns"])
        self.assertEqual(f["decision_at"], iso(ko - timedelta(hours=2)))

    def test_identical_repeat_is_one_episode(self):
        ko = T0
        a = [alert(1, ko=ko, obs=ko - timedelta(hours=2), up=True),
             alert(1, ko=ko, obs=ko - timedelta(hours=2) + timedelta(seconds=1), up=True, mid=2)]
        f = match_features(timelines(a)[0])
        self.assertEqual((f["prekickoff_messages"], f["episodes"]), (2, 1))
        self.assertNotIn("G_REPEAT_SAME_DIRECTION", f["patterns"])
        self.assertNotIn("G_MULTI_EPISODE", f["patterns"])

    def test_price_patterns_only_at_same_line(self):
        ko = T0
        x = alert(1, ko=ko, obs=ko - timedelta(hours=2), up=True)
        f = match_features(timelines([x])[0])
        self.assertFalse(any("PRICE" in p for p in f["patterns"]))
        x.update(total_after=2.5, over_after=2.05, under_after=1.78)
        f = match_features(timelines([x])[0])
        self.assertIn("M_OVER_PRICE_UP_SAME_LINE", f["patterns"])
        self.assertIn("M_IMPLIED_GOALS_DOWN", f["patterns"])

    def test_catalogue_is_closed(self):
        x = alert(1, ko=T0, obs=T0 - timedelta(hours=30), up=True)
        f = match_features(timelines([x])[0])
        self.assertTrue(set(f["patterns"]) <= set(PATTERNS))


class Engine(unittest.TestCase):
    def test_generation_ignores_outcomes(self):
        alerts, _ = synthetic(40, T0)
        feats = [match_features(t) for t in timelines(alerts)]
        a, _ = pattern_engine.generate_hypotheses(feats)
        b, _ = pattern_engine.generate_hypotheses(copy.deepcopy(feats))
        self.assertEqual([h["id"] for h in a], [h["id"] for h in b])
        sets = [h["members"] for h in a]
        self.assertEqual(len(sets), len(set(sets)), "redundant match sets kept")

    def test_freeze_then_validate_out_of_sample(self):
        alerts, ledger = synthetic(60, T0)
        now1 = T0 + timedelta(days=12)
        rep, reg, _ = pattern_engine.run(timelines(alerts), {"matches": ledger},
                                         {"schema_version": 1, "entries": []}, now=now1)
        self.assertTrue(rep["changes"]["new_frozen_candidates"])
        self.assertTrue(all(e["discovery"]["known"] >= 20 for e in reg["entries"]))
        self.assertEqual({e["decisions"] == [] for e in reg["entries"]}, {True})
        frozen = {e["id"] for e in reg["entries"]}
        # Same data again: nothing out-of-sample, so no state can pass CANDIDATO.
        rep2, reg2, _ = pattern_engine.run(timelines(alerts), {"matches": ledger}, reg, now=now1)
        self.assertEqual({f["state"] for f in rep2["frozen"]}, {"CANDIDATO"})
        self.assertEqual({f["out_of_sample"]["known"] for f in rep2["frozen"]}, {0})
        # New prospective matches that keep the effect.
        more, more_ledger = synthetic(70, now1 + timedelta(hours=4), first_id=100)
        all_ledger = dict(ledger, **more_ledger)
        now2 = now1 + timedelta(days=14)
        rep3, reg3, _ = pattern_engine.run(timelines(alerts + more), {"matches": all_ledger}, reg2, now=now2)
        states = {f["id"]: f["state"] for f in rep3["frozen"]}
        self.assertTrue(set(states) == frozen)
        self.assertIn("VALIDADO", states.values())
        pattern_engine.assert_append_only(reg2, reg3)
        for e in reg3["entries"]:
            self.assertEqual(e["decisions"][0]["checkpoint"] if e["decisions"] else 30, 30)

    def test_effect_that_vanishes_is_rejected(self):
        alerts, ledger = synthetic(60, T0)
        now1 = T0 + timedelta(days=12)
        _, reg, _ = pattern_engine.run(timelines(alerts), {"matches": ledger},
                                       {"schema_version": 1, "entries": []}, now=now1)
        more, more_ledger = synthetic(70, now1 + timedelta(hours=4), first_id=100, effect=False)
        rep, _, _ = pattern_engine.run(timelines(alerts + more), {"matches": dict(ledger, **more_ledger)},
                                       reg, now=now1 + timedelta(days=14))
        self.assertTrue(rep["frozen"])
        self.assertEqual({f["state"] for f in rep["frozen"]}, {"REJEITADO"})

    def test_registry_tampering_refused(self):
        alerts, ledger = synthetic(60, T0)
        _, reg, _ = pattern_engine.run(timelines(alerts), {"matches": ledger},
                                       {"schema_version": 1, "entries": []}, now=T0 + timedelta(days=12))
        bad = copy.deepcopy(reg)
        bad["entries"][0]["definition"] = {"op": "HAS", "a": "M_LATE"}
        with self.assertRaises(ValueError):
            pattern_engine.load_registry(bad)
        bad = copy.deepcopy(reg)
        bad["entries"][0]["direction"] = {"HIGHER": "LOWER", "LOWER": "HIGHER"}[bad["entries"][0]["direction"]]
        with self.assertRaises(ValueError):
            pattern_engine.assert_append_only(reg, bad)

    def test_no_freeze_without_effect(self):
        alerts, ledger = synthetic(60, T0, effect=False)
        rep, reg, _ = pattern_engine.run(timelines(alerts), {"matches": ledger},
                                         {"schema_version": 1, "entries": []}, now=T0 + timedelta(days=12))
        self.assertEqual(reg["entries"], [])
        self.assertEqual(set(rep["state_counts"]), {"EXPLORATORIO"})

    def test_source_conflict_excluded(self):
        out, prov, conflicts = pattern_engine.outcomes_from(
            {"matches": {"a": {"status": "FINAL", "result": {"home_goals": 1, "away_goals": 0}}}},
            [{"match_key": "a", "status": "final", "home_goals": "2", "away_goals": "0"},
             {"match_key": "b", "status": "final", "home_goals": "0", "away_goals": "0"}])
        self.assertEqual((sorted(out), conflicts, prov["b"]), (["b"], ["a"], "H1_RESULTS_CSV"))

    def test_incremental_cache_reuse(self):
        alerts, ledger = synthetic(20, T0)
        tl = timelines(alerts)
        r1, _, cache = pattern_engine.run(tl, {"matches": ledger}, {"schema_version": 1, "entries": []},
                                          now=T0 + timedelta(days=5))
        r2, _, _ = pattern_engine.run(tl, {"matches": ledger}, {"schema_version": 1, "entries": []},
                                      now=T0 + timedelta(days=5), cache=json.loads(json.dumps(cache)))
        self.assertEqual(r2["incremental"], {"reused": 20, "recomputed": 0})
        self.assertEqual(r1["patterns"], r2["patterns"])


class Similarity(unittest.TestCase):
    def test_no_future_and_no_outcome_features(self):
        alerts, ledger = synthetic(12, T0)
        feats = [match_features(t) for t in timelines(alerts)]
        target = feats[-1]
        for c in feats:
            if similarity.eligible(target, c):
                ko = datetime.fromisoformat(c["kickoff_utc"])
                self.assertLessEqual(ko + timedelta(hours=3), datetime.fromisoformat(target["decision_at"]))
        out = {k: v for k, v in pattern_engine.outcomes_from({"matches": ledger})[0].items()}
        flipped = {k: dict(v, OVER_2_5=not v["OVER_2_5"]) for k, v in out.items()}
        a = similarity.neighbours(target, feats, out)
        b = similarity.neighbours(target, feats, flipped)
        self.assertEqual([(n["match_key"], n["similarity"]) for n in a["neighbours"]],
                         [(n["match_key"], n["similarity"]) for n in b["neighbours"]])
        self.assertFalse(similarity.eligible(feats[0], feats[-1]))


class RealData(unittest.TestCase):
    def test_real_tracked_data(self):
        alerts, rows, errors = read_sources(ROOT)
        tl = collect_timelines(alerts, rows, source_errors=errors)[0]
        ledger = json.loads((ROOT / "data/lab/ft-ledger.json").read_text(encoding="utf-8"))
        rep, reg, _ = pattern_engine.run(tl, ledger, {"schema_version": 1, "entries": []},
                                         now=datetime.now(timezone.utc))
        s = rep["scope"]
        finals = {k for k, v in ledger["matches"].items() if v.get("status") == "FINAL"}
        eligible = {t["match_key"] for t in tl}
        self.assertLessEqual(s["ft_confirmed"], len(finals & eligible))
        self.assertEqual(s["research_eligible"] + sum(s["excluded"].values()), s["matches_observed"])
        self.assertTrue(set(rep["state_counts"]) <= set(pattern_engine.STATES))
        text = json.dumps(rep).lower()
        for banned in ('"roi"', '"ev"', '"profit"', '"stake"', '"pick"'):
            self.assertNotIn(banned, text)
        for x in rep["patterns"]:
            for t, st in x["outcomes"].items():
                self.assertEqual(st["hits"] + st["misses"], st["known"])
                if "q_bh" in st:
                    self.assertGreaterEqual(st["q_bh"] + 1e-12, st["p_two_sided"])
        self.assertLessEqual(len(rep["frozen"]), pattern_engine.MAX_ACTIVE_FROZEN)


if __name__ == "__main__":
    unittest.main()
