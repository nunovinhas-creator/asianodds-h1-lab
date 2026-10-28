"""Bounded, persisted per-provider date rotation; no network operations.

A provider may fetch ONLY authorized days during one FT run; the provider
adapter's existing per-run budget remains the ultimate safety cap.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

SCHEMA = 1
CAPS = {"goal": 2, "openfoot": 2, "api_football": 3}
MAX_HISTORY_DAYS = 45
# Conservative ceilings for this FT workflow, not a claim about other API users.
# These are lower than the free tiers previously established for the project.
API_FOOTBALL_DAILY_LIMIT = 90
OPENFOOT_MONTHLY_LIMIT = 4500


def choose_days(selected_keys, matches, previous, now, enabled):
    """Rotate fixture dates across scheduled runs, without spending API calls.

    Oldest *last attempted date* wins; never checked dates go first.
    Selection is only from already eligible games picked by the FT queue.
    Repeating a date within a run costs at most one remote list request.
    """
    if now.tzinfo is None:
        raise ValueError("UTC aware clock required")
    if not isinstance(previous, dict) or previous.get("schema_version", 1) != 1:
        raise ValueError("Invalid provider date journal")
    history = previous.get("providers", {})
    if not isinstance(history, dict):
        raise ValueError("Invalid provider date history")
    now = now.astimezone(timezone.utc)
    usage = previous.get("usage", {})
    if not isinstance(usage, dict):
        raise ValueError("Malformed provider request usage")
    counts = Counter()
    for key in selected_keys:
        item = matches.get(key)
        if not isinstance(item, dict) or not isinstance(item.get("kickoff_utc"), str):
            continue
        stamp = item["kickoff_utc"]
        try:
            ko = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ko.tzinfo is None or ko.astimezone(timezone.utc) > now:
            continue
        if (now-ko.astimezone(timezone.utc)).days > 30:
            continue
        counts[ko.astimezone(timezone.utc).date().isoformat()] += 1
    result = {}
    for provider, cap in CAPS.items():
        if provider not in enabled:
            result[provider] = []
            continue
        days = history.get(provider, {})
        if not isinstance(days, dict):
            raise ValueError("Malformed provider dates")
        provider_usage = usage.get(provider, {})
        if not isinstance(provider_usage, dict) or any(
                type(v) is not int or v < 0 for v in provider_usage.values()):
            raise ValueError("Malformed provider request accounting")
        if provider == "api_football":
            cap = min(cap, max(0, API_FOOTBALL_DAILY_LIMIT -
                               provider_usage.get(now.date().isoformat(), 0)))
        elif provider == "openfoot":
            month = now.date().isoformat()[:7]
            used = sum(v for day,v in provider_usage.items() if day.startswith(month))
            cap = min(cap, max(0, OPENFOOT_MONTHLY_LIMIT - used))
        result[provider] = sorted(counts, key=lambda d: (
            days.get(d, {}).get("last_requested_at", "") if isinstance(days.get(d, {}), dict) else "",
            -counts[d], d
        ))[:cap]
    return result


def advance(previous, rotation, requested, now):
    """Record only days actually attempted by the provider adapter.

    Failed responses still spend free-tier calls and therefore consume a
    rotation turn. No invented requests, no private credentials persisted.
    """
    if now.tzinfo is None:
        raise ValueError("UTC aware clock required")
    old = previous.get("providers", {})
    out = {"schema_version": SCHEMA, "providers": {}, "usage": {}}
    old_usage = previous.get("usage", {})
    if not isinstance(old_usage, dict):
        raise ValueError("Malformed historical API usage")
    for p in CAPS:
        prior = old.get(p, {})
        if not isinstance(prior, dict):
            raise ValueError("Malformed persisted journal")
        days = {k: dict(v) for k,v in prior.items() if isinstance(v,dict)}
        permitted = set(rotation.get(p, []))
        actual = sorted(set(requested.get(p, [])))
        if not set(actual).issubset(permitted):
            raise ValueError("Provider queried an unplanned date")
        if len(actual) > CAPS[p]:
            raise ValueError("Provider date quota exceeded")
        for day in actual:
            row = days.get(day, {})
            row["requests"] = int(row.get("requests", 0)) + 1
            row["last_requested_at"] = now.astimezone(timezone.utc).isoformat(timespec="seconds")
            days[day] = row
        ordered = sorted(days.items(), key=lambda kv: (kv[1].get("last_requested_at", ""), kv[0]))
        out["providers"][p] = dict(ordered[-MAX_HISTORY_DAYS:])
        usage = dict(old_usage.get(p, {}))
        if any(type(v) is not int or v < 0 for v in usage.values()):
            raise ValueError("Invalid stored request usage")
        today = now.astimezone(timezone.utc).date().isoformat()
        usage[today] = usage.get(today,0) + len(actual)
        out["usage"][p] = {k:v for k,v in sorted(usage.items())[-MAX_HISTORY_DAYS:]}
    return out
