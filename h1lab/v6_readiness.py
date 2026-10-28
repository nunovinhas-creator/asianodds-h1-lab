"""V6 prospective coverage gate, explicitly based on observable source opportunities.

A Telegram observed_at before kickoff is NOT proof the collector received it
before kickoff. Therefore this is a conservative source-eligible coverage
denominator, not a claim of 99% real-time polling or ingestion performance.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from .v6_shadow import utc


def measure(timelines, records, now):
    if now.tzinfo is None:
        raise ValueError("timezone-aware now required")
    now = now.astimezone(timezone.utc)
    seen_first = [utc(x.get("known_at")) for x in records if utc(x.get("known_at"))]
    start = min(seen_first) if seen_first else None
    frozen = {r["match_key"] for r in records
              if utc(r.get("known_at")) and utc(r.get("kickoff_utc"))
              and utc(r["known_at"]) < utc(r["kickoff_utc"])}
    latest = {}
    for r in records:
        latest[r["match_key"]] = r
    flags = Counter()
    for r in latest.values():
        q = r.get("price_quality") or {}
        flags.update(q.get("flags") or [])
        if q.get("status") == "USABLE":
            flags["usable_market_baseline"] += 1
        elif q.get("status") == "NO_TOTAL":
            flags["no_total_in_last_message"] += 1
        else:
            flags["other_unusable_market_baseline"] += 1

    finished = {}
    for t in timelines:
        ident = t.get("identity") or {}
        kos = ident.get("kickoff_utc") or []
        if (len(kos) != 1 or not ident.get("kickoff_consistent", False)
                or not ident.get("team_names_consistent", False)
                or ident.get("per_message_conflicts")):
            continue
        kickoff = utc(kos[0])
        if not start or not kickoff or not start <= kickoff <= now:
            continue
        # Only messages actually timestamped before kickoff. Arrival time
        # of the Telegram message at the collector is not preserved.
        pre = any(utc(e.get("observed_at")) and utc(e["observed_at"]) < kickoff
                  for e in t.get("events", []))
        if pre:
            finished[t["match_key"]] = kickoff

    def coverage(days):
        if start is None:
            return {"source_eligible": 0, "frozen_pre_kickoff": 0,
                    "ratio": None, "missing_match_keys": [],
                    "interpretation": "SOURCE_ELIGIBLE_UPPER_BOUND_NOT_INGESTION"}
        lower = max(start, now - timedelta(days=days))
        keys = sorted(k for k, ko in finished.items() if ko >= lower)
        missing = [k for k in keys if k not in frozen]
        n = len(keys)
        return {"source_eligible": n, "frozen_pre_kickoff": n - len(missing),
                "ratio": round((n - len(missing)) / n, 4) if n else None,
                "missing_match_keys": missing[:50],
                "missing_count": len(missing),
                "interpretation": "SOURCE_ELIGIBLE_UPPER_BOUND_NOT_INGESTION"}

    elapsed = (now - start).total_seconds() / 86400 if start else 0
    week = coverage(7)
    fortnight = coverage(14)
    def gate(days, sample):
        if elapsed < days or sample["source_eligible"] == 0:
            return "WARMUP"
        return ("SOURCE_COVERAGE_PASS_PENDING_EXTERNAL_VERIFICATION"
                if sample["ratio"] >= 0.99 else "SOURCE_COVERAGE_BELOW_99_PERCENT")

    return {
        "schema_version": 1, "status": "V6_COVERAGE_OBSERVABILITY_NOT_MODEL_VALIDATION",
        "generated_at": now.isoformat(timespec="seconds"),
        "first_prospective_known_at": start.isoformat(timespec="seconds") if start else None,
        "days_since_first_capture": round(elapsed, 3),
        "records": len(records), "unique_matches": len(latest),
        "quality_counts_latest": dict(flags),
        "last_7_kickoff_days": week, "last_14_kickoff_days": fortnight,
        "p0_7_day_gate": gate(7, week), "v6_1_14_day_gate": gate(14, fortnight),
        "limitations": [
            "Telegram observed_at alone cannot prove a notification was ingested on time.",
            "Coverage is compared with observed pre-kickoff messages, not all fixtures.",
            "A passing code-level threshold still requires manual Git revision and run-log audit.",
            "No FT evidence or statistical superiority is inferred from capture coverage.",
        ],
    }
