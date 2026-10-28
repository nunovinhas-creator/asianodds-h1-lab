"""Score-free, complete API-Football day identity index for human FT review.

Only authenticated complete fixture-date caches may feed this index. It stores
fixture IDs, team IDs, names, league ID/name and UTC kickoff, NEVER scores,
credentials, odds or results. An incomplete day is unusable for collision
proof or auto settlement. No network operations.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from .lab_api_football import _time, _name
from .lab_ft_evidence import day_fingerprint

SCHEMA = 1
MAX_DAYS = 45
MAX_FIXTURES_PER_DAY = 7000


def _positive(x):
    return type(x) is int and x > 0


def _read_event(event, day):
    if not isinstance(event, dict):
        return None
    fixture, teams, league = (event.get(key) for key in ("fixture", "teams", "league"))
    if not all(isinstance(x, dict) for x in (fixture, teams, league)):
        return None
    h, a = teams.get("home"), teams.get("away")
    if not isinstance(h, dict) or not isinstance(a, dict):
        return None
    fid, hid, aid, league_id = fixture.get("id"), h.get("id"), a.get("id"), league.get("id")
    when = _time(event)
    home, away = _name(event, "home"), _name(event, "away")
    league_name = league.get("name")
    if (not all(_positive(x) for x in (fid, hid, aid, league_id))
            or hid == aid or when is None or when.date().isoformat() != day
            or not all(isinstance(n, str) and n.strip() and len(n) <= 180
                        for n in (home, away, league_name))):
        return None
    return {"fixture_id": fid, "home_team_id": hid, "away_team_id": aid,
            "home": home.strip(), "away": away.strip(),
            "competition_id": league_id, "competition": league_name.strip(),
            "kickoff_utc": when.astimezone(timezone.utc).isoformat(timespec="seconds")}


def build_index(previous, caches, now):
    """Persist complete, bounded day snapshots and preserve untouched dates.

    A day is COMPLETE only when every row can be safely represented. If any
    fixture has invalid identity metadata, the day is kept but marked
    INCOMPLETE; incomplete evidence cannot justify an approval.
    """
    if now.tzinfo is None:
        raise ValueError("UTC clock required")
    if not isinstance(previous, dict) or previous.get("schema_version") != SCHEMA:
        raise ValueError("Invalid API-Football day index schema")
    if not isinstance(previous.get("days"), dict) or not isinstance(caches, dict):
        raise ValueError("Invalid API-Football day index")
    now = now.astimezone(timezone.utc)
    keep = {}
    for day, old in previous["days"].items():
        if not isinstance(day, str) or not isinstance(old, dict):
            raise ValueError("Malformed prior API-Football index")
        try:
            as_day = datetime.fromisoformat(day).date()
        except (TypeError, ValueError):
            raise ValueError("Malformed prior API-Football date") from None
        if 0 <= (now.date() - as_day).days <= MAX_DAYS:
            keep[day] = old
    for day, items in caches.items():
        if not isinstance(day, str):
            raise ValueError("Malformed API-Football cache date")
        try:
            as_day = datetime.fromisoformat(day).date()
        except (TypeError, ValueError):
            raise ValueError("Malformed API-Football cache date") from None
        if not 0 <= (now.date() - as_day).days <= MAX_DAYS:
            continue
        if not isinstance(items, list):  # a failed request never replaces evidence
            continue
        fixtures, seen = [], set()
        valid = len(items) <= MAX_FIXTURES_PER_DAY
        if valid:
            for event in items:
                row = _read_event(event, day)
                if row is None or row["fixture_id"] in seen:
                    valid = False
                    break
                seen.add(row["fixture_id"])
                fixtures.append(row)
        digest = day_fingerprint("api_football", items) if valid else None
        if digest is None:
            valid = False
        keep[day] = {
            "status": "COMPLETE" if valid else "INCOMPLETE",
            "provider": "api_football",
            "fetched_at": now.isoformat(timespec="seconds"),
            "total_fixtures": len(items),
            "fingerprint": digest if valid else None,
            "fixtures": sorted(fixtures, key=lambda x: x["fixture_id"]) if valid else [],
        }
    return {"schema_version": SCHEMA, "days": dict(sorted(keep.items())[-MAX_DAYS:])}


def fixture_index(day_index, day):
    """Return complete day fixtures, or None; never treat unknown as empty."""
    if not isinstance(day_index, dict) or day_index.get("schema_version") != SCHEMA:
        return None
    days = day_index.get("days")
    row = days.get(day) if isinstance(days, dict) else None
    if (not isinstance(row, dict) or row.get("provider") != "api_football"
            or row.get("status") != "COMPLETE"
            or type(row.get("total_fixtures")) is not int
            or not isinstance(row.get("fingerprint"), str)
            or len(row["fingerprint"]) != 64
            or not isinstance(row.get("fixtures"), list)
            or len(row["fixtures"]) != row["total_fixtures"]):
        return None
    return row["fixtures"]


def check_day_identity(day_index, approved):
    """One reviewed fixture must be unique and neither side can play twice ±90m."""
    from .lab_results import utc
    ko = utc(approved.get("provider_kickoff_utc"))
    if ko is None:
        return "DAY_IDENTITY_INVALID_KICKOFF"
    fixtures = fixture_index(day_index, ko.date().isoformat())
    if fixtures is None:
        return "DAY_IDENTITY_COMPLETE_LIST_MISSING"
    fixture_id = approved.get("provider_fixture_id")
    matches = [f for f in fixtures if f["fixture_id"] == fixture_id]
    if len(matches) != 1:
        return "DAY_IDENTITY_FIXTURE_ABSENT_OR_DUPLICATE"
    source = matches[0]
    if (source["home_team_id"] != approved.get("provider_home_team_id")
            or source["away_team_id"] != approved.get("provider_away_team_id")
            or source["competition_id"] != approved.get("provider_competition_id")
            or utc(source["kickoff_utc"]) != ko):
        return "DAY_IDENTITY_APPROVAL_DIFFERS_FROM_COMPLETE_LIST"
    ids = {source["home_team_id"], source["away_team_id"]}
    for other in fixtures:
        if other["fixture_id"] == fixture_id:
            continue
        other_ko = utc(other["kickoff_utc"])
        if (other_ko is not None and abs(other_ko - ko) <= timedelta(minutes=90)
                and ids & {other["home_team_id"], other["away_team_id"]}):
            return "DAY_IDENTITY_TEAM_COLLISION"
    return None
