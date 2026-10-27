"""Independent exploratory market intelligence. Never produces H1 picks or tickets."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from math import isfinite

FIELDS=("total_before","total_after","over_before","over_after","under_before","under_after")
def number(value):
    try:
        v=float(value)
        return v if isfinite(v) else None
    except (TypeError,ValueError):
        return None

def movement(before,after):
    a,b=number(before),number(after)
    if a is None or b is None: return None
    delta=round(b-a,6)
    return {"before":a,"after":b,"delta":delta,
            "direction":"up" if delta>1e-8 else "down" if delta< -1e-8 else "flat"}

def project(alert):
    """Only fields parsed and already recorded by the legacy collector."""
    obj={k:alert.get(k) for k in ("event_id","match_key","home","away",
        "competition","observed_at","kickoff_utc","market","source_url")}
    obj["total_line"]=movement(alert.get("total_before"),alert.get("total_after"))
    obj["over_price"]=movement(alert.get("over_before"),alert.get("over_after"))
    obj["under_price"]=movement(alert.get("under_before"),alert.get("under_after"))
    obj["one_x_two"]={k:movement(v.get("before"),v.get("after"))
        for k,v in alert.get("one_x_two",{}).items() if isinstance(v,dict)}
    ah=alert.get("asian_handicap") or {}
    before,after=ah.get("before") or {},ah.get("after") or {}
    obj["asian_handicap"]={k:movement(before.get(k),after.get(k))
        for k in ("line","home_odds","away_odds")}
    return obj

def build(state,results=None):
    """Descriptive counts; settled outcomes never used as predictive evidence."""
    alerts=[project(a) for a in state.get("alerts",[]) if isinstance(a,dict)]
    seen=set()
    unique=[]
    for a in sorted(alerts,key=lambda x:(x.get("observed_at") or "",x.get("event_id") or "")):
        if not a.get("event_id") or a["event_id"] in seen: continue
        seen.add(a["event_id"])
        unique.append(a)
    games=defaultdict(list)
    for a in unique:
        if a.get("match_key"): games[a["match_key"]].append(a)
    movement_counts=Counter()
    market_counts=Counter()
    for a in unique:
        market_counts[a.get("market") or "unknown"]+=1
        for field in ("total_line","over_price","under_price"):
            if a[field] is not None: movement_counts[field+":"+a[field]["direction"]]+=1
        for k,v in a["one_x_two"].items():
            if v is not None: movement_counts["1x2_"+k+":"+v["direction"]]+=1
        for k,v in a["asian_handicap"].items():
            if v is not None: movement_counts["ah_"+k+":"+v["direction"]]+=1
    confirmed=results or {}
    outcomes=[]
    for key,events in games.items():
        r=confirmed.get(key)
        if not r: continue
        h,a=number(r.get("home_goals")),number(r.get("away_goals"))
        if h is None or a is None or h<0 or a<0 or not h.is_integer() or not a.is_integer(): continue
        total=int(h+a)
        outcomes.append({"match_key":key,"goals":total,"over_2_5":total>2,
            "btts":h>0 and a>0,"result":"1" if h>a else "2" if h<a else "X",
            "alert_count":len(events)})
    return {"schema_version":1,"generated_at":datetime.now(timezone.utc).isoformat(),
        "status":"exploratory_only_no_predictive_claim",
        "coverage":{"unique_alerts":len(unique),"unique_matches":len(games),
            "matches_with_confirmed_ft":len(outcomes),"markets":dict(sorted(market_counts.items()))},
        "movement_counts":dict(sorted(movement_counts.items())),
        "events":unique,"outcomes":outcomes,
        "limitations":["Telegram contains selected alerts, not the full market.",
          "Legacy parser does not normalize every Telegram market or BTTS odds.",
          "Was/Now is not a continuous price history.",
          "Outcomes and movements are exploratory; no tested edge or ROI inferred."]}
