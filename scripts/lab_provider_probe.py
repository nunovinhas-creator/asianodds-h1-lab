"""One-shot LAB coverage audit. Read-only; NEVER settles or writes scores.

Probe public daily listings only; classify exact/CORE_NAME identities without
automatic aliases. Endpoints are unofficial: failures are expected and logged.
No secrets, browser bypass or personal data involved.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from h1lab.lab_identity import pair_level, core_tokens
from h1lab.results import norm_team


def utc(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def pending_by_day(root=Path("."), now=None):
    now = now or datetime.now(timezone.utc)
    ledger = json.loads((root / "data/lab/ft-ledger.json").read_text(encoding="utf-8"))
    by_day = {}
    for key, row in ledger["matches"].items():
        dt = utc(row.get("kickoff_utc"))
        if (dt is None or dt + timedelta(hours=3) > now
                or row.get("status") == "FINAL"):
            continue
        by_day.setdefault(dt.date().isoformat(), []).append({"match_key": key, **row})
    return by_day


def fetch(url):
    req = Request(url, headers={"Accept": "application/json",
                  "User-Agent": "AsianOdds-LAB-FT-Coverage-Audit/1.0"})
    try:
        with urlopen(req, timeout=16) as resp:
            if resp.status != 200:
                raise OSError("unexpected_http")
            raw = resp.read(10_000_001)
            if len(raw) > 10_000_000:
                raise ValueError("oversize")
            return json.loads(raw), "ok"
    except HTTPError as e:
        return None, f"http_{e.code}"
    except (URLError, OSError, ValueError, TimeoutError):
        return None, "unavailable"


def fotmob_list(data):
    output = []
    if not isinstance(data, dict):
        return output
    for league in data.get("leagues", []):
        if not isinstance(league, dict):
            continue
        for item in league.get("matches", []):
            if not isinstance(item, dict):
                continue
            h, a = item.get("home") or {}, item.get("away") or {}
            status = item.get("status") or {}
            if not isinstance(h, dict) or not isinstance(a, dict) or not isinstance(status, dict):
                continue
            output.append({"id": item.get("id"), "home": h.get("name", ""),
                "away": a.get("name", ""),
                "utc": utc(status.get("utcTime")),
                "status": ("finished" if status.get("finished") else "not_final"),
                "scores": (h.get("score"), a.get("score")),
                "reason": (status.get("reason") or {}).get("short", "")
                          if isinstance(status.get("reason"), dict) else str(status.get("reason") or ""),
                "competition": league.get("name", "")})
    return output


def sofa_list(data):
    output = []
    if not isinstance(data, dict):
        return output
    for ev in data.get("events", []):
        if not isinstance(ev, dict):
            continue
        h, a, st = ev.get("homeTeam") or {}, ev.get("awayTeam") or {}, ev.get("status") or {}
        try:
            dt = datetime.fromtimestamp(ev["startTimestamp"], timezone.utc)
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        if not all(isinstance(z, dict) for z in (h, a, st)):
            continue
        hs, aw = ev.get("homeScore") or {}, ev.get("awayScore") or {}
        output.append({"id": ev.get("id"), "home": h.get("name", ""),
            "away": a.get("name", ""), "utc": dt,
            "status": st.get("type"), "scores": (hs.get("normaltime"), aw.get("normaltime")),
            "current": (hs.get("current"), aw.get("current")),
            "reason": st.get("description", ""),
            "competition": (ev.get("tournament") or {}).get("name", "")})
    return output


def matches_signal(row, source):
    when = source["utc"]
    kickoff = utc(row.get("kickoff_utc"))
    return (when is not None and kickoff is not None
            and abs((kickoff - when).total_seconds()) <= 5400
            and pair_level(row.get("home"), row.get("away"),
                           source.get("home"), source.get("away")) is not None)


def audit_day(provider, day, source, pending):
    matches = 0
    for row in pending:
        candidates = [event for event in source if matches_signal(row, event)]
        reverse = [ev for ev in source
                   if ev.get("utc") and abs((utc(row.get("kickoff_utc"))-ev["utc"]).total_seconds()) <= 5400
                   and pair_level(row["home"],row["away"],ev["away"],ev["home"])]
        if len(candidates) == 1 and not reverse:
            ev = candidates[0]
            collisions = [x for x in source if x is not ev and x.get("utc")
                          and abs((ev["utc"]-x["utc"]).total_seconds()) <= 5400
                          and (core_tokens(x["home"]) in (core_tokens(row["home"]), core_tokens(row["away"]))
                               or core_tokens(x["away"]) in (core_tokens(row["home"]), core_tokens(row["away"])))]
            if collisions:
                print("PROBE_AMBIGUOUS_CLUB", provider, row["match_key"])
                continue
            matches += 1
            print("PROBE_MATCH", provider, day, row["match_key"],
                  repr(row["home"]), repr(row["away"]), "=>",
                  repr(ev["home"]), repr(ev["away"]), "competition",
                  repr(ev["competition"]), "status", ev["status"],
                  "score", ev["scores"], "reason", repr(ev["reason"]),
                  "event_id", ev["id"])
        elif candidates or reverse:
            print("PROBE_AMBIGUOUS", provider, row["match_key"],
                  "candidates",len(candidates),"reversed",len(reverse))
    print("PROBE_DAY", provider, day, "source_fixtures",len(source),
          "unverified_targets",len(pending),"unique_identifications",matches)
    return matches


def main():
    by_day = pending_by_day()
    days = sorted(by_day, key=lambda d: (-len(by_day[d]), d))[:3]
    totals = Counter()
    for day in days:
        for provider, url, parser in (
            ("fotmob", "https://www.fotmob.com/api/data/matches?date="+day.replace("-", ""), fotmob_list),
            ("sofascore", "https://www.sofascore.com/api/v1/sport/football/scheduled-events/"+day, sofa_list),
        ):
            data, status = fetch(url)
            print("PROBE_REQUEST", provider, day, status)
            if data is not None:
                totals[provider] += audit_day(provider, day, parser(data), by_day[day])
    print("PROBE_TOTAL", dict(totals), "dates",days)
    print("PROBE_READ_ONLY_NEVER_SETTLES")
    return 0


if __name__ == "__main__":
    sys.exit(main())
