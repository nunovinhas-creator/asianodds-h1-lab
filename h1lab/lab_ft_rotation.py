"""Bounded, persisted per-provider date rotation; no network operations.

A provider may fetch ONLY authorized days during one FT run; the provider
adapter's existing per-run budget remains the ultimate safety cap.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from .lab_api_football_access import restriction_for_day

SCHEMA = 1
CAPS = {"goal": 2, "openfoot": 2, "api_football": 3}
MAX_HISTORY_DAYS = 45
# Conservative ceilings for this FT workflow, not a claim about other API users.
# These are lower than the free tiers previously established for the project.
API_FOOTBALL_DAILY_LIMIT = 90
# Local LAB ceiling; actual GOAL provider allowance remains unverified.
GOAL_DAILY_LIMIT = 80
OPENFOOT_MONTHLY_LIMIT = 4500
RETRY_VERSION = 7


def _day_wait(row):
    if row.get("last_fetch_status") != "COMPLETE":
        return timedelta(hours=4)
    stable = max(0, int(row.get("stable_confirmations", 0)))
    return timedelta(hours=24 if stable >= 2 else 12 if stable >= 1 else 4)


def _eligible_day(row, now):
    if not isinstance(row, dict) or row.get("retry_version") != RETRY_VERSION:
        return True  # migrate legacy date rotation on the next real request
    stamp = row.get("last_requested_at")
    if not isinstance(stamp, str):
        return True
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return False  # malformed V7 journal: fail closed
    if when.tzinfo is None:
        return False
    return now >= when.astimezone(timezone.utc) + _day_wait(row)


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
        if provider == "goal":
            cap = min(cap, max(0, GOAL_DAILY_LIMIT -
                               provider_usage.get(now.date().isoformat(), 0)))
        elif provider == "api_football":
            cap = min(cap, max(0, API_FOOTBALL_DAILY_LIMIT -
                               provider_usage.get(now.date().isoformat(), 0)))
        elif provider == "openfoot":
            month = now.date().isoformat()[:7]
            used = sum(v for day,v in provider_usage.items() if day.startswith(month))
            cap = min(cap, max(0, OPENFOOT_MONTHLY_LIMIT - used))
        access = (previous.get("api_football_history_access", {})
                  if provider == "api_football" else {})
        available = [day for day in counts
                     if _eligible_day(days.get(day), now)
                     and (provider != "api_football"
                          or restriction_for_day(access, day, now) is None)]
        result[provider] = sorted(available, key=lambda d: (
            days.get(d, {}).get("last_requested_at", "") if isinstance(days.get(d, {}), dict) else "",
            -counts[d], d
        ))[:cap]
    return result


def advance(previous, rotation, requested, now, *, extra_requests=None, fingerprints=None):
    """Record only days actually attempted by the provider adapter.

    Failed responses still spend free-tier calls and therefore consume a
    rotation turn. No invented requests, no private credentials persisted.
    """
    if now.tzinfo is None:
        raise ValueError("UTC aware clock required")
    extra_requests = extra_requests or {}
    fingerprints = fingerprints or {}
    if (not isinstance(fingerprints, dict) or
            any(p not in CAPS or not isinstance(value, dict)
                for p, value in fingerprints.items())):
        raise ValueError("Invalid provider-day fingerprints")
    if any(p not in CAPS or type(n) is not int or n < 0 for p,n in extra_requests.items()):
        raise ValueError("Invalid supplementary request count")
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
        if len(actual) + extra_requests.get(p,0) > CAPS[p]:
            raise ValueError("Provider date quota exceeded")
        provided = fingerprints.get(p, {})
        if not set(provided).issubset(actual):
            raise ValueError("Fingerprint for a date not requested")
        for day in actual:
            row = days.get(day, {})
            new_hash = provided.get(day)
            if new_hash is not None and (not isinstance(new_hash, str) or
                    len(new_hash) != 64 or any(c not in "0123456789abcdef" for c in new_hash)):
                raise ValueError("Invalid provider day fingerprint")
            row["requests"] = int(row.get("requests", 0)) + 1
            row["last_requested_at"] = now.astimezone(timezone.utc).isoformat(timespec="seconds")
            row["retry_version"] = RETRY_VERSION
            if new_hash is None:
                # A failed/incomplete fetch spends quota but is NOT stability.
                row["last_fetch_status"] = "UNAVAILABLE"
            else:
                stable = row.get("last_fetch_status") == "COMPLETE" and row.get("fingerprint") == new_hash
                row["stable_confirmations"] = (int(row.get("stable_confirmations", 0)) + 1 if stable else 0)
                row["fingerprint"] = new_hash
                row["last_fetch_status"] = "COMPLETE"
            days[day] = row
        ordered = sorted(days.items(), key=lambda kv: (kv[1].get("last_requested_at", ""), kv[0]))
        out["providers"][p] = dict(ordered[-MAX_HISTORY_DAYS:])
        usage = dict(old_usage.get(p, {}))
        if any(type(v) is not int or v < 0 for v in usage.values()):
            raise ValueError("Invalid stored request usage")
        today = now.astimezone(timezone.utc).date().isoformat()
        usage[today] = usage.get(today,0) + len(actual) + extra_requests.get(p,0)
        if p == "goal" and usage[today] > GOAL_DAILY_LIMIT:
            raise ValueError("GOAL daily LAB ceiling exceeded")
        if p == "api_football" and usage[today] > API_FOOTBALL_DAILY_LIMIT:
            raise ValueError("API-Football daily LAB ceiling exceeded")
        out["usage"][p] = {k:v for k,v in sorted(usage.items())[-MAX_HISTORY_DAYS:]}
    return out
