"""LAB V5 research engine: patterns, combinations, outcome association,
prospective validation and similar-match search. Shadow LAB only.

What it never does: touch H1 files, pick bets, compute ROI/EV, or treat a
historical hit-rate as proof. Classification rules (docs/lab/PATTERN-ENGINE.md):

EXPLORATORIO  default. Computed on all confirmed-FT matches so far.
CANDIDATO     met the discovery criteria and was *frozen* (definition, outcome,
              direction, discovery stats, timestamp) in the append-only
              registry. Fewer than OOS_MIN_EVAL out-of-sample results yet.
EM_VALIDACAO  frozen; out-of-sample results are accumulating (n < checkpoint).
VALIDADO      at a fixed checkpoint (30, then 60, 90 ... OOS matches) the
              one-sided test in the frozen direction passed at the Bonferroni
              level 0.05 / (hypotheses ever frozen), the OOS effect kept its
              sign and size, FT coverage was balanced and, for Over/Under, the
              observed rate also beat the market-implied model probability.
REJEITADO     failed a checkpoint, or reversed early (OOS n >= 15 with an
              effect of the opposite sign of at least 10 pp).

"Out-of-sample" = matches whose *first* pre-kickoff alert was observed after
the hypothesis was frozen. Discovery data is never reused as validation.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from .lab_stats import (bh_qvalues, fisher, implied_z, mean_ci, newcombe_diff, r, wilson)
from .market_math import MATH_VERSION
from .pattern_features import (EXCLUSIVE, FEATURE_VERSION, ORDERABLE, PATTERNS,
                               match_features, outcome)
from .similarity import SIMILARITY_VERSION, neighbours, walk_forward

ENGINE_VERSION = 1
STATUS = "LAB_EXPLORATORY_RESEARCH_NOT_BETTING"
STATES = ("EXPLORATORIO", "CANDIDATO", "EM_VALIDACAO", "VALIDADO", "REJEITADO")
TESTED_OUTCOMES = ("OVER_2_5", "BTTS_YES")  # complements are reported, not re-tested
COMPLEMENT = {"OVER_2_5": "UNDER_2_5", "BTTS_YES": "BTTS_NO"}
MIN_SUPPORT = 5            # matches (any FT status) for a hypothesis to exist
MIN_TEST_N = 10            # confirmed FT in the group AND in its complement
CAND_MIN_N = 20
CAND_MAX_Q = 0.10
CAND_MIN_DIFF = 0.10
MAX_COVERAGE_GAP = 0.20
OOS_MIN_EVAL = 10
CHECKPOINT = 30
EARLY_REJECT_N = 15
EARLY_REJECT_DIFF = 0.10
MAX_ACTIVE_FROZEN = 10
MAX_HYPOTHESES = 800
TRIPLE_BASE_PAIRS = 25
RESULT_DELAY = timedelta(hours=3)


def _utc(v):
    if not isinstance(v, str):
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(timezone.utc) if d.tzinfo else None


# --------------------------------------------------------------------------
# Hypothesis definitions

def canonical(defn):
    return json.dumps(defn, sort_keys=True, separators=(",", ":"))


def hypothesis_id(defn, *, feature_version=None):
    """Stable across later feature schema upgrades for already frozen entries."""
    version = FEATURE_VERSION if feature_version is None else feature_version
    raw = canonical(defn) + "|f%d" % version
    return "P5-" + hashlib.sha256(raw.encode()).hexdigest()[:10]


def definition_sha(defn, *, feature_version=None):
    """Hash a frozen definition using the feature version of that entry."""
    version = FEATURE_VERSION if feature_version is None else feature_version
    return hashlib.sha256((canonical(defn) + "|f%d" % version).encode()).hexdigest()


def holds(defn, f):
    pats = set(f.get("patterns", ()))
    op = defn["op"]
    if op == "HAS":
        return defn["a"] in pats
    if op == "AND":
        return all(x in pats for x in defn["all"])
    if op == "AND_NOT":
        return all(x in pats for x in defn["all"]) and not any(x in pats for x in defn["none"])
    if op == "BEFORE":
        a, b = defn["first"], defn["then"]
        if a not in pats or b not in pats:
            return False
        ta, tb = f["pattern_first_at"].get(a), f["pattern_first_at"].get(b)
        ea, eb = f["pattern_first_episode"].get(a), f["pattern_first_episode"].get(b)
        return ta is not None and tb is not None and ta < tb and ea != eb
    raise ValueError("unknown operator")


def label(defn):
    d = lambda p: PATTERNS[p][2] if p in PATTERNS else p
    op = defn["op"]
    if op == "HAS":
        return d(defn["a"])
    if op == "AND":
        return " E ".join(d(x) for x in defn["all"])
    if op == "AND_NOT":
        return " E ".join(d(x) for x in defn["all"]) + " — SEM: " + " / ".join(d(x) for x in defn["none"])
    return d(defn["first"]) + " — DEPOIS, noutro episódio: " + d(defn["then"])


def complexity(defn):
    return {"HAS": 1, "AND": len(defn.get("all", ())), "BEFORE": 2,
            "AND_NOT": len(defn.get("all", ())) + len(defn.get("none", ()))}[defn["op"]]


def _exclusive(*ps):
    return any(sum(p in g for p in ps) > 1 for g in EXCLUSIVE)


def generate_hypotheses(features, *, min_support=MIN_SUPPORT, max_hypotheses=MAX_HYPOTHESES):
    """Bounded, deterministic generation from match *patterns only* (no outcomes).

    Returns (hypotheses, generation_stats). A hypothesis whose match set equals
    a simpler one already kept is dropped as redundant.
    """
    n = len(features)
    has = defaultdict(set)
    for f in features:
        for p in f["patterns"]:
            has[p].add(f["match_key"])
    universe = {f["match_key"] for f in features}
    pats = sorted(p for p in PATTERNS if min_support <= len(has[p]) <= n - min_support)
    by_key = {f["match_key"]: f for f in features}
    stats = Counter()
    kept, seen_sets = [], {}

    def add(defn, members):
        stats["considered"] += 1
        if len(members) < min_support or len(members) > n - min_support:
            stats["below_support_or_trivial"] += 1
            return
        fs = frozenset(members)
        # Same match set, or its exact complement (the same two-group test),
        # as a simpler hypothesis already kept: record as an equivalent only.
        twin = seen_sets.get(fs) or seen_sets.get(frozenset(universe - fs))
        if twin is not None:
            stats["redundant_same_or_complement_matches"] += 1
            if len(twin["equivalent"]) < 5:
                twin["equivalent"].append({"definition": defn, "complement": fs not in seen_sets})
            return
        entry = {"equivalent": []}
        seen_sets[fs] = entry
        kept.append((complexity(defn), -len(members), hypothesis_id(defn), defn, fs, entry))

    for p in pats:
        add({"op": "HAS", "a": p}, has[p])
    pairs = []
    for i, a in enumerate(pats):
        for b in pats[i + 1:]:
            if _exclusive(a, b):
                continue
            both = has[a] & has[b]
            if len(both) >= min_support:
                pairs.append((len(both), a, b))
                add({"op": "AND", "all": [a, b]}, both)
            for x, y in ((a, b), (b, a)):
                only = has[x] - has[y]
                if len(only) >= min_support and len(both) >= min_support:
                    add({"op": "AND_NOT", "all": [x], "none": [y]}, only)
    order = [p for p in pats if p in ORDERABLE]
    for a in order:
        for b in order:
            if a == b:
                continue
            defn = {"op": "BEFORE", "first": a, "then": b}
            members = {k for k in has[a] & has[b] if holds(defn, by_key[k])}
            if members:
                add(defn, members)
    pairs.sort(key=lambda x: (-x[0], x[1], x[2]))
    for _, a, b in pairs[:TRIPLE_BASE_PAIRS]:
        base = has[a] & has[b]
        for c in pats:
            if c in (a, b) or _exclusive(a, b, c):
                continue
            with_c = base & has[c]
            if len(with_c) >= min_support:
                add({"op": "AND_NOT", "all": [a, b], "none": [c]}, base - has[c])
    kept.sort(key=lambda x: (x[0], x[1], x[2]))
    stats["generated"] = len(kept)
    stats["capped"] = max(0, len(kept) - max_hypotheses)
    out = [{"id": h, "definition": d, "complexity": c, "members": fs,
            "equivalent": [label(x["definition"]) + (" (complemento)" if x["complement"] else "")
                           for x in e["equivalent"]]}
           for c, _, h, d, fs, e in kept[:max_hypotheses]]
    stats["individual_patterns_with_support"] = len(pats)
    stats["universe_matches"] = len(universe)
    return out, dict(stats)


# --------------------------------------------------------------------------
# Outcome evaluation

def group_stats(members, eval_keys, outcomes, past_keys, features_by_key, target):
    """Rates for one hypothesis vs its complement inside ``eval_keys``."""
    inside = [k for k in eval_keys if k in members]
    outside = [k for k in eval_keys if k not in members]
    kin = [k for k in inside if k in outcomes]
    kout = [k for k in outside if k in outcomes]
    hin = sum(outcomes[k][target] for k in kin)
    hout = sum(outcomes[k][target] for k in kout)
    pin = [k for k in inside if k in past_keys]
    pout = [k for k in outside if k in past_keys]
    cov_in = len(kin) / len(pin) if pin else None
    cov_out = len(kout) / len(pout) if pout else None
    res = {"matches": len(inside), "known": len(kin), "unknown_past": len(pin) - len(kin),
           "future_or_grace": len(inside) - len(pin), "hits": hin, "misses": len(kin) - hin,
           "rate": r(hin / len(kin)) if kin else None,
           "ci95": [r(x) for x in wilson(hin, len(kin))] if kin else None,
           "reference_known": len(kout), "reference_hits": hout,
           "reference_rate": r(hout / len(kout)) if kout else None,
           "ft_coverage": r(cov_in), "reference_ft_coverage": r(cov_out)}
    if kin and kout:
        res["diff"] = r(hin / len(kin) - hout / len(kout))
        res["diff_ci95"] = [r(x) for x in newcombe_diff(hin, len(kin), hout, len(kout))]
    if target in ("OVER_2_5",):
        probs = [features_by_key[k]["p_over_2_5_model"] for k in kin
                 if features_by_key[k].get("p_over_2_5_model") is not None]
        if probs and len(probs) == len(kin):
            res["market_implied_rate"] = r(sum(probs) / len(probs))
            res["vs_market_implied"] = r(hin / len(kin) - sum(probs) / len(probs))
            res["vs_market_z"] = r(implied_z(hin, probs), 3)
    return res


def _goals(keys, outcomes):
    vals = [outcomes[k]["total_goals"] for k in keys if k in outcomes]
    ci = mean_ci(vals)
    return {"known": len(vals), "mean": r(sum(vals) / len(vals), 3) if vals else None,
            "ci95": [r(x, 3) for x in ci] if ci else None}


def periods(members, keys, outcomes, features_by_key, target):
    """Per kickoff day and first/second chronological half of confirmed FTs."""
    known = sorted((features_by_key[k]["kickoff_utc"], k) for k in keys if k in outcomes)
    by_day = defaultdict(lambda: [0, 0, 0, 0])
    for ko, k in known:
        row = by_day[ko[:10]]
        if k in members:
            row[0] += 1
            row[1] += outcomes[k][target]
        else:
            row[2] += 1
            row[3] += outcomes[k][target]
    halves = []
    mid = len(known) // 2
    for part in (known[:mid], known[mid:]):
        ki = [k for _, k in part if k in members]
        ko_ = [k for _, k in part if k not in members]
        hi = sum(outcomes[k][target] for k in ki)
        ho = sum(outcomes[k][target] for k in ko_)
        halves.append({"known": len(ki), "rate": r(hi / len(ki)) if ki else None,
                       "reference_rate": r(ho / len(ko_)) if ko_ else None,
                       "diff": r(hi / len(ki) - ho / len(ko_)) if ki and ko_ else None})
    return {"by_kickoff_day": {d: {"known": v[0], "rate": r(v[1] / v[0]) if v[0] else None,
                                   "reference_known": v[2], "reference_rate": r(v[3] / v[2]) if v[2] else None}
                               for d, v in sorted(by_day.items())},
            "halves": halves}


def _stable(p):
    ds = [h["diff"] for h in p["halves"] if h["diff"] is not None and h["known"] >= 5]
    if len(ds) < 2:
        return None
    return all(d > 0 for d in ds) or all(d < 0 for d in ds)


# --------------------------------------------------------------------------
# Registry (append-only)

def load_registry(raw):
    reg = raw if isinstance(raw, dict) else {"schema_version": 1, "entries": []}
    if reg.get("schema_version") != 1 or not isinstance(reg.get("entries"), list):
        raise ValueError("Incompatible pattern registry")
    ids = set()
    for e in reg["entries"]:
        frozen_version = e.get("feature_version", 1)
        if (e.get("definition_sha256") != definition_sha(e["definition"], feature_version=frozen_version)
                or e["id"] != hypothesis_id(e["definition"], feature_version=frozen_version)):
            raise ValueError("Frozen hypothesis definition altered: " + str(e.get("id")))
        if e["id"] in ids:
            raise ValueError("Duplicate frozen hypothesis")
        ids.add(e["id"])
    return reg


def assert_append_only(old, new):
    """Every old entry must survive unchanged except for appended decisions."""
    old_by = {e["id"]: e for e in old.get("entries", [])}
    new_by = {e["id"]: e for e in new.get("entries", [])}
    for k, e in old_by.items():
        n = new_by.get(k)
        if n is None:
            raise ValueError("Frozen hypothesis removed: " + k)
        a, b = dict(e), dict(n)
        da, db = a.pop("decisions", []), b.pop("decisions", [])
        if a != b or db[:len(da)] != da:
            raise ValueError("Frozen hypothesis rewritten: " + k)


def oos_state(entry, oos, alpha):
    """Deterministic state for a frozen hypothesis given cumulative OOS stats."""
    n = oos["known"]
    sign = 1 if entry["direction"] == "HIGHER" else -1
    diff = oos.get("diff")
    if n < OOS_MIN_EVAL:
        return "CANDIDATO", None
    if n >= EARLY_REJECT_N and diff is not None and sign * diff <= -EARLY_REJECT_DIFF:
        return "REJEITADO", "early_reversal"
    if n < CHECKPOINT:
        return "EM_VALIDACAO", None
    return None, "checkpoint_due"


def checkpoint_decision(entry, oos, alpha):
    sign = 1 if entry["direction"] == "HIGHER" else -1
    alt = "greater" if sign > 0 else "less"
    p = (fisher(oos["hits"], oos["known"], oos["reference_hits"], oos["reference_known"], alt)
         if oos.get("reference_known") else None)
    reasons = []
    if p is None or p > alpha:
        reasons.append("oos_test_not_significant")
    d = oos.get("diff")
    if d is None or sign * d < CAND_MIN_DIFF / 2:
        reasons.append("oos_effect_too_small_or_reversed")
    ci, co = oos.get("ft_coverage"), oos.get("reference_ft_coverage")
    if ci is None or co is None or abs(ci - co) > MAX_COVERAGE_GAP:
        reasons.append("ft_coverage_imbalanced")
    if entry["outcome"] == "OVER_2_5":
        z = oos.get("vs_market_z")
        if z is None or sign * z < 1.645:
            reasons.append("does_not_beat_market_implied")
    return ("VALIDADO" if not reasons else "REJEITADO"), {"p_one_sided": r(p, 6), "alpha": r(alpha, 6),
                                                        "failed": reasons}


# --------------------------------------------------------------------------
# Main entry

def outcomes_from(ledger, h1_results=()):
    """Confirmed 90-minute scores. LAB ledger first; H1 results.csv only fills gaps.

    A disagreement between the two sources excludes the match (never chosen).
    """
    out, prov, conflicts = {}, {}, []
    for key, row in (ledger.get("matches") or {}).items():
        res = row.get("result") if row.get("status") == "FINAL" else None
        if isinstance(res, dict) and type(res.get("home_goals")) is int and type(res.get("away_goals")) is int:
            out[key] = outcome(res)
            prov[key] = "LAB_LEDGER" + ("" if res.get("identity_match") in (None, "EXACT")
                                         else ":" + res["identity_match"])
    for row in h1_results:
        key = row.get("match_key")
        try:
            h, a = int(row.get("home_goals")), int(row.get("away_goals"))
        except (TypeError, ValueError):
            continue
        if (row.get("status") or "").lower() != "final" or h < 0 or a < 0:
            continue
        if key in out:
            if (out[key]["home_goals"], out[key]["away_goals"]) != (h, a):
                conflicts.append(key)
            continue
        out[key] = outcome({"home_goals": h, "away_goals": a})
        prov[key] = "H1_RESULTS_CSV"
    for k in conflicts:
        out.pop(k, None)
        prov[k] = "EXCLUDED_SOURCE_CONFLICT"
    return out, prov, conflicts


def build_features(timelines, cache):
    """Incremental: reuse cached features when a match's fingerprint is unchanged."""
    from .pattern_features import fingerprint
    old = (cache or {}).get("matches", {}) if (cache or {}).get("feature_version") == FEATURE_VERSION else {}
    feats, new_cache, reused = [], {}, 0
    for t in timelines:
        fp = fingerprint(t)
        prev = old.get(t["match_key"])
        if prev and prev.get("fingerprint") == fp:
            f = prev
            reused += 1
        else:
            f = match_features(t)
        feats.append(f)
        new_cache[t["match_key"]] = f
    return feats, {"feature_version": FEATURE_VERSION, "matches": new_cache}, {
        "reused": reused, "recomputed": len(timelines) - reused}


def run(timelines, ledger, registry, *, now, previous=None, cache=None, h1_results=(),
        source_commit=None, ft_report=None):
    now = now.astimezone(timezone.utc)
    registry = load_registry(copy.deepcopy(registry))
    old_registry = copy.deepcopy(registry)
    feats_all, new_cache, incr = build_features(timelines, cache)
    excluded = Counter(f["excluded"] for f in feats_all if "excluded" in f)
    feats = [f for f in feats_all if "excluded" not in f]
    by_key = {f["match_key"]: f for f in feats}
    outcomes, provenance, conflicts = outcomes_from(ledger, h1_results)
    outcomes = {k: v for k, v in outcomes.items() if k in by_key}
    past = {k for k, f in by_key.items() if _utc(f["kickoff_utc"]) + RESULT_DELAY <= now}
    future = {k for k, f in by_key.items() if _utc(f["kickoff_utc"]) > now}
    keys = sorted(by_key)

    hyps, gen = generate_hypotheses(feats)
    rows, tests = [], []
    for h in hyps:
        row = {"id": h["id"], "definition": h["definition"], "label": label(h["definition"]),
               "complexity": h["complexity"], "matches": len(h["members"]), "outcomes": {},
               "members": h["members"], "equivalent_definitions": h["equivalent"]}
        for target in TESTED_OUTCOMES:
            st = group_stats(h["members"], keys, outcomes, past, by_key, target)
            if st["known"] >= MIN_TEST_N and st["reference_known"] >= MIN_TEST_N:
                st["p_two_sided"] = r(fisher(st["hits"], st["known"], st["reference_hits"],
                                             st["reference_known"]), 6)
                tests.append((row, target))
            row["outcomes"][target] = st
        kin = [k for k in keys if k in h["members"]]
        kout = [k for k in keys if k not in h["members"]]
        row["total_goals"] = {"in": _goals(kin, outcomes), "reference": _goals(kout, outcomes)}
        rows.append(row)
    qs = bh_qvalues([row["outcomes"][t]["p_two_sided"] for row, t in tests])
    for (row, t), q in zip(tests, qs):
        row["outcomes"][t]["q_bh"] = r(q, 6)

    # ----- frozen hypotheses: out-of-sample evaluation
    frozen_ids = {e["id"] for e in registry["entries"]}
    alpha = 0.05 / max(1, len(registry["entries"]))
    frozen_rows = []
    hyp_by_id = {h["id"]: h for h in hyps}
    for e in registry["entries"]:
        frozen_at = _utc(e["frozen_at"])
        members = {k for k, f in by_key.items() if holds(e["definition"], f)}
        oos_keys = [k for k in keys if _utc(by_key[k]["first_observed_at"]) > frozen_at]
        oos = group_stats(members, oos_keys, outcomes, past, by_key, e["outcome"])
        state, why = oos_state(e, oos, alpha)
        decisions = e.setdefault("decisions", [])
        last = decisions[-1] if decisions else None
        if last and last["state"] == "REJEITADO":
            state, why = "REJEITADO", "terminal"
        elif state == "REJEITADO" and why == "early_reversal":
            decisions.append({"at": now.isoformat(timespec="seconds"), "oos_known": oos["known"],
                              "state": "REJEITADO", "reason": "early_reversal", "oos_diff": oos.get("diff")})
        elif state is None:
            done = {d.get("checkpoint") for d in decisions}
            cp = (oos["known"] // CHECKPOINT) * CHECKPOINT
            if cp not in done:
                st, detail = checkpoint_decision(e, oos, alpha)
                decisions.append({"at": now.isoformat(timespec="seconds"), "checkpoint": cp,
                                  "oos_known": oos["known"], "state": st, **detail,
                                  "oos_rate": oos["rate"], "oos_reference_rate": oos["reference_rate"],
                                  "oos_diff": oos.get("diff")})
            state = decisions[-1]["state"]
        halves = periods(members, oos_keys, outcomes, by_key, e["outcome"])["halves"]
        degrading = (state == "VALIDADO" and halves[1]["diff"] is not None and
                     (1 if e["direction"] == "HIGHER" else -1) * halves[1]["diff"] < 0)
        frozen_rows.append({"id": e["id"], "label": e["label"], "definition": e["definition"],
                            "outcome": e["outcome"], "direction": e["direction"], "frozen_at": e["frozen_at"],
                            "state": state, "discovery": e["discovery"], "out_of_sample": oos,
                            "oos_halves": halves, "degradation_flag": degrading,
                            "decisions": e.get("decisions", [])})

    # ----- discovery classification and freezing of new candidates
    active = sum(1 for f in frozen_rows if f["state"] in ("CANDIDATO", "EM_VALIDACAO", "VALIDADO"))
    candidates = []
    for row in rows:
        row["state"] = "EXPLORATORIO"
        flags = []
        for t in TESTED_OUTCOMES:
            st = row["outcomes"][t]
            if "q_bh" not in st:
                st["evidence"] = "INSUFFICIENT_N"
                continue
            per = periods(row["members"], keys, outcomes, by_key, t)
            st["periods"] = per
            stable = _stable(per)
            st["temporal_stability"] = {True: "SAME_SIGN_BOTH_HALVES", False: "SIGN_CHANGES",
                                        None: "NOT_ENOUGH_PER_HALF"}[stable]
            cov_gap = (abs(st["ft_coverage"] - st["reference_ft_coverage"])
                       if st["ft_coverage"] is not None and st["reference_ft_coverage"] is not None else None)
            st["ft_coverage_gap"] = r(cov_gap)
            meets = (st["known"] >= CAND_MIN_N and st["reference_known"] >= CAND_MIN_N
                     and st["q_bh"] <= CAND_MAX_Q and abs(st["diff"]) >= CAND_MIN_DIFF
                     and cov_gap is not None and cov_gap <= MAX_COVERAGE_GAP and stable is True)
            if meets:
                st["evidence"] = "MEETS_CANDIDATE_CRITERIA"
                candidates.append((st["q_bh"], -abs(st["diff"]), row["id"], t, row, st))
            elif st["known"] >= 30 and st["reference_known"] >= 30 and abs(st["diff"]) < 0.05:
                st["evidence"] = "NULL_CONSISTENT"
            else:
                st["evidence"] = "NOT_SIGNIFICANT_AFTER_FDR" if st["q_bh"] > CAND_MAX_Q else "BELOW_CANDIDATE_CRITERIA"
            flags.append(st["evidence"])
        if row["id"] in frozen_ids:
            row["state"] = next(f["state"] for f in frozen_rows if f["id"] == row["id"])
    candidates.sort(key=lambda x: (x[0], x[1], x[2]))
    newly = []
    for q, _, hid, t, row, st in candidates:
        if active >= MAX_ACTIVE_FROZEN or hid in frozen_ids:
            continue
        members = sorted(row["members"])
        entry = {"id": hid, "definition": row["definition"], "definition_sha256": definition_sha(row["definition"]),
                 "label": row["label"], "outcome": t, "direction": "HIGHER" if st["diff"] > 0 else "LOWER",
                 "feature_version": FEATURE_VERSION, "engine_version": ENGINE_VERSION,
                 "frozen_at": now.isoformat(timespec="seconds"), "source_commit": source_commit,
                 "discovery": {k: st.get(k) for k in ("known", "hits", "rate", "reference_known",
                                                      "reference_rate", "diff", "diff_ci95", "q_bh",
                                                      "p_two_sided", "market_implied_rate")},
                 "discovery_matches": len(members),
                 "discovery_match_keys_sha256": hashlib.sha256("\n".join(members).encode()).hexdigest(),
                 "decisions": []}
        registry["entries"].append(entry)
        frozen_ids.add(hid)
        active += 1
        row["state"] = "CANDIDATO"
        newly.append(hid)
    assert_append_only(old_registry, registry)

    # ----- similar matches
    pool = feats
    targets = sorted(feats, key=lambda f: f["decision_at"], reverse=True)[:30]
    similar = []
    for t in targets:
        nb = neighbours(t, pool, outcomes)
        known = [n for n in nb["neighbours"]]
        similar.append({"match_key": t["match_key"], "match_label": t["match_label"],
                        "kickoff_utc": t["kickoff_utc"], "decision_at": t["decision_at"],
                        "status": ("FT_CONFIRMED" if t["match_key"] in outcomes else
                                   "FUTURE" if t["match_key"] in future else "AWAITING_FT"),
                        "patterns": [p for p in t["patterns"] if not p.startswith("M_TRIGGER")],
                        "lam_decision": t.get("lam_decision"), "net_dlam": t.get("net_dlam"),
                        "neighbour_over_2_5": (sum(n["over_2_5"] for n in known), len(known)),
                        **nb})
    wf = walk_forward(feats, outcomes)

    # ----- baselines and evolution
    known_keys = [k for k in keys if k in outcomes]
    o25 = sum(outcomes[k]["OVER_2_5"] for k in known_keys)
    btts = sum(outcomes[k]["BTTS_YES"] for k in known_keys)
    probs = [(by_key[k]["p_over_2_5_model"], outcomes[k]["OVER_2_5"]) for k in known_keys
             if by_key[k].get("p_over_2_5_model") is not None]
    baselines = {"known": len(known_keys),
                 "over_2_5": {"hits": o25, "rate": r(o25 / len(known_keys)) if known_keys else None,
                              "ci95": [r(x) for x in wilson(o25, len(known_keys))] if known_keys else None},
                 "btts_yes": {"hits": btts, "rate": r(btts / len(known_keys)) if known_keys else None,
                              "ci95": [r(x) for x in wilson(btts, len(known_keys))] if known_keys else None},
                 "total_goals": _goals(known_keys, outcomes),
                 "market_implied_over_2_5": {
                     "matches": len(probs),
                     "mean_model_probability": r(sum(p for p, _ in probs) / len(probs)) if probs else None,
                     "observed_rate_same_matches": r(sum(y for _, y in probs) / len(probs)) if probs else None,
                     "brier_model": r(sum((p - y) ** 2 for p, y in probs) / len(probs)) if probs else None,
                     "z_observed_vs_model": r(implied_z(sum(y for _, y in probs), [p for p, _ in probs]), 3)}}
    days = defaultdict(lambda: Counter())
    for f in feats:
        d = days[f["kickoff_utc"][:10]]
        d["matches"] += 1
        d["prekickoff_messages"] += f["prekickoff_messages"]
        if f["match_key"] in outcomes:
            d["known"] += 1
            d["over_2_5"] += outcomes[f["match_key"]]["OVER_2_5"]
            d["btts_yes"] += outcomes[f["match_key"]]["BTTS_YES"]
    evolution = [{"kickoff_day": k, **dict(v),
                  "over_2_5_rate": r(v["over_2_5"] / v["known"]) if v["known"] else None,
                  "btts_rate": r(v["btts_yes"] / v["known"]) if v["known"] else None}
                 for k, v in sorted(days.items())]

    # ----- individual patterns table and combination ranking
    singles = [x for x in rows if x["definition"]["op"] == "HAS"]
    combos = [x for x in rows if x["definition"]["op"] != "HAS"]

    def strength(x):
        qs_ = [x["outcomes"][t].get("q_bh") for t in TESTED_OUTCOMES if x["outcomes"][t].get("q_bh") is not None]
        return (min(qs_) if qs_ else 2.0, -max(abs(x["outcomes"][t].get("diff") or 0) for t in TESTED_OUTCOMES), x["id"])
    combos_ranked, sig_seen, same_sample = [], {}, Counter()
    for x in sorted(combos, key=strength):
        # Distinct definitions can select the same confirmed-FT matches today;
        # show the strongest once and count the others (they are still tested).
        sig = frozenset(k for k in x["members"] if k in outcomes)
        if sig in sig_seen:
            same_sample[sig_seen[sig]] += 1
            continue
        sig_seen[sig] = x["id"]
        combos_ranked.append(x)
    for x in combos_ranked:
        x["other_definitions_same_known_sample"] = same_sample[x["id"]]
    for x in combos_ranked[:40]:
        d = x["definition"]
        parents = (list(d.get("all", [])) + list(d.get("none", [])) if d["op"] in ("AND", "AND_NOT")
                   else [d["first"], d["then"]])
        x["parents"] = {}
        for p in parents:
            pr = next((s for s in singles if s["definition"].get("a") == p), None)
            if pr:
                x["parents"][p] = {t: {"known": pr["outcomes"][t]["known"], "rate": pr["outcomes"][t]["rate"]}
                                   for t in TESTED_OUTCOMES}
        x["example_matches"] = [{"match_label": by_key[k]["match_label"],
                                 "kickoff_day": by_key[k]["kickoff_utc"][:10],
                                 "score": ("%d-%d" % (outcomes[k]["home_goals"], outcomes[k]["away_goals"])
                                           if k in outcomes else None)}
                                for k in sorted(sorted(x["members"], key=lambda k: (by_key[k]["kickoff_utc"], k),
                                                       reverse=True), key=lambda k: k not in outcomes)[:5]]

    COMPACT = ("matches", "known", "unknown_past", "future_or_grace", "hits", "misses", "rate", "ci95",
               "reference_known", "reference_rate", "diff", "diff_ci95", "p_two_sided", "q_bh", "evidence",
               "market_implied_rate", "vs_market_implied", "ft_coverage", "reference_ft_coverage",
               "ft_coverage_gap", "temporal_stability")

    def slim(x, keep_periods=False):
        y = {k: v for k, v in x.items() if k not in ("members",)}
        if not keep_periods:
            y["outcomes"] = {t: {k: v for k, v in s.items() if k in COMPACT} for t, s in x["outcomes"].items()}
            y.pop("total_goals", None)
        return y

    # ----- changes vs previous run
    prev_states = (previous or {}).get("hypothesis_states", {})
    states_all = {x["id"]: x["state"] for x in rows}
    states_all.update({f["id"]: f["state"] for f in frozen_rows})
    # Only non-default states are stored; absence means EXPLORATORIO.
    states_now = {k: v for k, v in sorted(states_all.items()) if v != "EXPLORATORIO"}
    transitions = [{"id": k, "from": prev_states.get(k, "EXPLORATORIO"), "to": states_now.get(k, "EXPLORATORIO")}
                   for k in sorted(set(prev_states) | set(states_now))
                   if prev_states.get(k, "EXPLORATORIO") != states_now.get(k, "EXPLORATORIO")]
    since = _utc((previous or {}).get("generated_at"))
    ledger_rows = ledger.get("matches") or {}
    new_ft = [k for k in known_keys if provenance.get(k, "").startswith("LAB_LEDGER") and
              (since is None or (_utc(ledger_rows.get(k, {}).get("checked_at")) or now) > since)]
    new_results = []
    for k in sorted(new_ft, key=lambda k: by_key[k]["kickoff_utc"])[-50:]:
        f = by_key[k]
        new_results.append({"match_key": k, "match_label": f["match_label"], "kickoff_utc": f["kickoff_utc"],
                            "score": "%d-%d" % (outcomes[k]["home_goals"], outcomes[k]["away_goals"]),
                            "patterns": [p for p in f["patterns"] if not p.startswith("M_TRIGGER")],
                            "counts_out_of_sample_for": [e["id"] for e in registry["entries"]
                                                         if holds(e["definition"], f)
                                                         and _utc(f["first_observed_at"]) > _utc(e["frozen_at"])]})

    tested = len(tests)
    report = {
        "schema_version": 1, "status": STATUS, "generated_at": now.isoformat(timespec="seconds"),
        "source_commit": source_commit,
        "versions": {"engine": ENGINE_VERSION, "features": FEATURE_VERSION, "market_math": MATH_VERSION,
                     "similarity": SIMILARITY_VERSION},
        "scope": {
            "matches_observed": len(feats_all), "research_eligible": len(feats),
            "excluded": dict(excluded), "ft_confirmed": len(known_keys),
            "past_without_ft": len(past - set(outcomes)), "future": len(future),
            "in_result_grace": len(feats) - len(past) - len(future),
            "outcome_provenance": dict(Counter(provenance[k] for k in known_keys)),
            "outcome_source_conflicts_excluded": len(conflicts),
            "unit": "match (match_key); messages are never independent trials",
            "decision_time": "last message strictly before kickoff; nothing later is a feature",
        },
        "incremental": incr,
        "ft_coverage": _coverage(ft_report, feats, outcomes, past, future),
        "baselines": baselines,
        "rules": {"min_support": MIN_SUPPORT, "min_test_n": MIN_TEST_N, "candidate_min_n": CAND_MIN_N,
                  "candidate_max_q_bh": CAND_MAX_Q, "candidate_min_abs_diff": CAND_MIN_DIFF,
                  "max_ft_coverage_gap": MAX_COVERAGE_GAP, "oos_min_eval": OOS_MIN_EVAL,
                  "checkpoint_every": CHECKPOINT, "early_reject": [EARLY_REJECT_N, EARLY_REJECT_DIFF],
                  "max_active_frozen": MAX_ACTIVE_FROZEN, "bonferroni_alpha_now": r(alpha, 6),
                  "tested_outcomes": list(TESTED_OUTCOMES), "complements_reported_not_retested": COMPLEMENT},
        "generation": dict(gen, tests_performed=tested,
                           hypotheses_evaluated=len(rows), combinations_evaluated=len(combos)),
        "state_counts": dict(Counter(states_all.values())),
        "patterns": [slim(x, keep_periods=True) for x in sorted(singles, key=strength)],
        "combinations_top": [slim(x) for x in combos_ranked[:40]],
        "frozen": frozen_rows,
        "negative_evidence": [{"id": x["id"], "label": x["label"], "outcome": t,
                               "known": x["outcomes"][t]["known"], "diff": x["outcomes"][t].get("diff"),
                               "q_bh": x["outcomes"][t].get("q_bh")}
                              for x in rows for t in TESTED_OUTCOMES
                              if x["outcomes"][t].get("evidence") == "NULL_CONSISTENT"][:40],
        "similar_matches": similar,
        "similarity_walk_forward": wf,
        "evolution": evolution,
        "changes": {"new_frozen_candidates": newly, "state_transitions": transitions[:100],
                    "new_ft_results": new_results},
        "hypothesis_states": states_now,
        "pattern_catalogue": {k: {"scope": v[0], "family": v[1], "description": v[2]} for k, v in PATTERNS.items()},
        "limitations": [
            "Universe = matches announced by the AsianOdds channel; conclusions are conditional on being alerted.",
            "Model-implied Over 2.5 comes from a Poisson inversion of the observed Asian Total line; it is a reference, not an Over 2.5 price. No ROI or EV is computed.",
            "Sporting outcome (goals) is evaluated, not the settlement of any Asian bet.",
            "Exploratory rates use all confirmed results so far; only frozen hypotheses get an out-of-sample verdict.",
            "FT coverage is incomplete; groups with different coverage are flagged and cannot become candidates.",
            "Between two alerts the price path is unobserved; nothing is interpolated.",
        ],
    }
    return report, registry, new_cache


def _coverage(ft_report, feats, outcomes, past, future):
    out = {"research_eligible": len(feats), "ft_confirmed": len(set(outcomes) & {f["match_key"] for f in feats}),
           "past_without_ft": len(past - set(outcomes)), "future": len(future)}
    if isinstance(ft_report, dict):
        out["ledger_status_counts"] = ft_report.get("status_counts")
        out["ledger_timing_counts"] = ft_report.get("timing_counts")
        out["ledger_last_updated_at"] = ft_report.get("last_updated_at")
        reasons = Counter()
        for g in ft_report.get("games", []):
            if g.get("status") != "FINAL" and g.get("reason"):
                reasons[g["status"] + ":" + g["reason"]] += 1
        out["unresolved_reasons"] = dict(reasons)
    eligible = len(past)
    out["coverage_of_past_matches"] = r(len(set(outcomes) & past) / eligible) if eligible else None
    return out
