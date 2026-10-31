"""GOAL API daily FT recovery for LAB; 90-minute evidence only.

Official REST endpoint /v1/results/date/YYYY-MM-DD. The provider returns
homeTeamFtScore/awayTeamFtScore separately from scores after ET/penalties.
Results are immutable LAB observations; no H1 code or state is touched.
"""
from __future__ import annotations
import json
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from .lab_identity import CORE, EXACT, IDENTITY_VERSION, core_tokens, pair_level, select_event

API="https://api.goal-api.com/v1/results/date/"
MAX_DAYS=2
MAX_ROWS=1500
MAX_BYTES=5_000_000
FINAL={"FINISHED","AFTER_ET","AFTER_PEN"}
NUM=re.compile(r"[0-9]{1,2}")


def _utc(x):
    if not isinstance(x,str):
        return None
    try:
        d=datetime.fromisoformat(x.replace("Z","+00:00"))
    except ValueError:
        return None
    return d.astimezone(timezone.utc) if d.tzinfo else None


def _name(e,side):
    obj=e.get(side) if isinstance(e,dict) else None
    n=obj.get("name") if isinstance(obj,dict) else None
    return n if isinstance(n,str) and n.strip() else e.get(side+"Name","")


def _when(e):
    return _utc(e.get("kickoffUtc")) if isinstance(e,dict) else None


def fetch_date(day,key):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",day) or not key:
        raise ValueError("Invalid GOAL date query")
    req=Request(API+day+"?"+urlencode({"limit":500,"offset":0}),
        headers={"Authorization":"Bearer "+key,"Accept":"application/json",
                 "User-Agent":"AsianOdds-LAB-FT/1.0"})
    try:
        with urlopen(req,timeout=18) as resp:
            if resp.status!=200:
                raise OSError("unavailable")
            raw=resp.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:
                raise ValueError("GOAL response too large")
            body=json.loads(raw)
    except (HTTPError,URLError,OSError,ValueError,TimeoutError):
        raise OSError("GOAL unavailable") from None
    if not isinstance(body,dict) or body.get("success") is not True:
        raise ValueError("GOAL invalid envelope")
    rows=body.get("data")
    page=body.get("pagination")
    if (not isinstance(rows,list) or len(rows)>MAX_ROWS or
        not all(isinstance(ev,dict) for ev in rows)):
        raise ValueError("GOAL invalid result rows")
    if page is None and len(rows) >= 500:
        raise ValueError("GOAL incomplete list: possible silent truncation")
    if page is not None:
        if not isinstance(page,dict) or page.get("hasMore") is not False:
            raise ValueError("GOAL incomplete pagination")
        if type(page.get("total")) is not int or page["total"]!=len(rows):
            raise ValueError("GOAL incomplete count")
    # Results-by-date returned complete lists without pagination in production.
    # Unexpected partial pagination cannot be used for unique matching.
    return rows

def fetch_fixture_by_id(event_id, key):
    """Official GOAL /fixtures/:id; bounded and fail-closed."""
    if not isinstance(event_id, str) or not re.fullmatch(r"[0-9]{3,12}", event_id) or not key:
        raise ValueError("Invalid GOAL fixture id")
    req = Request("https://api.goal-api.com/v1/fixtures/" + event_id,
                  headers={"Authorization": "Bearer " + key,
                           "Accept": "application/json",
                           "User-Agent": "AsianOdds-LAB-FT/1.0"})
    try:
        with urlopen(req, timeout=18) as resp:
            if resp.status != 200:
                raise OSError("GOAL ID unavailable")
            data = resp.read(2_000_001)
            if len(data) > 2_000_000:
                raise ValueError("GOAL ID response too large")
            body = json.loads(data)
    except (HTTPError, URLError, OSError, TimeoutError, ValueError):
        raise OSError("GOAL ID unavailable") from None
    if not isinstance(body, dict) or body.get("success") is not True:
        raise ValueError("Invalid GOAL ID envelope")
    event = body.get("data")
    if not isinstance(event, dict) or str(event.get("apiId", "")) != event_id:
        raise ValueError("GOAL ID response identity mismatch")
    return event


def choose(signal, rows):
    ev,level,reason=select_event(signal, rows,
        lambda x:(_name(x,"homeTeam"),_name(x,"awayTeam")),_when)
    if ev is None:
        return None,None,"goal_"+reason
    when=_utc(signal.get("kickoff_utc"))
    if when is None:
        return None,None,"goal_invalid_kickoff"
    a,b=core_tokens(signal["home"]),core_tokens(signal["away"])
    for x in rows:
        k=_when(x)
        if k is None or abs((k-when).total_seconds())>5400:
            continue
        home,away=_name(x,"homeTeam"),_name(x,"awayTeam")
        if pair_level(signal["home"],signal["away"],away,home):
            return None,None,"goal_reversed_orientation"
        if x is ev:
            continue
        if (pair_level(signal["home"],signal["away"],home,away)
            or ({core_tokens(home),core_tokens(away)} & {a,b})):
            return None,None,"goal_ambiguous_fixture"
    return ev,level,"goal_identity_"+level.lower()


def verify(signal,ev,level):
    if not isinstance(ev,dict) or level not in (EXACT,CORE):
        return None,"goal_invalid_candidate"
    status=ev.get("matchStatus")
    if status not in FINAL or ev.get("matchPeriod")!="FINISHED":
        return None,"goal_not_finished_or_unverified"
    when,ko=_when(ev),_utc(signal.get("kickoff_utc"))
    if when is None or ko is None or abs((ko-when).total_seconds())>5400:
        return None,"goal_kickoff_mismatch"
    if pair_level(signal.get("home"),signal.get("away"),
                  _name(ev,"homeTeam"),_name(ev,"awayTeam")) is None:
        return None,"goal_team_mismatch"
    h,a=ev.get("homeTeamFtScore"),ev.get("awayTeamFtScore")
    if not all(isinstance(x,str) and NUM.fullmatch(x) for x in (h,a)):
        return None,"goal_no_regulation_score"
    hg,ag=int(h),int(a)
    # A normal FT score should equal the displayed score. For AET/PEN the
    # provider explicitly separates 90-min FT from ET/shootout scores.
    if status=="FINISHED":
        disp=(ev.get("homeTeamScore"),ev.get("awayTeamScore"))
        if any(v is not None and str(v)!=str(score)
               for v,score in zip(disp,(hg,ag))):
            return None,"goal_score_conflict"
        if any(ev.get(k) not in (None,"") for k in
               ("homeTeamExtraScore","awayTeamExtraScore",
                "homeTeamPenaltyScore","awayTeamPenaltyScore")):
            return None,"goal_et_status_conflict"
    if status=="AFTER_ET" and not any(ev.get(k) not in (None,"") for k in
                                      ("homeTeamExtraScore","awayTeamExtraScore")):
        return None,"goal_et_evidence_missing"
    if status=="AFTER_PEN" and not all(
        isinstance(ev.get(k),str) and NUM.fullmatch(ev[k]) for k in
        ("homeTeamPenaltyScore","awayTeamPenaltyScore")):
        return None,"goal_penalty_evidence_missing"
    source_id=ev.get("apiId")
    if not isinstance(source_id,str) or not re.fullmatch(r"[0-9]{3,12}",source_id):
        return None,"goal_invalid_id"
    reason=("verified_goal_ft_after_et" if status=="AFTER_ET" else
            "verified_goal_ft_after_pen" if status=="AFTER_PEN" else
            "verified_goal_ft")
    return ({"match_key":signal["match_key"],"status":"final",
             "home_goals":hg,"away_goals":ag,
             "source":"https://api.goal-api.com/v1/fixtures/"+source_id,
             "identity_match":level,"identity_version":IDENTITY_VERSION}, reason)


class GoalResults:
    def __init__(self,key="",*,getter=fetch_date,max_days=MAX_DAYS,allowed_days=None,target_ids=None,id_getter=fetch_fixture_by_id,reviewed_targets=None):
        if type(max_days) is not int or not 0<=max_days<=MAX_DAYS:
            raise ValueError("GOAL day budget exceeded")
        self.key=(key or "").strip()
        self.getter=getter
        self.max_days=max_days
        if allowed_days is not None and (len(allowed_days)>max_days or
                any(not isinstance(day,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",day)
                    for day in allowed_days)):
            raise ValueError("Unsafe provider day rotation")
        self.allowed_days = None if allowed_days is None else frozenset(allowed_days)
        self.cache={}
        self.requests=0
        self.id_requests=0
        self.id_outcomes={}
        self.target_ids=dict(target_ids or {})
        if len(self.target_ids)>1 or any(not isinstance(k,str) or not re.fullmatch(r"[0-9]{3,12}",str(v))
                                         for k,v in self.target_ids.items()):
            raise ValueError("Unsafe GOAL fixture ID targets")
        self.id_getter=id_getter
        self.reviewed_targets=dict(reviewed_targets or {})
        if any(key not in self.target_ids or
               str(value.get("provider_fixture_id", "")) != str(self.target_ids[key])
               for key,value in self.reviewed_targets.items()
               if isinstance(value, dict)):
            raise ValueError("Reviewed GOAL fixture target does not match ID target")
        if any(not isinstance(value, dict) for value in self.reviewed_targets.values()):
            raise ValueError("Invalid reviewed GOAL targets")
        self.reviewed_observations={}
        self.reasons=Counter()
    def lookup(self,signal):
        if not self.key:
            return None,"goal_not_configured"
        ko=_utc(signal.get("kickoff_utc"))
        if ko is None:
            return None,"goal_invalid_kickoff"
        target = self.target_ids.get(signal.get("match_key"))
        if target is not None:
            if self.id_requests >= 1:
                return None,"goal_id_budget_deferred"
            # This one ID call replaces one of two date calls, never adds a third.
            if self.requests + self.id_requests >= MAX_DAYS:
                return None,"goal_id_budget_deferred"
            self.id_requests += 1
            try:
                event = self.id_getter(str(target), self.key)
            except (OSError, ValueError):
                self.id_outcomes[signal["match_key"]] = "goal_id_unavailable"
                self.reasons["goal_id_unavailable"] += 1
                return None,"goal_id_unavailable"
            if not isinstance(event,dict) or str(event.get("apiId","")) != str(target):
                self.id_outcomes[signal["match_key"]] = "goal_id_mismatch"
                self.reasons["goal_id_mismatch"] += 1
                return None,"goal_id_mismatch"
            reviewed = self.reviewed_targets.get(signal.get("match_key"))
            if reviewed is not None:
                from .lab_goal_reviewed import verify_reviewed_goal
                result, why, observation = verify_reviewed_goal(signal, event, reviewed)
                if observation is not None:
                    # Only normalized regulation-score evidence is retained;
                    # this path NEVER changes PENDING into FINAL.
                    self.reviewed_observations[signal["match_key"]] = observation
                self.id_outcomes[signal["match_key"]] = why
                self.reasons[why] += 1
                return result, why
            # A fixture ID is a locator. Re-apply the strict, public 90m
            # verifier after selecting exactly the matching team pair.
            chosen,level,why=choose(signal,[event])
            if chosen is None:
                self.id_outcomes[signal["match_key"]] = "goal_id_" + why
                self.reasons["goal_id_"+why] += 1
                return None,"goal_id_"+why
            result,reason=verify(signal,chosen,level)
            self.id_outcomes[signal["match_key"]] = reason
            self.reasons[reason]+=1
            return result,reason

        day=ko.date().isoformat()
        if self.allowed_days is not None and day not in self.allowed_days:
            return None,"goal_day_rotation_deferred"
        if day not in self.cache:
            if self.requests>=self.max_days:
                return None,"goal_day_budget_deferred"
            self.requests+=1
            try:
                self.cache[day]=self.getter(day,self.key)
            except (OSError,ValueError):
                self.cache[day]=None
        rows=self.cache[day]
        if not isinstance(rows,list):
            return None,"goal_unavailable"
        ev,level,why=choose(signal,rows)
        if ev is None:
            self.reasons[why]+=1
            return None,why
        result,why=verify(signal,ev,level)
        self.reasons[why]+=1
        return result,why
    def summary(self):
        return {"configured":bool(self.key),"requests":self.requests+self.id_requests,
                "date_requests":self.requests,"id_requests":self.id_requests,
                "cached_days":len(self.cache),
                "requested_days":sorted(self.cache),
                "rotation_days":sorted(self.allowed_days) if self.allowed_days is not None else [],
                "verified_in_run":sum(n for k,n in self.reasons.items()
                                      if k.startswith("verified_goal_ft")),
                "reason_counts":dict(sorted(self.reasons.items())),
                "id_outcomes":dict(sorted(self.id_outcomes.items()))}
