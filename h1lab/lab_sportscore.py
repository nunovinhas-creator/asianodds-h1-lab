"""SportScore public API lookup for LAB research. Explicit attribution required.

Only derived match FT is stored; raw responses and fixture listings never
leave this run. A 200-row date sample is never treated as exhaustive.
"""
from __future__ import annotations
import json
import re
from collections import Counter
from datetime import datetime,timezone
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode,urlparse
from urllib.request import Request,urlopen
from .results import norm_team
from .lab_reviewed_aliases import reviewed_provider_pair

ROOT="https://sportscore.com"
API=ROOT+"/api/v1/"
MAX_REQUESTS=35
MAX_TEAM_SEARCHES=12
NO_ET=re.compile(r"extra.?time|aet|after.extra|penalt|shoot.?out|spot.kick|\bET\b",re.I)
FULL=re.compile(r"\bft\b|full.?time|finish|\bfinal\b",re.I)
CUP=re.compile(r"\bcup\b|\bcupa\b|coppa|coupe|ta[cç]a|pokal|copa|trophy|knockout",re.I)


def _dt(value):
    if not isinstance(value,str):return None
    try:
        t=datetime.fromisoformat(value.replace("Z","+00:00"))
        return t.astimezone(timezone.utc) if t.tzinfo else None
    except ValueError:
        return None


def _str(value):
    return value.strip() if isinstance(value,str) else ""


def _source_url(raw):
    if not isinstance(raw,str) or not raw or len(raw)>400:return None
    if raw.startswith("/") and not raw.startswith("//"):
        raw=ROOT+raw
    parsed=urlparse(raw)
    return raw if parsed.scheme=="https" and parsed.netloc=="sportscore.com" else None


def teams_match(signal, match):
    """Only exact names or a specific reviewed game; never generic fuzzy matching."""
    if not isinstance(match, dict):
        return False
    home, away = norm_team(_str(match.get("home"))), norm_team(_str(match.get("away")))
    if home == norm_team(signal.get("home")) and away == norm_team(signal.get("away")):
        return True
    pair = reviewed_provider_pair(signal)
    return pair is not None and home == norm_team(pair[0]) and away == norm_team(pair[1])


def is_reviewed_alias(signal, match):
    return teams_match(signal, match) and (
        norm_team(_str(match.get("home"))) != norm_team(signal.get("home")) or
        norm_team(_str(match.get("away"))) != norm_team(signal.get("away")))


def verified(signal,match,competition=""):
    if not isinstance(match,dict):return None,"invalid_match"
    if not teams_match(signal,match):
        return None,"team_identity_mismatch"
    kickoff,when=_dt(signal.get("kickoff_utc")),_dt(match.get("time"))
    if not kickoff or not when or abs((kickoff-when).total_seconds())>5400:
        return None,"kickoff_mismatch"
    if match.get("status")!="finished":
        return None,"not_finished"
    status=_str(match.get("status_text"))
    if not status or NO_ET.search(status):
        return None,"et_or_period_unverified"
    if not FULL.search(status):
        return None,"normal_time_unverified"
    # Cup games need an explicit FT label, not merely a generic finished
    # state, because final score may include extra-time goals.
    if CUP.search(competition) and not re.search(r"\bft\b|full.?time",status,re.I):
        return None,"cup_regulation_unverified"
    h,a=match.get("home_score"),match.get("away_score")
    if not (re.fullmatch(r"[0-9]{1,2}",str(h)) and
            re.fullmatch(r"[0-9]{1,2}",str(a)) and type(h) is not bool and type(a) is not bool):
        return None,"invalid_score"
    source=_source_url(match.get("url"))
    if not source:
        return None,"missing_source_url"
    return {"match_key":signal["match_key"],"status":"final",
            "home_goals":int(h),"away_goals":int(a),"source":source},(
                "verified_sportscore_ft_reviewed_alias" if is_reviewed_alias(signal,match)
                else "verified_sportscore_ft")


def fetch(endpoint,params):
    if endpoint not in ("fixtures/","search/"):
        raise ValueError("Unsupported SportScore endpoint")
    url=API+endpoint+"?"+urlencode(params)
    request=Request(url,headers={"Accept":"application/json",
                  "User-Agent":"AsianOdds-LAB-FT-Research/1.0"})
    try:
        with urlopen(request,timeout=20) as response:
            if response.status!=200:
                raise OSError("SportScore unavailable")
            data=json.loads(response.read(2000000))
    except (HTTPError,URLError,OSError,TimeoutError,ValueError):
        raise OSError("SportScore unavailable") from None
    if not isinstance(data,dict):
        raise ValueError("Invalid SportScore response")
    return data


class SportScoreResults:
    def __init__(self,competitions,*,getter=fetch,max_requests=24,max_team_searches=8):
        if not (0<=max_requests<=MAX_REQUESTS and
                0<=max_team_searches<=MAX_TEAM_SEARCHES):
            raise ValueError("Unsafe SportScore budget")
        self.competitions=competitions
        self.getter=getter
        self.max_requests=max_requests
        self.max_team_searches=max_team_searches
        self.requests=0
        self.targeted=0
        self.day_cache={}
        self.team_cache={}
        self.search_cache={}
        self.reasons=Counter()

    def _get(self,endpoint,params):
        if self.requests>=self.max_requests:
            return None
        self.requests+=1
        try:
            return self.getter(endpoint,params)
        except (OSError,ValueError):
            return None

    def _fixtures(self,day,team=None):
        key=(day,team)
        if key in self.day_cache:
            return self.day_cache[key]
        params={"sport":"football","date":day,"status":"finished","limit":200 if team is None else 100}
        if team:params["team"]=team
        response=self._get("fixtures/",params)
        rows=response.get("matches") if isinstance(response,dict) else None
        if isinstance(rows,list) and len(rows)<=200 and all(isinstance(x,dict) for x in rows):
            self.day_cache[key]=rows
        else:
            self.day_cache[key]=None
        return self.day_cache[key]

    def _team_slug(self,name):
        if name in self.search_cache:
            return self.search_cache[name]
        # No guessed slugs: require provider's exact normalized team name.
        if self.targeted>=self.max_team_searches:
            return None
        self.targeted+=1
        response=self._get("search/",{"sport":"football","q":name,"limit":20})
        teams=response.get("teams") if isinstance(response,dict) else None
        matches=[x for x in teams if isinstance(x,dict) and
                 norm_team(_str(x.get("name")))==norm_team(name) and
                 re.fullmatch(r"[a-z0-9-]{2,140}",_str(x.get("slug")))] if isinstance(teams,list) else []
        slug=matches[0]["slug"] if len(matches)==1 else None
        self.search_cache[name]=slug
        return slug

    def lookup(self,signal):
        kickoff=_dt(signal.get("kickoff_utc"))
        if not kickoff:
            return None,"sportscore_invalid_kickoff"
        day=kickoff.date().isoformat()
        rows=self._fixtures(day)
        if rows is None:
            self.reasons["date_unavailable"]+=1
        # Even a transient day-index failure must not block a strictly
        # validated, separately budgeted team-scoped query.
        plausible=self._plausible(signal,rows or [])
        if not plausible and self.targeted<self.max_team_searches:
            slug=self._team_slug(signal["home"])
            if slug:
                targeted_rows=self._fixtures(day,team=slug)
                if targeted_rows is not None:
                    plausible=self._plausible(signal,targeted_rows)
        if len(plausible)!=1:
            reason=("sportscore_unavailable" if rows is None else "sportscore_no_exact_match") if not plausible else "sportscore_ambiguous"
            self.reasons[reason]+=1
            return None,reason
        result,reason=verified(signal,plausible[0],self.competitions.get(signal["match_key"],""))
        self.reasons[reason]+=1
        return result,reason

    @staticmethod
    def _plausible(signal,rows):
        when=_dt(signal.get("kickoff_utc"))
        if not when:return []
        out=[]
        for x in rows:
            timestamp=_dt(x.get("time"))
            if timestamp is None or abs((when-timestamp).total_seconds())>5400:
                continue
            if teams_match(signal,x):
                out.append(x)
        return out

    def summary(self):
        return {"requests":self.requests,"targeted_searches":self.targeted,
                "cached_date_team_queries":len(self.day_cache),
                "confirmed_in_run":(self.reasons["verified_sportscore_ft"]+
                                    self.reasons["verified_sportscore_ft_reviewed_alias"]),
                "reviewed_alias_ft_in_run":self.reasons["verified_sportscore_ft_reviewed_alias"],
                "reason_counts":dict(sorted(self.reasons.items()))}
