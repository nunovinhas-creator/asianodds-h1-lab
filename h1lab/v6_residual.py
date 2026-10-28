"""V6 independent, *exploratory* market-relative audit of ALL V5 hypotheses.

No p-values, freeze/promotion, bets or retroactive forecasts from this module.
Every result refers to one confirmed FT match, and a quality-vetted observed
pre-kickoff Total snapshot. OOS is evaluated separately using frozen V6 records.
"""
from __future__ import annotations

import csv
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .pattern_engine import build_features, generate_hypotheses, outcomes_from
from .timeline import collect_timelines, read_sources
from .v6_shadow import quality, utc

SCHEMA = 1
MIN_TEMPORAL_WEEKS = 3


def latest_total(timeline):
    """Last *actually observed* pre-kickoff Total. Never invent intervening odds."""
    kos = (timeline.get("identity") or {}).get("kickoff_utc") or []
    if len(kos) != 1:
        return None
    kickoff = utc(kos[0])
    if not kickoff:
        return None
    events = sorted((e for e in timeline.get("events", [])
                     if utc(e.get("observed_at")) is not None
                     and utc(e["observed_at"]) < kickoff
                     and (e.get("snapshots") or {}).get("total") is not None),
                    key=lambda e: (e["observed_at"], e["event_id"]))
    if not events:
        return None
    e = events[-1]
    q = quality(e["snapshots"]["total"])
    return {"event_id": e["event_id"], "observed_at": e["observed_at"],
            "quality_status": q["status"], "quality_flags": q["flags"],
            "p_over_2_5": q.get("p_over_2_5"),
            "total_line": (q.get("after") or {}).get("line")}


def residual_summary(keys, baselines, outcomes):
    """Day-cluster bootstrap CI only if three distinct kickoff days exist.

    This is DESCRIPTIVE uncertainty, not a confirmatory p-value. Daily clusters
    are used because many FT share one day. No success decision is made here.
    """
    values = [(k, float(outcomes[k]["OVER_2_5"]) - baselines[k]["p_over_2_5"])
              for k in keys if k in outcomes and k in baselines
              and baselines[k]["p_over_2_5"] is not None]
    n = len(values)
    if not n:
        return {"n": 0, "hits": 0, "observed_rate": None, "market_rate": None,
                "residual": None, "residual_ci95_day_bootstrap": None,
                "distinct_days": 0, "distinct_weeks": 0, "state": "INSUFFICIENT_N"}
    selected = [k for k, _ in values]
    successes = sum(int(outcomes[k]["OVER_2_5"]) for k in selected)
    ps = sum(baselines[k]["p_over_2_5"] for k in selected)
    residuals = [v for _, v in values]
    grouped = defaultdict(list)
    for k, delta in values:
        day = baselines[k]["kickoff_utc"][:10]
        grouped[day].append(delta)
    days = sorted(grouped)
    weeks = {datetime.fromisoformat(d).isocalendar()[:2] for d in days}
    ci = None
    if len(days) >= 3:
        rng = random.Random(960)
        bs = []
        for _ in range(240):
            draw = [d for _ in days for d in [days[rng.randrange(len(days))]]]
            vals = [v for day in draw for v in grouped[day]]
            bs.append(sum(vals) / len(vals))
        bs.sort()
        ci = [round(bs[5], 4), round(bs[234], 4)]
    return {
        "n": n, "hits": successes, "observed_rate": round(successes / n, 4),
        "market_rate": round(ps / n, 4),
        "residual": round(sum(residuals) / n, 4),
        "residual_ci95_day_bootstrap": ci,
        "distinct_days": len(days), "distinct_weeks": len(weeks),
        "state": "EXPLORATORY_NOT_CONFIRMATORY" if len(weeks) >= MIN_TEMPORAL_WEEKS
                 else "INSUFFICIENT_TEMPORAL_DIVERSITY",
    }


def evaluate(timelines, ledger, h1_rows=()):
    feats, _, incr = build_features(timelines, cache=None)
    eligible = [f for f in feats if not f.get("excluded")]
    by_key = {f["match_key"]: f for f in eligible}
    outcomes, _, conflicts = outcomes_from(ledger, h1_rows)
    baseline = {}
    counts = Counter()
    for t in timelines:
        k = t.get("match_key")
        if k not in by_key:
            continue
        row = latest_total(t)
        counts["eligible_matches"] += 1
        if row is None:
            counts["missing_total"] += 1
            continue
        counts["total_observed"] += 1
        if row["p_over_2_5"] is None:
            counts["price_quarantined"] += 1
            counts.update("flag_" + x for x in row["quality_flags"])
            continue
        # A Total captured from a historical Telegram timestamp does NOT
        # establish when the collector learned it; this is in-sample only.
        baseline[k] = dict(row, kickoff_utc=by_key[k]["kickoff_utc"])
        counts["price_usable"] += 1
    universe = sorted(by_key)
    hyps, generated = generate_hypotheses(eligible)
    all_ft = {k for k in universe if k in outcomes}
    rows = []
    for h in hyps:
        members = set(h["members"])
        group = residual_summary(members, baseline, outcomes)
        complement = residual_summary(all_ft - members, baseline, outcomes)
        rows.append({"id": h["id"], "definition": h["definition"],
                     "members_total": len(members),
                     "over_2_5_vs_market": group,
                     "other_matches_vs_market": complement,
                     "btts_yes_vs_market": {"state": "MODEL_REFERENCE_NOT_AVAILABLE",
                                           "reason": "Asian Total does not directly determine BTTS probability"}})
    rows.sort(key=lambda x: (-x["over_2_5_vs_market"]["n"], x["id"]))
    ft_with_qa = sorted(k for k in all_ft if k in baseline)
    return {
        "schema_version": SCHEMA,
        "status": "V6_EXPLORATORY_MARKET_RELATIVE_NO_BETS",
        "scope": {"eligible_matches": len(universe), "ft_confirmed": len(all_ft),
                  "ft_with_usable_price": len(ft_with_qa),
                  "source_conflicts": len(conflicts), "snapshot_diagnostics": dict(counts),
                  "time_semantics": "Historical observed_at only; NOT prospective known_at"},
        "method": {
            "primary_response": "y(Over2.5) - quality_vetted_market_model_p(Over2.5)",
            "market_reference": "Asian Total inverse Poisson (not traded O2.5 odds)",
            "confidence_interval": "240-replicate day-block descriptive bootstrap; omitted if fewer than 3 days",
            "freeze_or_validate": False,
            "three_distinct_weeks_required_for_temporal_stability": True,
            "all_hypotheses": True, "btts_market_baseline": "NOT_AVAILABLE",
            "selection_bias": "Telegram alert-selected sample only",
        },
        "generation": {**generated, "hypotheses_evaluated": len(rows)},
        "all_hypotheses": rows,
        "baseline_all_confirmed": residual_summary(all_ft, baseline, outcomes),
        "limitations": [
            "In-sample historical analysis, NEVER independent prospective validation.",
            "Market model assumptions and high concentration of FT by day.",
            "Residuals should replace hit-rate-versus-complement as the V6 question.",
            "Legacy V5 rankings remain untouched for backwards compatibility.",
        ],
    }


def run(root):
    root = Path(root)
    alerts, v4, errors = read_sources(root)
    timelines, _, _ = collect_timelines(alerts, v4, source_errors=errors)
    path = root / "data/lab/ft-ledger.json"
    ledger = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"matches": {}}
    csv_file = root / "data/results.csv"
    if csv_file.exists():
        with csv_file.open(encoding="utf-8") as stream:
            h1_rows = list(csv.DictReader(stream))
    else:
        h1_rows = []
    return evaluate(timelines, ledger, h1_rows)
