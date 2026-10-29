"""Optional, officially documented API-Football v3 FT provider for LAB only.

https://www.api-football.com/documentation_v3
Disabled without the user's own API_FOOTBALL_KEY. Date lookup is cached with
a strict three-day request budget. No 120-minute/penalty scores accepted.
"""
from __future__ import annotations
import json
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .lab_identity import CORE, EXACT, IDENTITY_VERSION, core_tokens, pair_level, select_event

BASE="https://v3.football.api-sports.io/"
MAX_DAYS=3
MAX_BYTES=10_000_000


def _utc(value):
    try:
        dt=datetime.fromisoformat(value.replace("Z","+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (AttributeError,ValueError,TypeError):
        return None


def _time(ev):
    fixture=ev.get("fixture") if isinstance(ev,dict) else None
    if not isinstance(fixture,dict):
        return None
    stamp=fixture.get("timestamp")
    if type(stamp) is int and stamp>0:
        try:
            when=datetime.fromtimestamp(stamp,timezone.utc)
        except (OverflowError,ValueError,OSError):
            return None
        by_string=_utc(fixture.get("date"))
        if by_string is not None and abs((by_string-when).total_seconds())>60:
            return None
        return when
    return _utc(fixture.get("date"))


def _name(ev,side):
    teams=ev.get("teams") if isinstance(ev,dict) else None
    team=teams.get(side) if isinstance(teams,dict) else None
    return team.get("name","") if isinstance(team,dict) else ""


def _same_team(a,b):
    x,y=core_tokens(a),core_tokens(b)
    return bool(x) and x==y


def _unique_identity(signal, rows):
    chosen,level,why=select_event(signal,rows,
        lambda ev:(_name(ev,"home"),_name(ev,"away")),_time)
    if chosen is None:
        return None,None,"api_football_"+why
    ko=_utc(signal.get("kickoff_utc"))
    if ko is None:
        return None,None,"api_football_invalid_kickoff"
    for ev in rows:
        when=_time(ev)
        if when is None or abs((when-ko).total_seconds())>90*60:
            continue
        h,a=_name(ev,"home"),_name(ev,"away")
        if pair_level(signal["home"],signal["away"],a,h):
            return None,None,"api_football_reversed_order"
        if ev is chosen:
            continue
        if (pair_level(signal["home"],signal["away"],h,a) is not None
            or any(_same_team(x,y) for x in (signal["home"],signal["away"])
                   for y in (h,a))):
            return None,None,"api_football_ambiguous_fixture"
    return chosen,level,"api_football_identity_"+level.lower()


def _score(signal,ev,level):
    fixture=ev.get("fixture") or {}
    teams=ev.get("teams") or {}
    if not isinstance(fixture,dict) or not isinstance(teams,dict):
        return None,"api_football_invalid_fixture"
    fstatus=fixture.get("status") or {}
    if not isinstance(fstatus,dict) or fstatus.get("short")!="FT":
        # AET/PEN scores may include extra time; leave them unverified.
        return None,"api_football_regulation_unverified"
    if pair_level(signal.get("home"),signal.get("away"),
                  _name(ev,"home"),_name(ev,"away")) is None:
        return None,"api_football_identity_mismatch"
    when,ko=_time(ev),_utc(signal.get("kickoff_utc"))
    if when is None or ko is None or abs((when-ko).total_seconds())>5400:
        return None,"api_football_kickoff_mismatch"
    home,away=teams.get("home") or {},teams.get("away") or {}
    if not isinstance(home,dict) or not isinstance(away,dict):
        return None,"api_football_invalid_teams"
    id_=fixture.get("id")
    if any(type(x) is not int or x<=0 for x in (id_,home.get("id"),away.get("id"))):
        return None,"api_football_invalid_ids"
    if home["id"]==away["id"]:
        return None,"api_football_identity_collision"
    score=ev.get("score") or {}
    fulltime=score.get("fulltime") if isinstance(score,dict) else None
    goals=ev.get("goals") or {}
    if not isinstance(fulltime,dict) or not isinstance(goals,dict):
        return None,"api_football_missing_regulation_score"
    hs,aw=fulltime.get("home"),fulltime.get("away")
    if (any(type(n) is not int or not 0<=n<=99 for n in (hs,aw,goals.get("home"),goals.get("away")))
        or (hs,aw)!=(goals.get("home"),goals.get("away"))):
        return None,"api_football_score_conflict"
    return {"match_key":signal["match_key"],"status":"final",
            "home_goals":hs,"away_goals":aw,
            "source":BASE+"fixtures?id="+str(id_),
            "identity_match":level,"identity_version":IDENTITY_VERSION}, "verified_api_football_ft"


def fetch_date(day,key):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",day) or not key:
        raise ValueError("invalid API-Football request")
    url=BASE+"fixtures?"+urlencode({"date":day,"timezone":"UTC"})
    req=Request(url,headers={"x-apisports-key":key,"Accept":"application/json",
                             "User-Agent":"AsianOdds-LAB-Research/1.0"})
    try:
        with urlopen(req,timeout=16) as resp:
            if resp.status!=200:
                raise OSError("unavailable")
            raw=resp.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:
                raise ValueError("response oversized")
            data=json.loads(raw)
    except (HTTPError,URLError,OSError,TimeoutError,ValueError):
        raise OSError("API-Football unavailable") from None
    if not isinstance(data,dict) or not isinstance(data.get("response"),list):
        raise ValueError("invalid API-Football response")
    if data.get("errors"):
        raise OSError("API-Football returned an error")
    paging=data.get("paging") or {}
    if not isinstance(paging,dict) or paging.get("total",1)!=1:
        raise ValueError("incomplete API-Football pagination")
    if len(data["response"])>7000 or not all(isinstance(x,dict) for x in data["response"]):
        raise ValueError("invalid API-Football fixtures")
    return data["response"]


def fetch_ids(ids, key):
    """One official fixtures?ids= request, maximum 20 unique reviewed IDs."""
    if (not key or not isinstance(ids, (list, tuple)) or
            not 1 <= len(ids) <= 20 or
            any(type(x) is not int or x <= 0 for x in ids) or
            len(set(ids)) != len(ids)):
        raise ValueError("Invalid API-Football reviewed ID batch")
    req = Request(BASE + "fixtures?" +
                  urlencode({"ids": "-".join(str(x) for x in ids)}),
                  headers={"x-apisports-key": key, "Accept": "application/json",
                           "User-Agent": "AsianOdds-LAB-Reviewed-FT/1.0"})
    try:
        with urlopen(req, timeout=16) as resp:
            if resp.status != 200:
                raise OSError("API-Football ID request unavailable")
            raw = resp.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("API-Football ID result oversized")
            body = json.loads(raw)
    except (HTTPError, URLError, OSError, TimeoutError, ValueError):
        raise OSError("API-Football ID request unavailable") from None
    if (not isinstance(body, dict) or body.get("errors") or
            not isinstance(body.get("response"), list) or
            len(body["response"]) > len(ids)):
        raise ValueError("Invalid API-Football ID response")
    paging = body.get("paging") or {}
    if not isinstance(paging, dict) or paging.get("total", 1) != 1:
        raise ValueError("Incomplete API-Football ID response")
    rows = {}
    for event in body["response"]:
        fixture = event.get("fixture") if isinstance(event, dict) else None
        event_id = fixture.get("id") if isinstance(fixture, dict) else None
        if (type(event_id) is not int or event_id not in ids or
                event_id in rows):
            raise ValueError("Unrequested or duplicate API-Football fixture ID")
        rows[event_id] = event
    return rows


class APIFootballResults:
    def __init__(self,key="",*,fetch=fetch_date,max_days=MAX_DAYS,allowed_days=None,
                 reviewed_targets=None, id_fetch=fetch_ids):
        if not isinstance(max_days,int) or not 0<=max_days<=MAX_DAYS:
            raise ValueError("invalid API-Football budget")
        self.key=(key or "").strip()
        self.fetch=fetch
        self.max_days=max_days
        if allowed_days is not None and (len(allowed_days)>max_days or
                any(not isinstance(day,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",day)
                    for day in allowed_days)):
            raise ValueError("Unsafe provider day rotation")
        self.allowed_days = None if allowed_days is None else frozenset(allowed_days)
        self.days={}
        self.requests=0
        self.id_requests=0
        self.reviewed_targets=dict(reviewed_targets or {})
        self.reviewed_outcomes = {}  # immutable, score-free per-match API ID diagnostics
        if len(self.reviewed_targets) > 20 or any(
                not isinstance(k, str) or not isinstance(v, dict)
                for k, v in self.reviewed_targets.items()):
            raise ValueError("Unsafe API-Football reviewed targets")
        self.id_fetch=id_fetch
        self.id_cache=None
        self.reasons=Counter()

    def lookup(self,signal):
        if not self.key:
            return None,"api_football_not_configured"
        reviewed = self.reviewed_targets.get(signal.get("match_key"))
        if reviewed is not None:
            key = signal["match_key"]
            def failed(reason):
                self.reviewed_outcomes[key] = reason
                return None, reason
            if self.max_days == 0:
                return failed("api_football_reviewed_id_disabled")
            from .lab_api_football_reviewed import validate_reviewed_result
            if self.id_cache is None:
                if self.requests + self.id_requests >= MAX_DAYS:
                    return failed("api_football_reviewed_id_budget_deferred")
                self.id_requests += 1
                try:
                    self.id_cache = self.id_fetch(
                        sorted(set(v["provider_fixture_id"]
                                   for v in self.reviewed_targets.values())),
                        self.key)
                except (OSError, ValueError, KeyError, TypeError):
                    self.id_cache = {}
                    self.reasons["api_football_reviewed_id_unavailable"] += 1
                    return failed("api_football_reviewed_id_unavailable")
            event = self.id_cache.get(reviewed["provider_fixture_id"])
            if event is None:
                self.reasons["api_football_reviewed_id_missing"] += 1
                return failed("api_football_reviewed_id_missing")
            result, why = validate_reviewed_result(signal, reviewed, event)
            self.reasons[why] += 1
            self.reviewed_outcomes[key] = why
            return result, why
        ko=_utc(signal.get("kickoff_utc"))
        if ko is None:
            return None,"api_football_invalid_kickoff"
        day=ko.date().isoformat()
        if self.allowed_days is not None and day not in self.allowed_days:
            return None,"api_football_day_rotation_deferred"
        if day not in self.days:
            if self.requests>=self.max_days or self.requests+self.id_requests >= MAX_DAYS:
                return None,"api_football_day_budget_deferred"
            self.requests+=1
            try:
                matches=self.fetch(day,self.key)
                self.days[day]=matches if isinstance(matches,list) else None
            except (OSError,ValueError):
                self.days[day]=None
        rows=self.days[day]
        if rows is None:
            self.reasons["api_football_unavailable"]+=1
            return None,"api_football_unavailable"
        ev,level,why=_unique_identity(signal,rows)
        if ev is None:
            self.reasons[why]+=1
            return None,why
        result,reason=_score(signal,ev,level)
        self.reasons[reason]+=1
        return result,reason

    def summary(self):
        return {"configured":bool(self.key),"requests":self.requests + self.id_requests,
                "date_requests":self.requests,"id_requests":self.id_requests,
                "reviewed_targets":len(self.reviewed_targets),
                "reviewed_outcomes":dict(sorted(self.reviewed_outcomes.items())),
                "cached_days":len(self.days),
                "requested_days":sorted(self.days),
                "rotation_days":sorted(self.allowed_days) if self.allowed_days is not None else [],
                "verified_in_run":(self.reasons["verified_api_football_ft"] +
                                   self.reasons["verified_api_football_ft_reviewed_pair"]),
                "reason_counts":dict(sorted(self.reasons.items()))}
