"""GOAL API one-off coverage and schema probe. No raw API responses or secrets logged."""
import json,os,sys
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen
from collections import Counter

ROOT="https://api.goal-api.com/v1"
def fetch(path,key):
    req=Request(ROOT+path,headers={"Authorization":"Bearer "+key,
        "Accept":"application/json","User-Agent":"AsianOdds-LAB-GOAL-Probe/1.0"})
    try:
        with urlopen(req,timeout=18) as res:
            if res.status!=200:raise OSError("status")
            raw=res.read(2_000_001)
            if len(raw)>2_000_000:raise ValueError("large")
            return json.loads(raw),200
    except HTTPError as e:return None,e.code
    except (URLError,OSError,TimeoutError,ValueError):return None,"unavailable"

def main():
    key=os.environ.get("GOAL_API_KEY","").strip()
    if not key:
        print("GOAL_API_SECRET_MISSING")
        return 1
    print("GOAL_API_SECRET_PRESENT")
    for name,path in (("results","/results/date/2026-10-27?limit=100&offset=0"),
                      ("fixtures","/fixtures/date/2026-10-27?limit=100&offset=0")):
        data,status=fetch(path,key)
        print("GOAL_API_HTTP",name,status)
        if not isinstance(data,dict):continue
        rows=data.get("data")
        page=data.get("pagination")
        print("GOAL_API_ENVELOPE",name,"ok",data.get("success"),
            "rows",len(rows) if isinstance(rows,list) else -1,
            "pagination",page)
        if not isinstance(rows,list):continue
        print("GOAL_API_STATUS",name,dict(Counter(str(x.get("matchStatus")) for x in rows if isinstance(x,dict))))
        for m in [r for r in rows if isinstance(r,dict)][:3]:
            print("GOAL_API_FIELDS",name,sorted(m))
            print("GOAL_API_SAMPLE",repr({k:m.get(k) for k in
                ("id","apiId","homeTeamName","awayTeamName","kickoffUtc",
                 "matchStatus","matchPeriod","homeTeamScore","awayTeamScore",
                 "homeTeamFtScore","awayTeamFtScore","homeTeamExtraScore",
                 "awayTeamExtraScore","homeTeamPenaltyScore","awayTeamPenaltyScore",
                 "leagueName","countryName")})[:950])
    print("GOAL_API_PROBE_DONE")
    return 0

if __name__=="__main__":
    sys.exit(main())
