"""LAB-only FotMob daily-result adapter.

The public FotMob listing is an unofficial endpoint: few bounded requests,
no credentials or bypasses. Only unambiguous ordered fixtures with a provider
label explicitly saying FT and integer 90-minute scores are accepted.
Penalties/AET, conflicts and partial source data remain unresolved.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .lab_identity import CORE, EXACT, IDENTITY_VERSION, core_tokens, pair_level, select_event

API = "https://www.fotmob.com/api/data/"
MAX_DAYS = 3
MAX_BYTES = 10_000_000
WINDOW = 90 * 60
FINAL = {"FT", "FULL TIME", "FULL-TIME"}
SCORE = re.compile(r"^\s*([0-9]{1,2})\s*-\s*([0-9]{1,2})\s*$")


def _utc(text):
    if not isinstance(text, str):
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else None


def fetch_day(day):
    if not re.fullmatch(r"[0-9]{8}", day):
        raise ValueError("invalid day")
    url = API + "matches?date=" + day
    req = Request(url, headers={"Accept": "application/json",
                  "User-Agent": "AsianOdds-LAB-FT/1.0"})
    try:
        with urlopen(req, timeout=16) as resp:
            if resp.status != 200:
                raise OSError("unexpected_http")
            raw = resp.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("oversized response")
            data = json.loads(raw)
    except (HTTPError, URLError, OSError, ValueError, TimeoutError):
        raise OSError("FotMob source unavailable") from None
    if not isinstance(data, dict) or not isinstance(data.get("leagues"), list):
        raise ValueError("invalid FotMob structure")
    if len(data["leagues"]) > 800:
        raise ValueError("unbounded FotMob leagues")
    games = []
    for league in data["leagues"]:
        if not isinstance(league, dict) or not isinstance(league.get("matches"), list):
            raise ValueError("invalid FotMob competition")
        for match in league["matches"]:
            if not isinstance(match, dict):
                raise ValueError("invalid FotMob fixture")
            games.append(match)
            if len(games) > 10000:
                raise ValueError("unbounded FotMob fixtures")
    return games


def _name(ev, key):
    side = ev.get(key)
    return side.get("name", "") if isinstance(side, dict) else ""


def _when(ev):
    status = ev.get("status")
    return _utc(status.get("utcTime")) if isinstance(status, dict) else None


def _same_club(a, b):
    ta, tb = core_tokens(a), core_tokens(b)
    return bool(ta) and ta == tb


def safe_candidate(signal, events):
    """Match by full ordered pair, and refuse exact-alias and club collisions."""
    chosen, level, reason = select_event(signal, events,
        lambda x: (_name(x, "home"), _name(x, "away")), _when)
    if chosen is None:
        return None, None, "fotmob_" + reason
    kickoff = _utc(signal.get("kickoff_utc"))
    if kickoff is None:
        return None, None, "fotmob_invalid_kickoff"
    # select_event returns immediately for an exact match. Enforce collision
    # checks for exact AND core names, including reverse orientation.
    for ev in events:
        when = _when(ev)
        if when is None or abs((when-kickoff).total_seconds()) > WINDOW:
            continue
        home, away = _name(ev,"home"), _name(ev,"away")
        if pair_level(signal["home"],signal["away"],away,home):
            return None, None, "fotmob_reversed_order_candidate"
        if ev is chosen:
            continue
        if (pair_level(signal["home"],signal["away"],home,away)
            or _same_club(signal["home"],home)
            or _same_club(signal["home"],away)
            or _same_club(signal["away"],home)
            or _same_club(signal["away"],away)):
            return None, None, "fotmob_ambiguous_club_or_fixture"
    return chosen, level, "fotmob_identity_" + level.lower()


def final_result(signal, match, level):
    if not isinstance(match, dict) or level not in (EXACT,CORE):
        return None, "fotmob_invalid_candidate"
    status = match.get("status")
    home, away = match.get("home"), match.get("away")
    if not all(isinstance(v,dict) for v in (status,home,away)):
        return None, "fotmob_invalid_fields"
    kickoff = _utc(signal.get("kickoff_utc"))
    when = _when(match)
    if kickoff is None or when is None or abs((kickoff-when).total_seconds()) > WINDOW:
        return None, "fotmob_invalid_kickoff"
    if pair_level(signal.get("home"),signal.get("away"),_name(match,"home"),_name(match,"away")) is None:
        return None, "fotmob_identity_mismatch"
    if (status.get("finished") is not True or status.get("cancelled") is True
        or status.get("started") is not True):
        return None, "fotmob_not_final"
    reason = status.get("reason")
    label = reason.get("short") if isinstance(reason,dict) else None
    # "Pen" and "AET" may display final scores, not regulation scores.
    if not isinstance(label,str) or label.strip().upper() not in FINAL:
        return None, "fotmob_regulation_unverified"
    h,a = home.get("score"),away.get("score")
    if not all(type(v) is int and 0<=v<=99 for v in (h,a)):
        return None, "fotmob_invalid_score"
    score_str = status.get("scoreStr")
    if score_str is not None:
        parsed = SCORE.fullmatch(score_str) if isinstance(score_str,str) else None
        if parsed is None or (int(parsed[1]),int(parsed[2]))!=(h,a):
            return None, "fotmob_score_conflict"
    ids = [match.get("id"),home.get("id"),away.get("id")]
    if any(type(x) is not int or x<=0 for x in ids) or ids[1]==ids[2]:
        return None, "fotmob_invalid_event_id"
    return {"match_key":signal["match_key"],"status":"final",
            "home_goals":h,"away_goals":a,
            "source":API+"matchDetails?matchId="+str(ids[0]),
            "identity_match":level,
            "identity_version":IDENTITY_VERSION}, "verified_fotmob_ft"


class FotMobResults:
    def __init__(self, *,fetch=fetch_day,max_days=MAX_DAYS):
        if not isinstance(max_days,int) or not 0<=max_days<=MAX_DAYS:
            raise ValueError("FotMob day budget exceeded")
        self.fetch=fetch
        self.max_days=max_days
        self.days={}
        self.requests=0
        self.reasons=Counter()

    def lookup(self,signal):
        when=_utc(signal.get("kickoff_utc"))
        if when is None:
            return None,"fotmob_invalid_kickoff"
        day=when.strftime("%Y%m%d")
        if day not in self.days:
            if self.requests >= self.max_days:
                return None,"fotmob_day_budget_deferred"
            self.requests+=1
            try:
                rows=self.fetch(day)
                self.days[day]=rows if isinstance(rows,list) else None
            except (OSError,ValueError):
                self.days[day]=None
        rows=self.days[day]
        if rows is None:
            self.reasons["fotmob_unavailable"]+=1
            return None,"fotmob_unavailable"
        candidate,level,why=safe_candidate(signal,rows)
        if candidate is None:
            self.reasons[why]+=1
            return None,why
        result,reason=final_result(signal,candidate,level)
        self.reasons[reason]+=1
        return result,reason

    def summary(self):
        return {"requests":self.requests,"cached_days":len(self.days),
                "verified_in_run":self.reasons["verified_fotmob_ft"],
                "reason_counts":dict(sorted(self.reasons.items()))}
