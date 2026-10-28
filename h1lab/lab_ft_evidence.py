"""Minimal, score-free fingerprints of authenticated provider day lists.

A fingerprint is only a change detector, NEVER proof of a fixture identity
or a 90-minute result. Empty complete lists are evidence; failed fetches are not.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .lab_api_football import _name as api_name, _time as api_time
from .lab_goal import _name as goal_name, _when as goal_time
from .lab_openfoot import names as open_names, utc as open_time


def fingerprint(lookup, provider, signal):
    adapter = getattr(lookup, "__self__", None)
    cache_name = {"api_football": "days", "goal": "cache",
                  "openfoot": "days"}.get(provider)
    cache = getattr(adapter, cache_name, None) if cache_name else None
    if not isinstance(cache, dict):
        return None
    try:
        kickoff = datetime.fromisoformat(signal["kickoff_utc"].replace("Z", "+00:00"))
        if kickoff.tzinfo is None:
            return None
        kickoff = kickoff.astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    day = kickoff.date().isoformat()
    if day not in cache or not isinstance(cache[day], list):
        return None
    rows = []
    for item in cache[day]:
        if not isinstance(item, dict):
            continue
        if provider == "api_football":
            when = api_time(item)
            home, away = api_name(item, "home"), api_name(item, "away")
            fixture = item.get("fixture") or {}
            status = fixture.get("status") or {} if isinstance(fixture, dict) else {}
            status = status.get("short") if isinstance(status, dict) else ""
            identifier = fixture.get("id") if isinstance(fixture, dict) else None
            teams = item.get("teams") or {}
            team_ids = [(teams.get(side) or {}).get("id") for side in ("home","away")] if isinstance(teams, dict) else []
        elif provider == "goal":
            when = goal_time(item)
            home, away = goal_name(item, "homeTeam"), goal_name(item, "awayTeam")
            status = [item.get("matchStatus"), item.get("matchPeriod"),
                      item.get("homeTeamFtScore") is not None,
                      item.get("awayTeamFtScore") is not None]
            identifier = item.get("apiId")
            team_ids = []
        else:
            when = open_time(item.get("kickoffAt"))
            home, away = open_names(item)
            status = item.get("status")
            identifier = item.get("id")
            team_ids = []
        if when is None or abs((when-kickoff).total_seconds()) > 5400:
            continue
        rows.append([str(identifier or ""), str(home or "")[:120],
                     str(away or "")[:120], when.isoformat(),
                     status, team_ids])
    rows.sort(key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False))
    payload = json.dumps(rows, sort_keys=True, ensure_ascii=False, default=str,
                         separators=(",", ":")).encode("utf-8")
    return {"day": day, "fingerprint": hashlib.sha256(payload).hexdigest(),
            "candidate_count": len(rows), "complete": True}


def day_fingerprint(provider, rows):
    """Hash a COMPLETE provider-day list without retaining scores or raw rows.

    None is reserved for failed/incomplete responses. Empty complete lists
    legitimately produce a deterministic hash. Never use this for FT matching.
    """
    if provider not in ("api_football", "goal", "openfoot") or not isinstance(rows, list):
        return None
    records = []
    for item in rows:
        if not isinstance(item, dict):
            return None
        if provider == "api_football":
            when = api_time(item)
            home, away = api_name(item, "home"), api_name(item, "away")
            fixture = item.get("fixture") or {}
            if not isinstance(fixture, dict):
                return None
            status = fixture.get("status") or {}
            status = status.get("short") if isinstance(status, dict) else None
            identifier = fixture.get("id")
            teams = item.get("teams") or {}
            if not isinstance(teams, dict):
                return None
            ids = [(teams.get(side) or {}).get("id") for side in ("home", "away")]
        elif provider == "goal":
            when = goal_time(item)
            home, away = goal_name(item, "homeTeam"), goal_name(item, "awayTeam")
            status = [item.get("matchStatus"), item.get("matchPeriod"),
                      item.get("homeTeamFtScore") is not None,
                      item.get("awayTeamFtScore") is not None]
            identifier = item.get("apiId")
            ids = []
        else:
            when = open_time(item.get("kickoffAt"))
            home, away = open_names(item)
            status = item.get("status")
            identifier = item.get("id")
            ids = []
        if when is None:
            return None
        records.append([str(identifier or ""), str(home or "")[:120],
                        str(away or "")[:120], when.isoformat(), status, ids])
    records.sort(key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False, default=str))
    return hashlib.sha256(json.dumps(records, sort_keys=True, ensure_ascii=False,
                          default=str, separators=(",", ":")).encode("utf-8")).hexdigest()
