"""Interpretable "similar historical matches" search for the LAB (no ML).

Question answered: *which earlier matches showed odds behaviour like this one?*

* Features are decision-time only (``pattern_features.match_features``'s
  ``vector``). The final score is never a feature.
* A neighbour is eligible only if its kickoff + 3 h is not after the target's
  decision time, i.e. its result could have been known when the target's last
  pre-kickoff alert arrived. No future information leaks into the comparison.
* Distance is a weighted Gower-style mean of capped, *fixed-scale* absolute
  differences. Scales are constants chosen a priori (not fitted to data), so
  the same pair always gets the same similarity and every contribution can be
  shown. Missing on either side counts as maximal difference for that feature.
* Pattern overlap (Jaccard over movement patterns) is a separate, reported
  component.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

SIMILARITY_VERSION = 1
RESULT_DELAY = timedelta(hours=3)
# feature -> (scale, weight)
FEATURES = {
    "net_dlam": (0.30, 3.0),
    "max_msg_dlam": (0.30, 2.0),
    "last_line": (0.75, 2.0),
    "lam_decision": (0.60, 2.0),
    "n_episodes": (2.0, 1.0),
    "log_lead_first": (1.5, 1.0),
    "log_lead_last": (1.5, 1.0),
    "has_1x2": (1.0, 0.5),
    "ah_dir": (2.0, 0.5),
    "opposing": (1.0, 1.0),
    "late": (1.0, 0.5),
}
PATTERN_WEIGHT = 2.0
MOVEMENT_PREFIXES = ("M_TOTAL", "M_OVER", "M_UNDER", "M_BOTH", "M_IMPLIED", "M_LINE", "M_1X2",
                     "M_AH", "G_REPEAT", "G_OPPOSING", "G_INTENSIFYING", "G_WEAKENING",
                     "G_NET", "G_UNOBSERVED")


def _utc(v):
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return d.astimezone(timezone.utc) if d.tzinfo else None


def _movement(f):
    return {p for p in f.get("patterns", ()) if p.startswith(MOVEMENT_PREFIXES)}


def compare(a, b):
    """(similarity 0..1, per-feature contributions) between two feature dicts."""
    va, vb = a.get("vector") or {}, b.get("vector") or {}
    total_w, dist, parts = 0.0, 0.0, {}
    for name, (scale, w) in FEATURES.items():
        x, y = va.get(name), vb.get(name)
        d = 1.0 if x is None or y is None else min(abs(x - y) / scale, 1.0)
        dist += w * d
        total_w += w
        parts[name] = round(1 - d, 2)
    pa, pb = _movement(a), _movement(b)
    jac = len(pa & pb) / len(pa | pb) if (pa | pb) else 1.0
    dist += PATTERN_WEIGHT * (1 - jac)
    total_w += PATTERN_WEIGHT
    parts["shared_patterns"] = round(jac, 2)
    return round(1 - dist / total_w, 4), parts


def eligible(target, candidate):
    if candidate["match_key"] == target["match_key"]:
        return False
    dec = _utc(target.get("decision_at"))
    ko = _utc(candidate.get("kickoff_utc"))
    return dec is not None and ko is not None and ko + RESULT_DELAY <= dec


def neighbours(target, pool, outcomes, *, k=5, min_similarity=0.55):
    """Most similar eligible earlier matches; those with a confirmed FT first."""
    scored = []
    for c in pool:
        if not eligible(target, c):
            continue
        s, parts = compare(target, c)
        if s >= min_similarity:
            scored.append((s, c, parts))
    scored.sort(key=lambda x: (-x[0], x[1]["match_key"]))
    known = [x for x in scored if x[1]["match_key"] in outcomes]
    out = []
    for s, c, parts in known[:k]:
        o = outcomes[c["match_key"]]
        out.append({"match_key": c["match_key"], "match_label": c.get("match_label"),
                    "kickoff_utc": c.get("kickoff_utc"), "similarity": s,
                    "score": "%d-%d" % (o["home_goals"], o["away_goals"]),
                    "total_goals": o["total_goals"], "over_2_5": o["OVER_2_5"],
                    "btts": o["BTTS_YES"], "shared_patterns": sorted(_movement(target) & _movement(c)),
                    "contributions": parts})
    return {"eligible_earlier_matches": sum(1 for c in pool if eligible(target, c)),
            "similar_above_threshold": len(scored), "with_confirmed_ft": len(known),
            "neighbours": out}


def walk_forward(features, outcomes, *, k=10, min_similarity=0.55, min_neighbours=5):
    """Leak-free check: does a kNN Over-2.5 estimate beat simple references?

    For every match with a confirmed FT, using only matches whose result was
    knowable at its decision time: kNN estimate (Laplace), the running base
    rate (Laplace) and the model-implied P(O2.5) from the observed Total
    quote. Brier scores are reported on the same subset. Exploratory only.
    """
    rows = []
    for t in features:
        key = t["match_key"]
        if key not in outcomes or t.get("p_over_2_5_model") is None:
            continue
        prior = [c for c in features if c["match_key"] in outcomes and eligible(t, c)]
        if not prior:
            continue
        scored = sorted(((compare(t, c)[0], c) for c in prior), key=lambda x: (-x[0], x[1]["match_key"]))
        near = [c for s, c in scored if s >= min_similarity][:k]
        if len(near) < min_neighbours:
            continue
        y = 1.0 if outcomes[key]["OVER_2_5"] else 0.0
        hits = sum(outcomes[c["match_key"]]["OVER_2_5"] for c in near)
        base_hits = sum(outcomes[c["match_key"]]["OVER_2_5"] for c in prior)
        p_knn = (hits + 1) / (len(near) + 2)
        p_base = (base_hits + 1) / (len(prior) + 2)
        rows.append((y, p_knn, p_base, t["p_over_2_5_model"]))
    n = len(rows)

    def brier(i):
        return None if not n else round(sum((r[i] - r[0]) ** 2 for r in rows) / n, 4)
    return {"matches_evaluated": n, "brier_knn": brier(1), "brier_running_base_rate": brier(2),
            "brier_market_implied_model": brier(3),
            "status": "INSUFFICIENT_SAMPLE" if n < 50 else "EXPLORATORY",
            "note": "Lower Brier is better. Same matches for all three. Not a betting test."}
