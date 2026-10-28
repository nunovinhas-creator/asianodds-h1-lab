"""Read-only coverage diagnostics for the independent LAB FT collector.

Every metric is derived from the current ledger/report. No additional API
requests, guessed scores or modifications to H1 production files.
"""
from collections import Counter
from datetime import datetime, timezone


def coverage_diagnostics(ledger, report):
    rows = ledger.get("matches", {})
    timing = report.get("timing_counts", {})
    if not isinstance(rows, dict) or not isinstance(timing, dict):
        raise ValueError("Invalid LAB FT inputs")
    provider_reasons = Counter()
    unresolved = Counter()
    for game in rows.values():
        if game.get("status") == "FINAL":
            continue
        unresolved[game.get("status", "UNKNOWN")] += 1
        for provider, reason in (game.get("provider_reasons") or {}).items():
            provider_reasons[(str(provider), str(reason))] += 1
    return {
        "schema_version": 1,
        "unit": "distinct observed match_key",
        "ft_confirmed": report.get("final_recorded", 0),
        "future": timing.get("FUTURE", 0),
        "grace": timing.get("IN_3H_GRACE", 0),
        "blocked_review": timing.get("BLOCKED_REVIEW", 0),
        "past_unverified_eligible": sum(timing.get(k, 0) for k in (
            "ELIGIBLE_NEVER_QUERIED", "ELIGIBLE_RETRY_DUE",
            "ELIGIBLE_COOLDOWN", "ELIGIBLE_SOURCE_UPGRADE",
            "ELIGIBLE_REVIEWED_BSD_ID", "ELIGIBLE_REVIEWED_ALIAS",
            "EXPIRED")),
        "provider_obstacles": [
            {"provider": provider, "reason": reason, "matches": count}
            for (provider, reason), count in sorted(
                provider_reasons.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "unresolved_statuses": dict(sorted(unresolved.items())),
        "notes": [
            "Provider obstacles may overlap: the same game can fail multiple providers.",
            "Rate-limit counts come from attempts, not distinct API-wide coverage.",
            "No unresolved game is treated as an incorrect pick or a settled bet.",
        ],
    }
