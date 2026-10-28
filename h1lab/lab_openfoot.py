"""OpenFoot Starter FT lookup for LAB only. Fail closed on ambiguity or ET."""
from __future__ import annotations
import json,re
from collections import Counter
from datetime import datetime,timezone
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from .lab_identity import EXACT,CORE,IDENTITY_VERSION,core_tokens,pair_level,select_event

API="https://openfootapi.com/v1/matches"
MAX_DAYS=2
# Explicit fixture-level pairs evidenced by the authenticated 2026-10-27
# Cupa Romaniei listing. No wildcard/team-level alias is ever applied.
REVIEWED_PAIRS={
  "2026-10-27,95935,1688":(
      "AFC Progresul Spartac '44","FC Petrolul Ploieşti",
      "2026-10-27T15:00:00+00:00",
      "Progresul Spartac","Petrolul Ploiești","comp_cupa_romaniei_ro"),
  "2026-10-27,22207,24472":(
      "FCM Uzina Textila Arad (UTA)","FC SA Botoşani",
      "2026-10-27T17:00:00+00:00",
      "UTA Arad","Botoșani","comp_cupa_romaniei_ro"),
}

def utc(value):
    if not isinstance(value,str):return None
    try:
        t=datetime.fromisoformat(value.replace("Z","+00:00"))
        return t.astimezone(timezone.utc) if t.tzinfo else None
    except ValueError:return None

def names(e):
    h,a=e.get("homeTeam"),e.get("awayTeam")
    return (h.get("name","") if isinstance(h,dict) else "",
            a.get("name","") if isinstance(a,dict) else "")

def fetch(day,key):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",day):raise ValueError("invalid date")
    url=API+"?"+urlencode({"date":day,"status":"finished","limit":100})
    req=Request(url,headers={"Authorization":"Bearer "+key,"Accept":"application/json"})
    try:
        with urlopen(req,timeout=18) as resp:
            if resp.status!=200:raise OSError("unavailable")
            raw=resp.read(4_000_001)
            if len(raw)>4_000_000:raise ValueError("oversize")
            body=json.loads(raw)
    except (HTTPError,URLError,OSError,TimeoutError,ValueError):
        raise OSError("OpenFoot unavailable") from None
    if not isinstance(body,dict) or not isinstance(body.get("data"),list):
        raise ValueError("invalid OpenFoot envelope")
    meta=body.get("meta") or {}
    page=meta.get("pagination") or {}
    rows=body["data"]
    if (not isinstance(page,dict) or page.get("next_cursor") is not None
        or meta.get("total_count")!=len(rows)
        or len(rows)>100 or not all(isinstance(x,dict) for x in rows)
        or (meta.get("access") or {}).get("authenticated") is not True):
        raise ValueError("OpenFoot incomplete page")
    return rows

def candidate(signal,rows):
    chosen,level,reason=select_event(signal,rows,names,
                                      lambda e:utc(e.get("kickoffAt")))
    if chosen is None:return None,None,"openfoot_"+reason
    ko=utc(signal.get("kickoff_utc"))
    if ko is None:return None,None,"openfoot_invalid_kickoff"
    for e in rows:
        when=utc(e.get("kickoffAt"))
        if when is None or abs((ko-when).total_seconds())>5400:continue
        h,a=names(e)
        if pair_level(signal["home"],signal["away"],a,h):
            return None,None,"openfoot_reversed"
        if e is chosen:continue
        if pair_level(signal["home"],signal["away"],h,a):
            return None,None,"openfoot_ambiguous"
        cores={core_tokens(signal["home"]),core_tokens(signal["away"])}
        if core_tokens(h) in cores or core_tokens(a) in cores:
            return None,None,"openfoot_club_collision"
    return chosen,level,"openfoot_identity_"+level.lower()

def verify(signal,e,level):
    if level not in (EXACT,CORE):return None,"openfoot_invalid_identity"
    if e.get("status")!="finished" or e.get("period")!="FT":
        return None,"openfoot_regulation_unknown"
    if e.get("kickoffTimeKnown") is not True:
        return None,"openfoot_kickoff_unknown"
    if any(k in e for k in ("extraTime","extraTimeScore","penalties","penaltyScore","shootout")):
        return None,"openfoot_et_penalties"
    ko,when=utc(signal.get("kickoff_utc")),utc(e.get("kickoffAt"))
    if ko is None or when is None or abs((ko-when).total_seconds())>5400:
        return None,"openfoot_kickoff_mismatch"
    h,a=names(e)
    if pair_level(signal.get("home"),signal.get("away"),h,a) is None:
        return None,"openfoot_identity_mismatch"
    score=e.get("score")
    if not isinstance(score,dict):return None,"openfoot_missing_score"
    hg,ag=score.get("home"),score.get("away")
    if any(type(n) is not int or n<0 or n>99 for n in (hg,ag)):
        return None,"openfoot_invalid_score"
    mid,cid=e.get("id"),e.get("competitionId")
    if (not isinstance(mid,str) or not re.fullmatch(r"match_[a-zA-Z0-9_-]{3,160}",mid)
        or not isinstance(cid,str) or not re.fullmatch(r"comp_[a-z0-9_]{3,100}",cid)):
        return None,"openfoot_invalid_ids"
    return {"match_key":signal["match_key"],"status":"final",
            "home_goals":hg,"away_goals":ag,
            "source":API+"?"+urlencode({"date":when.date().isoformat(),"competition":cid}),
            "identity_match":level,"identity_version":IDENTITY_VERSION}, "verified_openfoot_ft"

class OpenFootResults:
    def __init__(self,key="",*,getter=fetch,max_days=MAX_DAYS,allowed_days=None):
        if type(max_days) is not int or not 0<=max_days<=MAX_DAYS:
            raise ValueError("Unsafe OpenFoot budget")
        self.key=(key or "").strip()
        self.getter=getter
        self.max_days=max_days
        if allowed_days is not None and (len(allowed_days)>max_days or
                any(not isinstance(day,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",day)
                    for day in allowed_days)):
            raise ValueError("Unsafe provider day rotation")
        self.allowed_days = None if allowed_days is None else frozenset(allowed_days)
        self.days={}
        self.requests=0
        self.reasons=Counter()

    def lookup(self,signal):
        if not self.key:return None,"openfoot_not_configured"
        when=utc(signal.get("kickoff_utc"))
        if when is None:return None,"openfoot_invalid_kickoff"
        day=when.date().isoformat()
        if self.allowed_days is not None and day not in self.allowed_days:
            return None,"openfoot_day_rotation_deferred"
        if day not in self.days:
            if self.requests>=self.max_days:
                return None,"openfoot_day_budget_deferred"
            self.requests+=1
            try:self.days[day]=self.getter(day,self.key)
            except (OSError,ValueError):self.days[day]=None
        rows=self.days[day]
        if not isinstance(rows,list):
            return None,"openfoot_unavailable"
        e,level,why=candidate(signal,rows)
        probe=signal
        reviewed=False
        if e is None:
            expected=REVIEWED_PAIRS.get(signal.get("match_key"))
            if (expected is not None and
                signal.get("home")==expected[0] and
                signal.get("away")==expected[1] and
                utc(signal.get("kickoff_utc"))==utc(expected[2])):
                probe=dict(signal,home=expected[3],away=expected[4])
                e,level,why=candidate(probe,rows)
                if e is not None:
                    stamp=utc(e.get("kickoffAt"))
                    if (e.get("competitionId")!=expected[5] or stamp is None
                        or abs((stamp-utc(expected[2])).total_seconds())>300):
                        e=None
                        why="openfoot_reviewed_competition_or_kickoff_mismatch"
                    else:
                        reviewed=True
        if e is None:
            self.reasons[why]+=1
            return None,why
        result,why=verify(probe,e,level)
        if result is not None and reviewed:
            result["identity_match"]="REVIEWED_PAIR"
            why="verified_openfoot_ft_reviewed_pair"
        self.reasons[why]+=1
        return result,why

    def summary(self):
        return {"configured":bool(self.key),"requests":self.requests,
                "cached_days":len(self.days),
                "requested_days":sorted(self.days),
                "rotation_days":sorted(self.allowed_days) if self.allowed_days is not None else [],
                "verified_in_run":self.reasons["verified_openfoot_ft"]+self.reasons["verified_openfoot_ft_reviewed_pair"],
                "reason_counts":dict(sorted(self.reasons.items()))}
