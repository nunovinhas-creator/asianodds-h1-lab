"""Conservative multi-market projections of structured LEGACY observations.
Shadow-only: no picks, no settlements, no cross-line probabilistic comparisons.
Never claim a BTTS price if the source did not supply one.
"""
import math
import hashlib
from datetime import datetime, timezone
from collections import Counter

def finite(v):
    try:
        if isinstance(v,bool): return None
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError): return None

def move(before,after,kind="price"):
    b,a=finite(before),finite(after)
    if kind=="price" and (b is None or a is None or b<=1 or a<=1): return None
    if kind in ("asian_total_line","asian_handicap_line") and (b is None or a is None or abs(b*4-round(b*4))>1e-7 or abs(a*4-round(a*4))>1e-7): return None
    if b is None or a is None: return None
    return {"before":b,"after":a,"delta":round(a-b,6),
            "kind":kind,"direction":"up" if a>b else "down" if a<b else "flat"}

def normalize_alert(a):
    """No reinterpretation of an unknown format as a Total market."""
    market=a.get("market","unknown")
    out={k:a.get(k) for k in ("event_id","match_key","observed_at","kickoff_utc",
                                  "home","away","competition","market")}
    out["parser_version"]=2
    try:
        observed=datetime.fromisoformat(a["observed_at"].replace("Z","+00:00"))
        kickoff=datetime.fromisoformat(a["kickoff_utc"].replace("Z","+00:00"))
        out["pre_kickoff"]=observed < kickoff if observed.tzinfo and kickoff.tzinfo else None
    except (TypeError,ValueError,KeyError,AttributeError): out["pre_kickoff"]=None
    out["total"]=None
    out["one_x_two"]={}
    out["handicap"]=None
    out["btts"]=None  # Absent until real source examples establish the syntax.
    if market in ("total","1x2"):
        line=move(a.get("total_before"),a.get("total_after"),"asian_total_line")
        over=move(a.get("over_before"),a.get("over_after"))
        under=move(a.get("under_before"),a.get("under_after"))
        out["total"]={"line":line,"over_price":over,"under_price":under,
            "cross_line_odds_not_comparable":bool(line["delta"]) if line else None}
    selections=a.get("one_x_two")
    if isinstance(selections,dict):
        for key in ("1","X","2"):
            entry=selections.get(key)
            if isinstance(entry,dict):
                out["one_x_two"][key]=move(entry.get("before"),entry.get("after"))
    ah=a.get("asian_handicap")
    if isinstance(ah,dict) and isinstance(ah.get("before"),dict) and isinstance(ah.get("after"),dict):
        b,n=ah["before"],ah["after"]
        out["handicap"]={"line":move(b.get("line"),n.get("line"),"asian_handicap_line"),
            "home_price":move(b.get("home_odds"),n.get("home_odds")),
            "away_price":move(b.get("away_odds"),n.get("away_odds")),
            "cross_line_odds_not_comparable":None}
        ahline=out["handicap"]["line"]
        out["handicap"]["cross_line_odds_not_comparable"]=bool(ahline["delta"]) if ahline else None
    return out

def summary(alerts,formats):
    """Quality counts, not performance / predictive claims."""
    rows=[normalize_alert(a) for a in alerts if isinstance(a,dict)]
    games={r["match_key"] for r in rows if r["match_key"]}
    recognized=Counter(r["market"] or "unknown" for r in rows)
    post_kickoff=sum(r["pre_kickoff"] is False for r in rows)
    unknown_timing=sum(r["pre_kickoff"] is None for r in rows)
    observations={x.get("event_id"):x for x in formats if isinstance(x,dict) and x.get("event_id")}
    fmt=Counter(x.get("format_id","unknown") for x in observations.values())
    def family(x):
        if x.get("format_family_id"): return x["format_family_id"]
        classes=x.get("line_classes")
        if not isinstance(classes,list): return None
        normalized=["HDR_TOTAL" if k in ("HDR_TOTAL_UP","HDR_TOTAL_DOWN","HDR_TOTAL_OTHER") else k for k in classes]
        return hashlib.sha256("|".join(normalized).encode("utf-8")).hexdigest()[:16]
    families=Counter(f for x in observations.values() if (f:=family(x)) is not None)
    alert_ids={r["event_id"] for r in rows if r.get("event_id")}
    observed_alert_ids=set(observations)&alert_ids
    shapes={}
    other=total_lines=unknown=0
    other_feature_counts=Counter()
    for x in observations.values():
        classes=x.get("line_classes") or []
        other+=sum(v=="OTHER" for v in classes)
        for feature in x.get("other_features",[]):
            if not isinstance(feature,dict): continue
            for key in ("has_percentage","has_arrow","has_red","has_blue","has_colon","starts_emoji"):
                if feature.get(key) is True: other_feature_counts[key]+=1
            other_feature_counts["numbers_"+str(feature.get("numeric_tokens","unknown"))]+=1
        total_lines+=len(classes)
        unknown+=not bool(x.get("legacy_parsed"))
        fid=x.get("format_id","unknown")
        if fid not in shapes: shapes[fid]=classes
    return {"schema_version":2,"status":"descriptive_only","alerts":len(rows),
        "unique_games":len(games),"legacy_markets":dict(sorted(recognized.items())),
        "format_observations":len(observations),"distinct_formats":len(families),"distinct_directional_formats":len(fmt),
        "format_family_counts":dict(families),
        "format_counts":dict(fmt),"format_shapes":shapes,
        "other_lines":other,"observed_lines":total_lines,
        "other_feature_counts":dict(other_feature_counts),
        "other_pct":round(100*other/total_lines,2) if total_lines else None,
        "alerts_with_format":len(observed_alert_ids),
        "format_to_alert_coverage_pct":round(100*len(observed_alert_ids)/len(alert_ids),2) if alert_ids else None,
        "post_kickoff_alerts":post_kickoff,"unknown_kickoff_relation":unknown_timing,
        "legacy_parsed_formats":sum(bool(x.get("legacy_parsed")) for x in observations.values()),
        "unknown_legacy_formats":sum(not x.get("legacy_parsed") for x in observations.values()),
        "coverage_note":"Matched alert IDs with format observations / distinct historical alert IDs. All-message coverage is a separate measure.",
        "limitations":["No BTTS prices verified","Cross-line prices must not be read as probabilities",
          "Telegram reports selected alerts, not all market changes"]}
