"""MASTER BRAIN V6 shadow journal: quality, genuinely prospective baselines, evidence.

Independent of H1 settlement, V5 discoveries, Telegram alerts and picks.
Only the timestamp at which this process FIRST saw a still-future fixture is
a prospective 'known_at'. Historic Telegram timestamps never backdate a forecast.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .market_math import implied_lambda, margin, prob_total_over, valid_line, valid_price
from .pattern_engine import outcomes_from
from .pattern_watch import inspect
from .timeline import collect_timelines, read_sources

SCHEMA = 1
STATUS = "V6_SHADOW_PROSPECTIVE_NOT_VALIDATED_NOT_BETTING"
JOURNAL_GLOB = "v6-forecasts-????-??.jsonl"
HYPOTHESIS = "V6-POSTHOC-20261028-NO-DOWN"
MIN_OOS_FT = 1000
ALPHA = 0.005
MIN_EDGE = 0.05
QUALITY_POLICY = "V6-Q2-MARGIN12-20261028"
MAX_OVERROUND = 0.12
ALT_EDGES = (0.05, 0.10, 0.20)  # fixed BEFORE observing OOS outcomes
ZERO_HASH = "0" * 64


def utc(s):
    if not isinstance(s, str):
        return None
    try:
        v = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return v.astimezone(timezone.utc) if v.tzinfo else None
    except ValueError:
        return None


def stamp(now):
    if now.tzinfo is None:
        raise ValueError("UTC-aware processing time required")
    return now.astimezone(timezone.utc).isoformat(timespec="seconds")


def canonical(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def quality(total):
    """Assess both sides of a Total row without changing the source snapshot.

    Cross-line repeated prices and negative margin are suspicious, NOT proof
    of corruption. Only clean after quotes become model baselines. Threshold
    12% for overround is explicitly a quality heuristic, not a bookmaker fact.
    """
    if not isinstance(total, dict):
        return {"status": "NO_TOTAL", "flags": ["no_total"], "before": None,
                "after": None, "p_over_2_5": None}
    before, after = total.get("before") or {}, total.get("after") or {}
    flags = []
    sides = {}
    for name, side in (("before", before), ("after", after)):
        line, o, u = side.get("line"), side.get("over_price"), side.get("under_price")
        valid = valid_line(line) and valid_price(o) and valid_price(u)
        m = margin(o, u) if valid else None
        if not valid:
            flags.append("invalid_" + name + "_quote")
        elif m < 0:
            flags.append("negative_" + name + "_margin")
        elif m > MAX_OVERROUND:
            flags.append("high_" + name + "_margin")
        sides[name] = {"line": line, "over_price": o, "under_price": u,
                       "margin": round(m, 5) if m is not None else None}
    b, a = sides["before"], sides["after"]
    if (valid_line(b["line"]) and valid_line(a["line"]) and b["line"] != a["line"]
            and ((b["over_price"] == a["over_price"]) or
                 (b["under_price"] == a["under_price"]))):
        flags.append("cross_line_unchanged_price")
    # A suspect BEFORE row should not invalidate a clean AFTER baseline except
    # a cross-line mismatch, which makes the quoted movement unreliable.
    bad_after = any(f in flags for f in ("invalid_after_quote", "negative_after_margin",
                                         "high_after_margin", "cross_line_unchanged_price"))
    lam = (implied_lambda(a["line"], a["over_price"], a["under_price"])
           if not bad_after else None)
    p = prob_total_over(lam)
    if not bad_after and p is None:
        flags.append("lambda_unavailable")
    return {"status": "USABLE" if p is not None else "UNUSABLE",
            "flags": flags, **sides, "lambda_after": lam, "p_over_2_5": p}


def _payload_hash(record):
    body = {k: v for k, v in record.items() if k != "sha256"}
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def read_journal(root):
    """Fail closed on modified/reordered JSONL; Git commits anchor tail history."""
    records, previous = [], ZERO_HASH
    for path in sorted((Path(root) / "data/lab").glob(JOURNAL_GLOB)):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                raise ValueError("blank line in V6 journal " + str(path))
            record = json.loads(line)
            if (record.get("schema_version") != SCHEMA or
                    record.get("previous_sha256") != previous or
                    record.get("sha256") != _payload_hash(record)):
                raise ValueError("V6 journal chain broken " + str(path))
            previous = record["sha256"]
            records.append(record)
    ids = [(r["match_key"], r["event_id"]) for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError("V6 journal duplicate match/event")
    return records


def append_journal(root, now, additions):
    """Only append to the current UTC month, never rewrite historical records."""
    root = Path(root)
    existing = read_journal(root)
    seen = {(r["match_key"], r["event_id"]) for r in existing}
    previous = existing[-1]["sha256"] if existing else ZERO_HASH
    filename = "v6-forecasts-" + now.astimezone(timezone.utc).strftime("%Y-%m") + ".jsonl"
    path = root / "data/lab" / filename
    count = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in additions:
            key = row["match_key"], row["event_id"]
            if key in seen:
                continue
            row = dict(row, schema_version=SCHEMA, previous_sha256=previous)
            row["sha256"] = _payload_hash(row)
            handle.write(canonical(row) + "\n")
            previous = row["sha256"]
            seen.add(key)
            count += 1
    # Check both the previous chain and the newly appended content.
    read_journal(root)
    return count


def _competition_type(value):
    """A heuristic label, never a proven division classification."""
    import re
    value = (value or "").lower()
    if any(x in value for x in ("u17", "u18", "u19", "u20", "u21", "youth",
                                 "juvenil", "reserve", "reserves", "sub-19", "sub-21")):
        return "YOUTH_RESERVE"
    if any(x in value for x in ("cup", "taça", "copa", "pokal", "coupe")):
        return "CUP"
    return "LEAGUE_OTHER" if value.strip() else "UNKNOWN"


def _falsification_context(timeline, events, watch, competition):
    """Future-proof frozen context; never reconstruct these fields for past predictions."""
    from .market_math import one_x_two_probs
    categories = {k: 0 for k in ("total", "one_x_two", "asian_handicap")}
    market_agreement = []
    for e in events:
        snap = e.get("snapshots") or {}
        for kind in categories:
            if kind in snap:
                categories[kind] += 1
        ah, one = snap.get("asian_handicap"), snap.get("one_x_two")
        if ah and one:
            before = one_x_two_probs({sel: one[sel]["before"] for sel in ("1", "X", "2")})
            after = one_x_two_probs({sel: one[sel]["after"] for sel in ("1", "X", "2")})
            ab = (ah.get("before") or {}).get("line")
            aa = (ah.get("after") or {}).get("line")
            if before and after and isinstance(ab, (int, float)) and isinstance(aa, (int, float)):
                home = after["1"] - before["1"]
                towards_home = ab - aa
                if abs(home) >= 0.01 and abs(towards_home) >= 0.25:
                    market_agreement.append((home > 0) == (towards_home > 0))
    return {
        "schema": "V6-FALSIFICATION-CONTEXT-1",
        "source_event_ids": [e["event_id"] for e in events],
        "watch_category": (watch or {}).get("category"),
        "episode_directions": (watch or {}).get("episode_directions"),
        "episodes": (watch or {}).get("episodes"),
        "first_lead_minutes": events[0].get("minutes_to_kickoff"),
        "last_lead_minutes": events[-1].get("minutes_to_kickoff"),
        "market_message_counts": categories,
        "cross_market_agreements": market_agreement,
        "competition_at_capture": competition,
        "competition_group_heuristic": _competition_type(competition),
        "observation_limit": "Telegram observed_at <= actual collector known_at; individual delivery times unknown",
    }


def captures(timelines, now, competitions=None):
    """Latest message per still-future game, never a reconstructed FT feature."""
    out = []
    for timeline in timelines:
        ident = timeline.get("identity") or {}
        kos = ident.get("kickoff_utc") or []
        if (len(kos) != 1 or not ident.get("kickoff_consistent", False) or
                not ident.get("team_names_consistent", False) or
                ident.get("per_message_conflicts")):
            continue
        kickoff = utc(kos[0])
        if not kickoff or not now < kickoff:
            continue
        events = sorted((e for e in timeline.get("events", [])
                         if utc(e.get("observed_at")) is not None
                         and utc(e["observed_at"]) <= now
                         and utc(e["observed_at"]) < kickoff
                         and isinstance(e.get("minutes_to_kickoff"), (int, float))
                         and not isinstance(e["minutes_to_kickoff"], bool)
                         and e["minutes_to_kickoff"] > 0),
                        key=lambda e: (e["observed_at"], e["event_id"]))
        if not events:
            continue
        last = events[-1]
        q = quality((last.get("snapshots") or {}).get("total"))
        # Reconstruct episode components only from events present at capture.
        # A future message must never join two earlier episodes transitively.
        from .timeline import episodes as isolated_episodes
        allowed = {e["event_id"] for e in events}
        past_relations = [r for r in timeline.get("related_messages", [])
                          if set(r.get("events") or ()) <= allowed]
        past_timeline = dict(timeline, events=events,
                             movement_episodes=isolated_episodes(events, past_relations))
        watch = inspect(past_timeline, now)
        competition = (competitions or {}).get(timeline["match_key"])
        from .v6_features_v2 import build as freeze_v2
        feature_context = freeze_v2(past_timeline, events, known_at=stamp(now),
                                    competition=competition)
        out.append({
            "match_key": timeline["match_key"], "match_label": timeline.get("match_label"),
            "kickoff_utc": kos[0], "event_id": last["event_id"],
            "observed_at": last["observed_at"], "known_at": stamp(now),
            "message_count_at_capture": len(events),
            "total_origin": ((last.get("snapshots") or {}).get("total") or {}).get("origin"),
            "price_quality": q, "quality_policy_version": QUALITY_POLICY,
            "falsification_context": _falsification_context(past_timeline, events, watch, competition),
            "feature_context_v2": feature_context,
            "market_probability_over_2_5": q["p_over_2_5"],
            "pattern_original_posthoc": bool(watch and watch["original_condition"]),
            "pattern_strict_posthoc": bool(watch and watch["strict_condition"]),
            "hypothesis_id": HYPOTHESIS,
            "forecast_kind": "MARKET_BASELINE_ONLY",
            "model_delta_vs_market": 0.0,  # no ML/model claimed
        })
    return sorted(out, key=lambda x: (x["kickoff_utc"], x["match_key"]))


def _retrospective_quality(root):
    """Diagnostic only: prior messages are not treated as future forecasts."""
    counts, n, sample = Counter(), 0, 0
    for path in sorted((Path(root) / "data/lab").glob("markets-????-??.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            t = (row.get("markets") or {}).get("total")
            if t:
                n += 1
                q = quality(t)
                counts.update(q["flags"])
                if q["status"] == "USABLE":
                    sample += 1
    return {"total_snapshots": n, "clean_after_quotes": sample,
            "quality_flags": dict(counts),
            "historical_only_not_forecasts": True}


def snapshot_quality_rows(root):
    """QA evidence by source event: *retrospective diagnostics*, never forecasts."""
    rows = []
    for path in sorted((Path(root) / "data/lab").glob("markets-????-??.jsonl")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            item = json.loads(raw)
            total = (item.get("markets") or {}).get("total")
            if total is not None:
                rows.append({
                    "event_id": item["event_id"], "observed_at": item["observed_at"],
                    "match_key": item.get("match_key"), "kickoff_utc": item.get("kickoff_utc"),
                    "quality": quality(total),
                })
    return {"schema_version": SCHEMA, "scope": "HISTORICAL_PRICE_QA_NOT_FORECASTS",
            "snapshots": sorted(rows, key=lambda x: (x["observed_at"], x["event_id"]))}


def _ft(root):
    ledger_path = Path(root) / "data/lab/ft-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    csv_path = Path(root) / "data/results.csv"
    if csv_path.exists():
        with csv_path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    else:
        rows = []
    return outcomes_from(ledger, rows)[0]


def sequential(selected):
    """Predeclared e-process vs *calibrated* market Bernoulli null.

    Each fixed alternative p+delta is a nonnegative test martingale under
    H0: P(Y=1 | information at capture) = p. Their average is also one.
    Threshold 1/ALPHA is valid under optional monitoring for ONE prespecified
    hypothesis; no retrospective tests are ever fed into this process.
    """
    log_e = [0.0 for _ in ALT_EDGES]
    for row in selected:
        p, y = row["market_probability_over_2_5"], row["outcome"]
        if not 0 < p < 1 or y not in (0, 1):
            raise ValueError("Invalid prospective score")
        for i, delta in enumerate(ALT_EDGES):
            q = min(0.999, p + delta)
            log_e[i] += math.log(q / p) if y else math.log((1-q) / (1-p))
    peak = max(log_e) if log_e else 0.0
    e_value = sum(math.exp(x - peak) for x in log_e) / len(log_e) * math.exp(min(peak, 700))
    return round(e_value, 6)


def report(root, records, now):
    # The latest actually frozen message per match determines its baseline.
    # Never cherry-pick a previous clean quote after seeing a newer bad one.
    latest = {}
    for row in records:
        if utc(row["known_at"]) >= utc(row["kickoff_utc"]):
            raise ValueError("Retrospective record marked as prospective")
        latest[row["match_key"]] = row
    outcomes = _ft(root)
    scored = []
    excluded = Counter()
    for row in latest.values():
        outcome = outcomes.get(row["match_key"])
        if outcome is None:
            continue
        p = row.get("market_probability_over_2_5")
        if not isinstance(p, (int, float)) or not 0 < p < 1:
            excluded.update(["invalid_or_missing_baseline"])
            continue
        scored.append({**row, "outcome": int(outcome["OVER_2_5"])})
    selected = sorted((r for r in scored if r["pattern_original_posthoc"]),
                      key=lambda r: (r["kickoff_utc"], r["match_key"]))
    other = [r for r in scored if not r["pattern_original_posthoc"]]

    def metrics(rows):
        if not rows:
            return {"n": 0, "observed_rate": None, "market_rate": None,
                    "residual": None, "brier": None}
        n = len(rows)
        y = [r["outcome"] for r in rows]
        p = [r["market_probability_over_2_5"] for r in rows]
        return {"n": n, "observed_rate": round(sum(y)/n, 4),
                "market_rate": round(sum(p)/n, 4),
                "residual": round(sum(a-b for a, b in zip(y, p))/n, 4),
                "brier": round(sum((a-b)**2 for a, b in zip(y, p))/n, 5)}

    sel = metrics(selected)
    e = sequential(selected)
    # Strong evidence and sufficient sample size BOTH required. Historical
    # n=11, hits=10 are NOT eligible for this prospective verdict.
    verdict = ("VALIDADO" if sel["n"] >= MIN_OOS_FT and e >= 1/ALPHA
               and sel["residual"] >= MIN_EDGE else "INCONCLUSIVO")
    return {
        "schema_version": SCHEMA, "status": STATUS, "generated_at": stamp(now),
        "hypothesis": {"id": HYPOTHESIS, "origin": "POST_HOC_DISCOVERY_2026-10-28",
                       "definition": "G_MULTI_ALERT and NOT M_IMPLIED_GOALS_DOWN",
                       "not_equivalent_to": "strict_episode_filter",
                       "state": verdict, "minimum_oos_ft": MIN_OOS_FT,
                       "single_hypothesis_alpha": ALPHA,
                       "test": "fixed-mixture one-sided e-process vs market",
                       "e_value": e,
                       "checkpoint": "continuous monitoring; insufficient evidence is never terminal",
                       "frozen_forecast_filter": "latest recorded message before kickoff"},
        "forecasts": {"records": len(records), "unique_matches": len(latest),
                      "ready_to_score": len(scored), "missing_or_bad_baseline_ft": sum(excluded.values()),
                      "with_market_baseline": sum(r["market_probability_over_2_5"] is not None for r in latest.values()),
                      "scope": "only games with actual known_at earlier than kickoff"},
        "comparisons": {"pattern_posthoc_original": sel, "other_observed": metrics(other),
                        "all_scored": metrics(scored)},
        "price_quality_historical": _retrospective_quality(root),
        "price_quality_policy": {"version": QUALITY_POLICY, "max_overround": MAX_OVERROUND,
                                 "applies_to_new_forecasts_only": True,
                                 "existing_forecasts_remain_frozen": True},
        "limitations": [
            "Market baseline is a Poisson model from Asian Total, not a traded O2.5 price.",
            "Historical pattern selection is post-hoc; no historical game validates it.",
            "Pricing-quality thresholds are heuristics; flagged quotes are not proof of feed corruption.",
            "Null for the sequential test assumes conditional calibration of market probabilities.",
            "No profitability, positive EV, automated picks, or OOS superiority has been demonstrated.",
        ],
    }


def run(root, now):
    root = Path(root)
    alerts, v4, errors = read_sources(root)
    timelines, _, _ = collect_timelines(alerts, v4, source_errors=errors)
    competitions = {a.get("match_key"): a.get("competition") for a in alerts
                    if isinstance(a, dict) and a.get("match_key") and a.get("competition")
                    and utc(a.get("observed_at")) is not None
                    and utc(a["observed_at"]) <= now}
    additions = captures(timelines, now, competitions)
    n = append_journal(root, now, additions)
    records = read_journal(root)
    return report(root, records, now), n
