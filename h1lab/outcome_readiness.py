"""Read-only research readiness: repeated-game outcomes, never betting returns."""
from __future__ import annotations

import csv
import io
from collections import Counter
from datetime import datetime, timedelta, timezone


STATUS = "READINESS_ONLY_NO_OUTCOME_TEST"


def _when(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _validated_results(csv_text: str):
    """Accept only exact-match H1 final rows with a traceable source."""
    results = {}
    rejected = 0
    for row in csv.DictReader(io.StringIO(csv_text)):
        key = (row.get("match_key") or "").strip()
        if not key:
            rejected += 1
            continue
        if key in results:
            raise ValueError("Duplicate match_key in H1 results; refuse ambiguous outcomes")
        is_final = (row.get("status") or "").strip().lower() == "final"
        usable = False
        if is_final:
            try:
                home = int(row.get("home_goals") or "")
                away = int(row.get("away_goals") or "")
                source = (row.get("source") or "").strip()
                usable = home >= 0 and away >= 0 and source.startswith("https://")
            except (ValueError, TypeError):
                usable = False
            if not usable:
                rejected += 1
        results[key] = usable
    return results, rejected


def generate(timeline: dict, results_csv: str, result_audit: dict,
             *, now: datetime | None = None) -> dict:
    """Produce aggregated coverage only, no odds→outcome association.

    Result coverage reflects H1 settlement files, not an independent audit
    of every fixture. No missing result may be treated as a betting loss.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    published = timeline.get("timelines", [])
    summary = timeline.get("summary", {})
    sampling = timeline.get("sampling", {})
    expected = int(summary.get("repeated_matches", -1))
    omitted = int(sampling.get("timelines_omitted", -1))
    if expected < 0 or omitted < 0 or len(published) + omitted != expected:
        raise ValueError("Timeline coverage inconsistent; do not publish misleading rates")
    keys = [item.get("match_key") for item in published]
    if not all(isinstance(key, str) and key for key in keys) or len(set(keys)) != len(keys):
        raise ValueError("Missing or duplicate match_key in published trajectories")
    if not isinstance(result_audit, dict):
        raise ValueError("H1 result audit must be an object")

    outcomes, rejected = _validated_results(results_csv)
    statuses = Counter()
    timing = Counter()
    tracking = Counter()
    before_kickoff_only = 0
    two_nonflat_pregame = 0
    for item in published:
        key = item["match_key"]
        kickoff_values = (item.get("identity") or {}).get("kickoff_utc", [])
        kickoffs = [_when(x) for x in kickoff_values]
        if len(kickoffs) != 1 or kickoffs[0] is None:
            stage = "KICKOFF_UNCONFIRMED"
            kickoff = None
        else:
            kickoff = kickoffs[0]
            stage = ("BEFORE_KICKOFF" if now < kickoff
                     else "BEFORE_3H_RESULT_DELAY" if now < kickoff + timedelta(hours=3)
                     else "AFTER_3H_RESULT_DELAY")
        timing[stage] += 1

        if outcomes.get(key) is True:
            statuses["H1_FINAL_RECORDED"] += 1
        elif key in result_audit:
            audit_status = result_audit[key].get("status", "") if isinstance(result_audit[key], dict) else ""
            statuses["H1_LOOKUP_PENDING" if audit_status == "pending"
                     else "H1_AUDIT_OTHER_NO_FINAL"] += 1
        elif key in outcomes:
            statuses["H1_RESULT_ROW_NOT_FINAL"] += 1
        else:
            statuses["NOT_TRACKED_IN_H1_RESULT_FILES"] += 1

        pregame = [e for e in item.get("events", [])
                   if isinstance(e.get("minutes_to_kickoff"), (int, float))
                   and e["minutes_to_kickoff"] > 0]
        if pregame and len(pregame) == len(item.get("events", [])):
            before_kickoff_only += 1
        nonflat = [e for e in pregame
                   if (e.get("snapshots") or {}).get("total")
                   and (e["snapshots"]["total"].get("before") or {}).get("line")
                       != (e["snapshots"]["total"].get("after") or {}).get("line")]
        if len(nonflat) >= 2:
            two_nonflat_pregame += 1
        tracking["H1_HAS_AUDIT_ENTRY" if key in result_audit else "NO_H1_AUDIT_ENTRY"] += 1

    settled = statuses["H1_FINAL_RECORDED"]
    count = len(published)
    return {
        "schema_version": 1,
        "status": STATUS,
        "source_commit": timeline.get("source_commit"),
        "as_of_utc": now.isoformat(timespec="seconds"),
        "scope": {
            "unit": "distinct match_key, not Telegram messages",
            "published_repeated_matches": count,
            "repeated_matches_in_source": expected,
            "repeated_matches_omitted": omitted,
            "source_all_distinct_matches": summary.get("matches"),
            "h1_results_rows": len(outcomes),
            "h1_final_rows_usable": sum(outcomes.values()),
            "h1_final_rows_invalid": rejected,
        },
        "repeated_match_outcomes": {
            "with_h1_final_record": settled,
            "without_h1_final_record": count - settled,
            "coverage_pct_of_published_repeated": round(settled / count * 100, 1) if count else None,
            "coverage_partial_if_omitted": omitted > 0,
            "statuses": dict(sorted(statuses.items())),
            "kickoff_stages": dict(sorted(timing.items())),
            "h1_tracking": dict(sorted(tracking.items())),
        },
        "pregame_data_readiness": {
            "all_observed_alerts_before_kickoff": before_kickoff_only,
            "at_least_two_nonflat_pregame_total_messages": two_nonflat_pregame,
            "caveat": "Two messages may describe the same market movement; not independent events or validated entries.",
        },
        "inference_gate": {
            "approved": False,
            "reason": "No outcome association tested; prospectively freeze sample/definitions and collect independently auditable final results.",
            "hypothesis_status": "NOT_TESTED",
        },
        "limitations": [
            "Only repeated matches published in the timeline are assessed.",
            "H1 tracks results for its own signals, not every alert in the channel.",
            "Absence of an H1 result never means no goal, a loss, or a failed lookup.",
            "H1 final rows are a linked outcome source, not external cross-provider re-verification by this LAB.",
            "Do not use in-play alerts as prematch evidence.",
            "No ROI, EV, betting selection, significance test, or estimated predictive performance is produced.",
        ],
    }
