"""Exploratory, match-level analysis of *observed* repeated Telegram alerts.

NO profit calculations, betting signals, continuous odds interpolation, or
statistical certification. Reads the descriptive LAB timeline, not H1 internals.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import json
import math

SCHEMA_VERSION = 1
STATUS = "EXPLORATORY_NO_OUTCOME_TEST"
STAGES = ("AFTER_KICKOFF", "T_0_TO_60", "T_60_TO_360",
          "T_360_TO_1440", "T_OVER_1440", "UNKNOWN")
DIRECTIONS = ("UP", "DOWN", "FLAT")
ORIGINS = ("V4_EXPLICIT", "H1_LEGACY_ONLY")


def stage(minutes):
    """Time-to-kickoff in minutes, never inferred from an unprovided kickoff."""
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not math.isfinite(minutes):
        return "UNKNOWN"
    if minutes < 0:
        return "AFTER_KICKOFF"
    if minutes < 60:
        return "T_0_TO_60"
    if minutes < 360:
        return "T_60_TO_360"
    if minutes < 1440:
        return "T_360_TO_1440"
    return "T_OVER_1440"


def frequency(n, total):
    """Percentages are explicitly *descriptive*, with declared denominators."""
    return round(n * 100 / total, 1) if total else None


def evaluate(chronology: dict, *, example_limit: int = 12):
    if not isinstance(chronology, dict) or chronology.get("schema_version") != 1:
        raise ValueError("Invalid timeline schema; do not publish")
    if chronology.get("status") != "DESCRIPTIVE_SHADOW_AUDIT_NOT_CERTIFIED":
        raise ValueError("Unexpected timeline status")
    timelines = chronology.get("timelines")
    sampling = chronology.get("sampling", {})
    summary = chronology.get("summary", {})
    if not isinstance(timelines, list) or not isinstance(sampling, dict) or not isinstance(summary, dict):
        raise ValueError("Malformed timeline report")
    if type(example_limit) is not int or example_limit < 1:
        raise ValueError("Invalid example limit")
    if sampling.get("timelines_published") != len(timelines):
        raise ValueError("Partial/corrupted timeline list")
    if not isinstance(sampling.get("timelines_omitted"), int) or sampling["timelines_omitted"] < 0:
        raise ValueError("Missing sampling limits")

    counts = Counter()
    origins = Counter()
    times = Counter()
    stage_matches = {k: set() for k in STAGES}
    matches_with = {k: set() for k in (
        "opposing_intra_alert_directions", "both_total_and_1x2",
        "at_least_two_nonflat_total_alerts", "with_related_alerts",
        "with_identical_total_snapshots", "with_unobserved_line_gaps",
        "with_ambiguous_repeats", "with_only_v4_total",
        "with_only_legacy_total", "with_mixed_origin_total",
        "with_post_kickoff_alerts")}
    examples = []
    seen_match_keys = set()
    seen_event_ids = set()
    invalid = []
    all_direction_events = 0

    for t in timelines:
        if not isinstance(t, dict):
            raise ValueError("Malformed repeated-match timeline")
        match_key = t.get("match_key")
        if not isinstance(match_key, str) or not match_key or match_key in seen_match_keys:
            raise ValueError("Duplicate/invalid match_key")
        seen_match_keys.add(match_key)
        events = t.get("events")
        if not isinstance(events, list) or len(events) < 2:
            raise ValueError("Expected at least two events per repeated match")
        event_ids = []
        has_v4 = has_legacy = False
        for e in events:
            eid = e.get("event_id") if isinstance(e, dict) else None
            if not isinstance(eid, str) or not eid or eid in seen_event_ids:
                raise ValueError("Duplicate/invalid event_id")
            seen_event_ids.add(eid)
            event_ids.append(eid)
            category = stage(e.get("minutes_to_kickoff"))
            times[category] += 1
            stage_matches[category].add(match_key)
            counts["message_total"] += 1
            counts["1x2_trigger"] += e.get("trigger_market") == "1x2"
            counts["total_trigger"] += e.get("trigger_market") == "total"
            has_v4 |= any(x.get("origin") == "V4_EXPLICIT" for x in (e.get("snapshots") or {}).values())
            has_legacy |= any(x.get("origin") == "H1_LEGACY_ONLY" for x in (e.get("snapshots") or {}).values())
        if len(set(event_ids)) != len(events):
            raise ValueError("Event-ID collision")
        if any(stage(e.get("minutes_to_kickoff")) == "AFTER_KICKOFF" for e in events):
            matches_with["with_post_kickoff_alerts"].add(match_key)
        if has_v4 and has_legacy:
            counts["mixed_v4_legacy_match"] += 1

        tr = t.get("trajectory") or {}
        total = tr.get("total") or {}
        points = total.get("points", [])
        if not isinstance(points, list):
            raise ValueError("Invalid Total trajectory")
        if any(p.get("move") not in DIRECTIONS or p.get("origin") not in ORIGINS for p in points):
            raise ValueError("Invalid Total point/origin; no guesses")
        for p in points:
            counts["total_"+p["move"].lower()] += 1
            origins[p["origin"]] += 1
        all_direction_events += len(points)
        nonflat = [p["move"] for p in points if p["move"] != "FLAT"]
        if len(nonflat) >= 2:
            matches_with["at_least_two_nonflat_total_alerts"].add(match_key)
        if "UP" in nonflat and "DOWN" in nonflat:
            matches_with["opposing_intra_alert_directions"].add(match_key)
            examples.append({
                "match_key": match_key, "match_label": t.get("match_label", ""),
                "event_ids": event_ids, "directions": [p["move"] for p in points],
                "interpretation": "OPPOSING_INTRA_ALERT_DIRECTIONS_NOT_CONTINUOUS_REVERSAL",
            })

        origin_set = {p["origin"] for p in points}
        if origin_set == {"V4_EXPLICIT"}:
            matches_with["with_only_v4_total"].add(match_key)
        elif origin_set == {"H1_LEGACY_ONLY"}:
            matches_with["with_only_legacy_total"].add(match_key)
        elif origin_set == set(ORIGINS):
            matches_with["with_mixed_origin_total"].add(match_key)

        transitions = total.get("transitions") or []
        for line in transitions:
            typ = line.get("line")
            if typ == "UNOBSERVED_CHANGE":
                counts["gap_transitions"] += 1
                matches_with["with_unobserved_line_gaps"].add(match_key)
            elif typ == "AMBIGUOUS_REPEAT_OR_REVERSAL":
                counts["ambiguous_transitions"] += 1
                matches_with["with_ambiguous_repeats"].add(match_key)
            elif typ == "CONTINUOUS":
                counts["continuous_transitions"] += 1
            elif typ == "SAME_MOVEMENT_REPEAT":
                counts["same_movement_transitions"] += 1
            else:
                invalid.append({"match_key": match_key, "issue": "unknown_transition_class"})
        related = t.get("related_messages") or []
        if related:
            matches_with["with_related_alerts"].add(match_key)
        for pair in related:
            counts["related_pairs"] += 1
            typ = pair.get("evidence")
            if typ == "IDENTICAL_TOTAL_SNAPSHOT":
                counts["identical_total_pairs"] += 1
                matches_with["with_identical_total_snapshots"].add(match_key)
            elif typ == "SAME_TOTAL_LINE_MOVE_DIFFERENT_PRICES":
                counts["same_lines_different_price_pairs"] += 1
            else:
                invalid.append({"match_key": match_key, "issue": "unknown_relation_class"})
        if any("one_x_two" in (e.get("snapshots") or {}) for e in events) and points:
            matches_with["both_total_and_1x2"].add(match_key)

    if invalid:
        raise ValueError("Unrecognised trajectory classifications; refuse to publish")
    sample = len(timelines)
    count_by_match = {k: len(v) for k, v in matches_with.items()}
    observed_total = sum(counts["total_"+v.lower()] for v in DIRECTIONS)
    if observed_total != all_direction_events:
        raise ValueError("Direction denominator mismatch")
    if summary.get("repeated_matches") != sample + sampling["timelines_omitted"]:
        raise ValueError("Published sample does not reconcile with timeline summary")
    if sampling["timelines_omitted"] == 0:
        expected = summary.get("messages_on_repeated_matches")
        if expected is not None and expected != counts["message_total"]:
            raise ValueError("Repeated-match message total mismatch")
    if sample and summary.get("matches", 0) < sample:
        raise ValueError("More repeated matches than distinct matches")

    examples.sort(key=lambda e: (e["match_label"],e["match_key"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "source_generated_at": chronology.get("generated_at"),
        "source_commit": chronology.get("source_commit"),
        "scope": {
            "messages_in_source": summary.get("messages"),
            "all_distinct_matches": summary.get("matches"),
            "repeated_matches_in_source": summary.get("repeated_matches"),
            "repeated_matches_analysed": sample,
            "repeated_matches_omitted": sampling["timelines_omitted"],
            "coverage": ("ALL_PUBLISHED_REPEATED_MATCHES" if not sampling["timelines_omitted"] else
                         "PARTIAL_RECENT_REPEATED_MATCHES"),
            "events_analysed": counts["message_total"],
            "unit_for_pattern_prevalence": "distinct match_key",
            "unit_for_direction_tabulation": "one Total table per Telegram message",
        },
        "total_line_within_alert": {
            "messages_with_total": observed_total,
            "up": counts["total_up"], "down": counts["total_down"], "flat": counts["total_flat"],
            "by_origin": dict(sorted(origins.items())),
            "direction_pct_of_messages_with_total": {
                typ: frequency(counts["total_"+typ.lower()],observed_total)
                for typ in DIRECTIONS},
            "warning": "This tabulation is per message, not independent betting trials",
        },
        "match_level_patterns": {
            name: {"matches": n, "of_repeated_matches_analysed":sample,
                   "percentage_descriptive": frequency(n,sample)}
            for name,n in sorted(count_by_match.items())
        },
        "transitions": {
            "continuous":counts["continuous_transitions"],
            "unobserved_change":counts["gap_transitions"],
            "ambiguous_repeat_or_reversal":counts["ambiguous_transitions"],
            "same_movement_repeat":counts["same_movement_transitions"],
            "related_pairs":counts["related_pairs"],
            "identical_total_pairs":counts["identical_total_pairs"],
            "same_lines_different_prices_pairs":counts["same_lines_different_price_pairs"],
            "rule":"Relations are annotations; do not delete alerts or assert independent moves",
        },
        "time_to_kickoff": {
            "messages_by_bucket":{k:times[k] for k in STAGES},
            "distinct_matches_touching_bucket":{k:len(stage_matches[k]) for k in STAGES},
            "buckets":"minutes before scheduled kickoff: <0, 0–<60, 60–<360, 360–<1440, >=1440",
            "warning":"Match counts across buckets can overlap; alerts are not continuously sampled",
        },
        "opposing_direction_examples":examples[:example_limit],
        "hypotheses_for_future_oos_only":[
            {
                "id":"H1_DIRECTION_REVERSAL_AND_TOTAL_GOALS",
                "status":"NOT_TESTED", "endpoint":"independently settled full-time total goals",
                "design":"prospective, match-level; require >=2 confirmed non-flat alerts; stratify by lead time; no in-play leakage",
            },
            {
                "id":"H2_PREMATCH_TIMING_AND_PERSISTENCE",
                "status":"NOT_TESTED", "endpoint":"next independently observed market snapshot (not interpolated)",
                "design":"compare lead-time buckets only after uniform sampling/coverage and independent closing line",
            },
            {
                "id":"H3_LINKED_ALERTS_ARE_CORRELATED",
                "status":"DESCRIPTIVE_ONLY", "endpoint":"message clusters by match and shared Total snapshot",
                "design":"cluster at match_key; do not use linked notifications as independent bets or trials",
            },
        ],
        "limitations":[
            "The channel is event-triggered, not a continuous market feed; sample is selectively observed.",
            "Only repeated-match trajectories are included; do not generalise rates to all matches.",
            "Opposing directions in messages do not prove the intermediate line reversed in real time.",
            "Unobserved gaps are not interpolated; legacy H1 is not independent source validation.",
            "Published trajectories may be a recent subset when sampling.timelines_omitted > 0.",
            "No match result, bet settlement, expected value, ROI, p-value or profitability was tested.",
            "Descriptive percentages are conditional on the published repeated-match sample.",
            "User-provided Telegram messages and snapshots are not published with this summary.",
        ],
    }


def generate(root: Path):
    path = Path(root) / "docs" / "lab" / "match-trajectories.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return evaluate(data)
