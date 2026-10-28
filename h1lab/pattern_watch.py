"""Prospective V5 market-movement observer; NEVER a pick generator.

Reuses the unchanged V5 implied-lambda feature arithmetic. Separates the
historical G_MULTI_ALERT + NOT M_IMPLIED_GOALS_DOWN condition into episodes,
relevant rises, flat movements and opposite directions. A missing Total is
UNKNOWN, not 'no drop'. Does not access results, odds after kickoff, H1 tickets
or betting settings.

The append-only first-detection registry is observation-only; it is NOT the
V5 statistical frozen-hypothesis registry.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from .pattern_features import DLAM_EPS, message_metrics

SCHEMA = 1
STATUS = "PROSPECTIVE_OBSERVATION_NOT_VALIDATED_NOT_BETTING"


def utc(value):
    if not isinstance(value, str):
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except ValueError:
        return None


def classify(metrics, episode_ids):
    """Classify pre-kickoff messages. Input chronological, finite dlam or None.

    The original research criterion only requires >=2 messages without a
    message-level decline <= -0.05; it can accidentally include missing
    metrics and repeated messages. Quality-strict requires >=2 distinct
    episodes, and every relevant message to contain computable Total lambda.
    """
    count = len(metrics)
    if count < 2:
        return {"original": False, "strict": False, "category": "SINGLE_ALERT"}
    ds = [m.get("dlam") for m in metrics]
    original = not any(d is not None and d <= -DLAM_EPS for d in ds)
    episode_reps = {}
    for metric, episode in zip(metrics, episode_ids):
        if episode not in episode_reps:
            episode_reps[episode] = metric
    reps = list(episode_reps.values())
    independent = len(reps) >= 2
    complete = all(d is not None for d in ds)
    strictly_eligible = original and independent and complete
    d = [m.get("dlam") for m in reps if m.get("dlam") is not None]
    ups = sum(x >= DLAM_EPS for x in d)
    downs = sum(x <= -DLAM_EPS for x in d)
    if not complete:
        category = "INCOMPLETE_TOTAL"
    elif not independent:
        category = "POSSIBLE_DUPLICATE"
    elif ups and downs:
        category = "OPPOSING_DIRECTIONS"
    elif downs:
        category = "FALLING"
    elif ups == len(d):
        category = "RISING_EACH_EPISODE"
    elif ups:
        category = "RISING_WITH_FLAT"
    else:
        category = "FLAT_EACH_EPISODE"
    return {"original": original, "strict": strictly_eligible,
            "category": category, "episodes": len(reps),
            "up_episodes": ups, "down_episodes": downs,
            "flat_episodes": len(d)-ups-downs, "valid_messages": len(ds)-ds.count(None)}


def inspect(timeline, now):
    """Read a single timeline as known by `now`; only future kickoffs."""
    ident = timeline.get("identity") or {}
    kos = ident.get("kickoff_utc") or []
    if (len(kos) != 1 or not ident.get("kickoff_consistent", False) or
        not ident.get("team_names_consistent", False) or
        ident.get("per_message_conflicts")):
        return None
    kickoff = utc(kos[0])
    if not kickoff or kickoff <= now:
        return None
    events = sorted(
        (e for e in timeline.get("events", []) if
         utc(e.get("observed_at")) is not None and
         utc(e["observed_at"]) <= now and
         utc(e["observed_at"]) < kickoff and
         isinstance(e.get("minutes_to_kickoff"), (int, float)) and
         not isinstance(e["minutes_to_kickoff"], bool) and
         e["minutes_to_kickoff"] > 0),
        key=lambda e: (e["observed_at"], e["event_id"]),
    )
    if len(events) < 2:
        return None
    ep_index = {eid: n for n, group in enumerate(timeline.get("movement_episodes") or ())
                for eid in group}
    metrics, eps, observations = [], [], []
    for e in events:
        m = message_metrics(e)  # same V5 calculator and 0.05 threshold
        episode = ep_index.get(e["event_id"], e["event_id"])
        metrics.append(m)
        eps.append(episode)
        observations.append({
            "observed_at": e["observed_at"],
            "event_id": e["event_id"],
            "episode": str(episode),
            "delta_lambda": m.get("dlam"),
            "total_origin": m.get("total_origin"),
        })
    c = classify(metrics, eps)
    # The Total line comes from the last observed pre-kickoff message, never
    # from a reconstructed path or a later market snapshot.
    last_total = (events[-1].get("snapshots") or {}).get("total") or {}
    before_total = last_total.get("before") or {}
    after_total = last_total.get("after") or {}
    return {
        "total_line_before": before_total.get("line"),
        "total_line_after": after_total.get("line"),
        "total_line_origin": last_total.get("origin"),
        "match_key": timeline["match_key"], "match_label": timeline["match_label"],
        "kickoff_utc": kos[0], "first_alert_at": events[0]["observed_at"],
        "last_alert_at": events[-1]["observed_at"],
        "messages": len(events), "episodes": c["episodes"],
        "valid_total_messages": c["valid_messages"],
        "original_condition": c["original"],
        "strict_condition": c["strict"],
        "category": c["category"],
        "episode_directions": {
            "up": c["up_episodes"], "down": c["down_episodes"],
            "flat": c["flat_episodes"]},
        "v4_total_count": sum(o["total_origin"] == "V4_EXPLICIT" for o in observations),
        "h1_legacy_total_count": sum(o["total_origin"] == "H1_LEGACY_ONLY" for o in observations),
        "observations": observations,
    }


def build(timelines, now, old_history=None):
    if now.tzinfo is None:
        raise ValueError("now must include timezone")
    now = now.astimezone(timezone.utc)
    past = old_history or {"schema_version": SCHEMA, "entries": []}
    if past.get("schema_version") != SCHEMA or not isinstance(past.get("entries"), list):
        raise ValueError("invalid prospective observation history")
    entries = list(past["entries"])
    keys = [r["match_key"] for r in entries]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicated historical observation key")
    recorded = set(keys)
    current = []
    for timeline in timelines:
        row = inspect(timeline, now)
        if row:
            current.append(row)
    current.sort(key=lambda x: (x["kickoff_utc"], x["match_key"]))
    if len({x["match_key"] for x in current}) != len(current):
        raise ValueError("duplicate match key in timeline")
    for row in current:
        # The first strict observation of a match is frozen before kickoff.
        if row["strict_condition"] and row["match_key"] not in recorded:
            entries.append({
                "match_key": row["match_key"], "match_label": row["match_label"],
                "kickoff_utc": row["kickoff_utc"],
                "first_detected_at": now.isoformat(timespec="seconds"),
                "observed_through": row["last_alert_at"],
                "category_at_first_detection": row["category"],
                "observations_at_first_detection": row["observations"],
                "rule_version": 1,
            })
            recorded.add(row["match_key"])
    assert entries[:len(past["entries"])] == past["entries"]
    original = [r for r in current if r["original_condition"]]
    eligible = [r for r in original if r["strict_condition"]]
    excluded = [r for r in original if not r["strict_condition"]]
    opposite = [r for r in current if r["category"] == "OPPOSING_DIRECTIONS"]
    report = {
        "schema_version": SCHEMA, "status": STATUS,
        "generated_at": now.isoformat(timespec="seconds"),
        "scope": "Pre-kickoff observed AsianOdds messages only, one match per observation",
        "rules": {"min_alerts": 2, "min_independent_episodes": 2,
                  "min_total_completeness": "all observed pre-kickoff messages",
                  "significant_delta_lambda": DLAM_EPS,
                  "lambda_model": "V5 market_math Poisson inversion; not an exchangeable price"},
        "summary": {
            "future_with_two_or_more_messages": len(current),
            "original_condition": len(original),
            "strict_eligible": len(eligible),
            "possible_duplicate_or_incomplete": len(excluded),
            "contradictory_excluded_from_original": len(opposite),
            "strict_by_category": dict(sorted(Counter(r["category"] for r in eligible).items())),
            "total_historical_first_detections": len(entries),
        },
        "future_strict": eligible,
        "future_other_original": excluded,
        "future_opposing": opposite,
        "limitations": [
            "OBSERVATIONAL ONLY: nothing here is a recommendation or validated V5 hypothesis.",
            "A pair of messages may be one movement; strict eligibility counts distinct episodes.",
            "Missing totals are UNKNOWN, not a flat or rising market.",
            "Every movement is evaluated from Was to Now inside one observed message.",
            "Unobserved movements between messages are not inferred or interpolated.",
            "V4 source agreement is not independent Golden Set certification.",
            "First strict detection frozen before kickoff; classification can change when new alerts arrive.",
        ],
    }
    return report, {"schema_version": SCHEMA, "entries": entries}
