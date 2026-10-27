"""Select high-information *real* Telegram events for independent human review.

This is a selection aid, NOT evidence of field correctness. Never prefill odds
or count V4 parser output as a reviewed reference.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timezone, datetime
from pathlib import Path
import json

from .v4_audit import CUTOVER, instant
from .golden import read_reviews

FEATURES = {
    "ah_line_changed_in_1x2": {"weight": 120, "label": "Handicap muda num alerta 1X2"},
    "total_line_changed_in_1x2": {"weight": 105, "label": "Total muda num alerta 1X2"},
    "1x2_trigger_up": {"weight": 85, "label": "Disparo 1X2 com odd a subir"},
    "1x2_trigger_down": {"weight": 65, "label": "Disparo 1X2 com odd a descer"},
    "same_match_repeated": {"weight": 80, "label": "Mesmo jogo com vários alertas"},
    "1x2_selection_X": {"weight": 110, "label": "Disparo 1X2 no empate"},
    "1x2_selection_1": {"weight": 35, "label": "Disparo 1X2 na equipa 1"},
    "1x2_selection_2": {"weight": 35, "label": "Disparo 1X2 na equipa 2"},
    "total_up": {"weight": 28, "label": "Linha de Total a subir"},
    "total_down": {"weight": 28, "label": "Linha de Total a descer"},
    "1x2_total_stable": {"weight": 15, "label": "Total estável dentro do 1X2"},
    "post_cutover_provenance": {"weight": 12, "label": "Parser V4 com proveniência"},
    "pre_cutover_no_revision": {"weight": 5, "label": "Registo V4 anterior à proveniência"},
}
SCHEMA_VERSION = 1


def classify_event(market, count_by_match, *, cutover=None):
    """Features depend only on actual persisted observations, not made-up text."""
    features = set()
    trigger = market.get("trigger") or {}
    tm = market.get("trigger_market")
    tables = market.get("markets") or {}
    total = tables.get("total") or {}
    ah = tables.get("asian_handicap") or {}
    if tm == "total":
        before, after = (total.get("before") or {}).get("line"), (total.get("after") or {}).get("line")
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            if after > before:
                features.add("total_up")
            elif after < before:
                features.add("total_down")
    if tm == "1x2" and "one_x_two" in tables:
        if ah.get("line_changed") is True:
            features.add("ah_line_changed_in_1x2")
        if total.get("line_changed") is True:
            features.add("total_line_changed_in_1x2")
        if total.get("line_changed") is False:
            features.add("1x2_total_stable")
        selection = trigger.get("selection")
        if selection in ("1", "X", "2"):
            features.add("1x2_selection_" + selection)
        before, after = trigger.get("before"), trigger.get("after")
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            if after > before:
                features.add("1x2_trigger_up")
            elif after < before:
                features.add("1x2_trigger_down")
    match = market.get("match_key")
    if match and count_by_match[match] > 1:
        features.add("same_match_repeated")
    when = instant(market.get("observed_at"))
    if when is not None and when >= (cutover or instant(CUTOVER)):
        if market.get("parser_revision") and market.get("parser_commit"):
            features.add("post_cutover_provenance")
    elif when is not None:
        features.add("pre_cutover_no_revision")
    return features


def build_priority_queue(state, format_rows, observations, reviews, *, limit=10):
    """Greedy marginal coverage with explicit observed and missing categories.

    Selection avoids already-reviewed event IDs. Reviewed features are *counted
    only as feature exposure*, not as independently authenticated truth.
    """
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    by_event = {x.get("event_id"): x for x in state.get("alerts", []) if isinstance(x, dict)}
    by_format = {x.get("event_id"): x for x in format_rows if isinstance(x, dict)}
    market_rows = [x for x in observations if isinstance(x, dict) and isinstance(x.get("event_id"), str)]
    match_counts = Counter(x.get("match_key") for x in market_rows if x.get("match_key"))
    previously_reviewed = {r.get("event_id") for _,r in reviews if isinstance(r,dict) and r.get("event_id")}
    rows, found = [], defaultdict(int)
    for market in market_rows:
        eid = market["event_id"]
        legacy = by_event.get(eid)
        if not legacy:
            continue
        features = classify_event(market, match_counts)
        for feature in features:
            found[feature] += 1
        when = instant(market.get("observed_at"))
        if when is None:
            continue
        fmt = by_format.get(eid) or {}
        rows.append({
            "event_id": eid,
            "home": legacy.get("home") or "",
            "away": legacy.get("away") or "",
            "competition": legacy.get("competition") or "",
            "observed_at": market.get("observed_at"),
            "market": legacy.get("market"),
            "format_id": fmt.get("format_id"),
            "format_family_id": fmt.get("format_family_id") or fmt.get("format_id"),
            "features": sorted(features),
            "previously_reviewed": eid in previously_reviewed,
            "pre_cutover": when < instant(CUTOVER),
        })
    reviewed_exposure = set().union(*(set(x["features"]) for x in rows if x["previously_reviewed"]))
    coverage = {key: {
        "observed_events": found[key],
        "present_in_reviewed_events": key in reviewed_exposure,
        "label": meta["label"],
    } for key,meta in FEATURES.items()}
    remaining = [row for row in rows if not row["previously_reviewed"]]
    selected = []
    seen = set(reviewed_exposure)
    while remaining and len(selected) < limit:
        def score(item):
            novelty = sum(FEATURES[key]["weight"] for key in item["features"] if key not in seen)
            # Subsequent examples still aid coverage, but rare phenomena lead.
            rare = sum(FEATURES[key]["weight"] / max(1, found[key]) for key in item["features"])
            post = 1 if not item["pre_cutover"] else 0
            return (novelty, rare, post, -len(item["features"]))
        # Stable chronological preference for equal scores.
        chosen = max(sorted(remaining,key=lambda x:(x["observed_at"],x["event_id"]),reverse=True),
                     key=score)
        selected.append({
            **{k:v for k,v in chosen.items() if k != "previously_reviewed"},
            "new_coverage": sorted(set(chosen["features"]) - seen),
            "why_review": [FEATURES[k]["label"] for k in sorted(
                chosen["features"],key=lambda x:-FEATURES[x]["weight"])][:4],
        })
        seen.update(chosen["features"])
        remaining.remove(chosen)
    not_observed = [key for key in FEATURES if not found[key]]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "SELECTION_ONLY_NOT_VERIFIED",
        "selection_strategy": "real V4+H1 event metadata; marginal rare-feature coverage; deterministic",
        "no_reference_values_prefilled": True,
        "source_event_count": len(rows),
        "reviewed_event_count": sum(r["previously_reviewed"] for r in rows),
        "priorities": selected,
        "feature_coverage": coverage,
        "not_observed_in_source": not_observed,
        "limitations": [
            "Selected features are derived from parser data and need original Telegram confirmation",
            "A recorded V4 feature is not evidence that the parser is correct",
            "Feature selection is purposeful, not a random statistical sample",
            "No selection-X case is fabricated if none appears in observed data",
            "Original Telegram text, screenshots and credentials are not persisted",
        ],
    }


def generate(root: Path, *, limit=10):
    state = json.loads((root/"data"/"state.json").read_text(encoding="utf-8"))
    from .v4_audit import read_jsonl
    formats, _ = read_jsonl(root, "formats")
    markets, _ = read_jsonl(root, "markets")
    reviews, _ = read_reviews(root)
    return build_priority_queue(state, formats, markets, reviews, limit=limit)
