"""Read-only authentication, pagination and FT schema probe for OpenFoot.
No key, token or raw API body is ever written to logs/repository.
"""
import json, os, sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

ROOT="https://openfootapi.com"
def get(path,key):
    req=Request(ROOT+path,headers={"Accept":"application/json",
         "Authorization":"Bearer "+key,"User-Agent":"AsianOdds-LAB-FT-Probe/1.0"})
    try:
        with urlopen(req,timeout=18) as res:
            if res.status!=200:raise OSError("http_unexpected")
            raw=res.read(4_000_001)
            if len(raw)>4_000_000:raise ValueError("oversize")
            return json.loads(raw), 200
    except HTTPError as e:
        return None,e.code
    except (URLError,OSError,TimeoutError,ValueError):
        return None,"unavailable"

def main():
    key=os.environ.get("OPENFOOT_API_KEY","").strip()
    if not key:
        print("OPENFOOT_SECRET_MISSING")
        return 1
    print("OPENFOOT_SECRET_PRESENT_NO_VALUE_LOGGED")
    for name,path in [("day","/v1/matches?date=2026-10-27&status=finished&limit=100"),
                      ("romania","/v1/matches?date=2026-10-27&competition=comp_cupa_romaniei_ro&status=finished&limit=100")]:
        data,code=get(path,key)
        print("OPENFOOT_RESPONSE",name,"http",code)
        if not isinstance(data,dict):
            continue
        items=data.get("data")
        meta=data.get("meta") or {}
        print("OPENFOOT_ENVELOPE",name,
              "data",type(items).__name__,"rows",len(items) if isinstance(items,list) else -1,
              "access_plan",(meta.get("access") or {}).get("plan"),
              "authenticated",(meta.get("access") or {}).get("authenticated"),
              "scope",meta.get("scope"),
              "pagination",meta.get("pagination"),
              "preview_limit",meta.get("preview_limit"),
              "total_count",meta.get("total_count"),
              "count",meta.get("count"))
        if not isinstance(items,list):continue
        print("OPENFOOT_STATES",name,dict(Counter(str(i.get("status")) for i in items if isinstance(i,dict))))
        for ev in [i for i in items if isinstance(i,dict)][:3]:
            print("OPENFOOT_SAMPLE_KEYS",sorted(ev))
            for f in ("score","scores","fullTime","fulltime","result","period","statusDetail","statusReason","homeScore","awayScore","homeGoals","awayGoals","winner","source","sources","license"):
                if f in ev:
                    print("OPENFOOT_SCORE_SCHEMA",f,repr(ev[f])[:500])
            print("OPENFOOT_SAMPLE_MATCH",repr(ev.get("homeTeam")),repr(ev.get("awayTeam")),
                  "status",repr(ev.get("status")),"kickoff",repr(ev.get("kickoffAt")),
                  "competition",repr(ev.get("competitionId")))
    print("OPENFOOT_READ_ONLY_DONE")
    return 0

if __name__=="__main__":
    sys.exit(main())
