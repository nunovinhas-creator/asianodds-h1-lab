"""Versioned V6 *capture-time* cross-market features; no H1 or V5 changes.

FEATURE_VERSION=2 is deliberately a V6 namespace, NOT a change to the frozen
V5 pattern_features.FEATURE_VERSION=1. Observations are messages, not a stream
of continuously sampled bookmaker prices. A missing market is UNKNOWN.
Historical V6 forecasts are NEVER backfilled from today's timeline.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import timezone

from .market_math import (fair_probs, implied_lambda, margin, prob_total_over,
                          valid_line, valid_price)
from .v6_shadow import MAX_OVERROUND, utc

FEATURE_VERSION = 2
NAMESPACE = "V6F2"
SCHEMA = "V6-OBSERVED-MARKETS-2"
MARKETS = ("total", "one_x_two", "asian_handicap")


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def digest(obj):
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def _round(value):
    return round(value, 5) if value is not None else None


def _ah_line_ok(value):
    # AH runs both sides of zero: -0.75 and +0.75 are valid handicap lines.
    return (isinstance(value, (float, int)) and not isinstance(value, bool)
            and math.isfinite(value) and -15 <= value <= 15
            and abs(value * 4 - round(value * 4)) < 1e-7)


def _margin_ok(*prices):
    m = margin(*prices)
    return m is not None and 0 <= m <= MAX_OVERROUND


def _total(snap):
    b, a = snap.get("before") or {}, snap.get("after") or {}
    out = {"origin": snap.get("origin"), "status": "UNKNOWN",
           "line_before": b.get("line"), "line_after": a.get("line"),
           "before_probability_o25": None, "after_probability_o25": None,
           "delta_probability_o25": None, "delta_lambda": None,
           "quality_policy": "V6_Q2_MARGIN_12PCT"}
    def calc(side):
        if not (valid_line(side.get("line")) and
                _margin_ok(side.get("over_price"), side.get("under_price"))):
            return None, None
        lam = implied_lambda(side["line"], side["over_price"], side["under_price"])
        return lam, prob_total_over(lam)
    lb, pb = calc(b)
    la, pa = calc(a)
    out["before_probability_o25"] = pb
    out["after_probability_o25"] = pa
    if pb is not None and pa is not None:
        out["delta_probability_o25"] = _round(pa - pb)
        out["delta_lambda"] = _round(la - lb)
        out["status"] = "BOTH_SIDES_USABLE"
    else:
        out["status"] = "INCOMPLETE_OR_SUSPECT_QUOTE"
    # A repeated price across different lines is ambiguous; it must not be
    # classified as an observed probability movement for V6.
    if b.get("line") != a.get("line") and (
        b.get("over_price") == a.get("over_price") or
        b.get("under_price") == a.get("under_price")
    ):
        out.update(status="CROSS_LINE_REPEATED_PRICE_SUSPECT",
                   delta_probability_o25=None, delta_lambda=None)
    return out


def _one_x_two(snap):
    out = {"origin": snap.get("origin"), "status": "UNKNOWN",
           "before": None, "after": None, "delta": None,
           "margin_before": None, "margin_after": None}
    try:
        odds_b = [snap[x]["before"] for x in ("1", "X", "2")]
        odds_a = [snap[x]["after"] for x in ("1", "X", "2")]
    except (KeyError, TypeError):
        return out
    mb, ma = margin(*odds_b), margin(*odds_a)
    out.update(margin_before=_round(mb), margin_after=_round(ma))
    if not (_margin_ok(*odds_b) and _margin_ok(*odds_a)):
        out["status"] = "SUSPECT_OR_INVALID_PRICE"
        return out
    pb, pa = fair_probs(*odds_b), fair_probs(*odds_a)
    names = ("home", "draw", "away")
    out.update(status="USABLE",
               before=dict(zip(names, [_round(x) for x in pb])),
               after=dict(zip(names, [_round(x) for x in pa])),
               delta=dict(zip(names, [_round(a - b) for a,b in zip(pa,pb)])))
    return out


def _handicap(snap):
    b, a = snap.get("before") or {}, snap.get("after") or {}
    out = {
        "origin": snap.get("origin"), "status": "UNKNOWN",
        "line_before": b.get("line"), "line_after": a.get("line"),
        "line_delta": None, "home_price_delta": None,
        "away_price_delta": None, "margin_before": None,
        "margin_after": None, "towards": "UNKNOWN",
    }
    prices_b = [b.get("home_price"), b.get("away_price")]
    prices_a = [a.get("home_price"), a.get("away_price")]
    out["margin_before"] = _round(margin(*prices_b))
    out["margin_after"] = _round(margin(*prices_a))
    if not (_ah_line_ok(b.get("line")) and _ah_line_ok(a.get("line")) and
            _margin_ok(*prices_b) and _margin_ok(*prices_a)):
        out["status"] = "INCOMPLETE_OR_SUSPECT_QUOTE"
        return out
    d = a["line"] - b["line"]
    out.update(status="USABLE", line_delta=_round(d),
               home_price_delta=_round(prices_a[0] - prices_b[0]),
               away_price_delta=_round(prices_a[1] - prices_b[1]),
               towards="HOME" if d < 0 else "AWAY" if d > 0 else "UNCHANGED")
    return out


def _pair_relation(total, one):
    if total is None or one is None:
        return {"relation": "UNOBSERVED", "type": "NOT_CO_OBSERVED"}
    if total["status"] != "BOTH_SIDES_USABLE" or one["status"] != "USABLE":
        return {"relation": "UNKNOWN_INVALID_MARKET", "type": "CO_OBSERVED_NO_INFERENCE"}
    return {
        "relation": "CO_OBSERVED_SAME_MESSAGE",
        "type": "DESCRIPTIVE_CO_MOVEMENT_NOT_CAUSAL",
        "total_delta_p_over_2_5": total["delta_probability_o25"],
        "one_x_two_delta_home": one["delta"]["home"],
        "one_x_two_delta_draw": one["delta"]["draw"],
        "one_x_two_delta_away": one["delta"]["away"],
        "interpretation": "No unique mapping between 1X2 probabilities and goal totals",
    }


def build(timeline, events, *, known_at, competition=None):
    """Capture-time V6 features only from source messages actually known now.

    Caller supplies events filtered by observed_at <= actual known_at and before
    kickoff. Future full-timeline relations must NOT influence the results.
    """
    when = utc(known_at) if isinstance(known_at, str) else known_at
    if when is None or when.tzinfo is None:
        raise ValueError("known_at must be timezone-aware")
    ko_values = (timeline.get("identity") or {}).get("kickoff_utc") or []
    if len(ko_values) != 1:
        raise ValueError("unique kickoff required for frozen context")
    kickoff = utc(ko_values[0])
    if not kickoff or not when < kickoff:
        raise ValueError("known_at must strictly precede kickoff")
    ordered = sorted(events, key=lambda e:(e["observed_at"],e["event_id"]))
    if not ordered:
        raise ValueError("at least one observed message required")
    source_ids = set()
    messages = []
    totals, one_x_twos, handicaps = [], [], []
    for e in ordered:
        observed = utc(e.get("observed_at"))
        if (not observed or observed > when or observed >= kickoff or
                e.get("event_id") in source_ids):
            raise ValueError("future, post-kickoff or duplicated source message")
        source_ids.add(e["event_id"])
        snaps = e.get("snapshots") or {}
        total = _total(snaps["total"]) if "total" in snaps else None
        one = _one_x_two(snaps["one_x_two"]) if "one_x_two" in snaps else None
        ah = _handicap(snaps["asian_handicap"]) if "asian_handicap" in snaps else None
        if total is not None:
            totals.append((e["event_id"],total))
        if one is not None:
            one_x_twos.append((e["event_id"],one))
        if ah is not None:
            handicaps.append((e["event_id"],ah))
        messages.append({
            "event_id":e["event_id"],"observed_at":e["observed_at"],
            "markets_present":sorted(k for k in snaps if k in MARKETS),
            "total":total, "one_x_two":one,"asian_handicap":ah,
            "total_1x2":_pair_relation(total,one),
            "note":"Was->Now is observed only within this exact Telegram message",
        })
    total_transitions = []
    for prev, cur in zip(ordered,ordered[1:]):
        a = (prev.get("snapshots") or {}).get("total")
        b = (cur.get("snapshots") or {}).get("total")
        if a is None or b is None:
            total_transitions.append({"from_event_id":prev["event_id"],
                "to_event_id":cur["event_id"],"classification":"MISSING_TOTAL_AT_BOUNDARY",
                "inferred_movement":None})
        else:
            left = (a.get("after") or {}).get("line")
            right = (b.get("before") or {}).get("line")
            if not (valid_line(left) and valid_line(right)):
                category="UNKNOWN_INVALID_LINE"
            elif left != right:
                category="UNOBSERVED_LINE_GAP"
            else:
                # Even an equal boundary line cannot prove quote continuity.
                category="SAME_BOUNDARY_LINE_PRICES_NOT_CONTINUOUSLY_OBSERVED"
            total_transitions.append({"from_event_id":prev["event_id"],
                "to_event_id":cur["event_id"],"classification":category,
                "inferred_movement":None})
    if totals and one_x_twos:
        direct = sum(m["total_1x2"]["relation"]=="CO_OBSERVED_SAME_MESSAGE" for m in messages)
        relation="SAME_MESSAGE" if direct else "SEPARATE_MESSAGES_ONLY"
    else:
        relation="UNKNOWN_MARKET_NOT_OBSERVED"
    # The original competition text may be missing: do NOT assume 'league'.
    from .v6_shadow import _competition_type
    out = {
        "schema":SCHEMA,"version":FEATURE_VERSION, "namespace":NAMESPACE,
        "source":"FROZEN_CAPTURE_TIME_ONLY",
        "known_at":when.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "kickoff_utc":ko_values[0],
        "source_event_ids":[e["event_id"] for e in ordered],
        "competition":{"raw_at_capture":competition,
                       "category_heuristic":_competition_type(competition),
                       "classification_confidence":"HEURISTIC_NOT_VALIDATED"},
        "coverage":{"message_count":len(messages),"with_total":len(totals),
                    "with_one_x_two":len(one_x_twos),
                    "with_asian_handicap":len(handicaps),
                    "co_observed_total_one_x_two":sum(
                        m["total_1x2"]["relation"]=="CO_OBSERVED_SAME_MESSAGE" for m in messages),
                    "unobserved_inter_message_intervals":max(0,len(messages)-1)},
        "total_1x2_relation":relation,
        "last_observed":{
            "total":dict(event_id=totals[-1][0],**totals[-1][1]) if totals else None,
            "one_x_two":dict(event_id=one_x_twos[-1][0],**one_x_twos[-1][1]) if one_x_twos else None,
            "asian_handicap":dict(event_id=handicaps[-1][0],**handicaps[-1][1]) if handicaps else None,
        },
        "inter_message_total":total_transitions,
        "messages":messages,
        "limitations":[
            "Separate market alerts do not imply contemporaneous bookmaker odds",
            "Between alerts the market is never observed continuously",
            "Competition categories are heuristics based on source text",
            "No interpolated prices, result-dependent features or validated new predictions",
        ],
    }
    out["sha256"]=digest(out)
    return out


def verify(record):
    """Verify frozen V2 contents without ever recomputing historical context."""
    if not isinstance(record,dict):
        return False
    return (record.get("schema")==SCHEMA and record.get("version")==FEATURE_VERSION
            and record.get("namespace")==NAMESPACE
            and isinstance(record.get("source_event_ids"),list)
            and record.get("sha256")==digest({k:v for k,v in record.items() if k!="sha256"}))
