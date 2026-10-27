"""Conservative multi-market projections of structured LEGACY observations.
Shadow-only: no picks, no settlements, no cross-line probabilistic comparisons.
Never claim a BTTS price if the source did not supply one.
"""
import math
from collections import Counter

def finite(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError): return None

def move(before,after,kind="price"):
    b,a=finite(before),finite(after)
    if b is None or a is None: return None
    return {"before":b,"after":a,"delta":round(a-b,6),
            "kind":kind,"direction":"up" if a>b else "down" if a<b else "flat"}

def normalize_alert(a):
    """No reinterpretation of an unknown format as a Total market."""
    market=a.get("market","unknown")
    out={k:a.get(k) for k in ("event_id","match_key","observed_at","kickoff_utc",
                                  "home","away","competition","market")}
    out["parser_version"]=2
    out["total"]=None
    out["one_x_two"]={}
    out["handicap"]=None
    out["btts"]=None  # Absent until real source examples establish the syntax.
    if market in ("total","1x2"):
        line=move(a.get("total_before"),a.get("total_after"),"asian_total_line")
        over=move(a.get("over_before"),a.get("over_after"))
        under=move(a.get("under_before"),a.get("under_after"))
        out["total"]={"line":line,"over_price":over,"under_price":under,
            "cross_line_odds_not_comparable":bool(line and line["delta"])}
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
            "away_price":move(b.get("away_odds"),n.get("away_odds"))}
    return out

def summary(alerts,formats):
    """Quality counts, not performance / predictive claims."""
    rows=[normalize_alert(a) for a in alerts if isinstance(a,dict)]
    games={r["match_key"] for r in rows if r["match_key"]}
    recognized=Counter(r["market"] or "unknown" for r in rows)
    observations={x.get("event_id"):x for x in formats if isinstance(x,dict) and x.get("event_id")}
    fmt=Counter(x.get("format_id","unknown") for x in observations.values())
    return {"schema_version":2,"status":"descriptive_only","alerts":len(rows),
        "unique_games":len(games),"legacy_markets":dict(sorted(recognized.items())),
        "format_observations":len(observations),"distinct_formats":len(fmt),
        "format_counts":dict(fmt),
        "legacy_parsed_formats":sum(bool(x.get("legacy_parsed")) for x in observations.values()),
        "unknown_legacy_formats":sum(not x.get("legacy_parsed") for x in observations.values()),
        "coverage_note":"Snapshot formats may cover fewer messages than legacy historical alerts.",
        "limitations":["No BTTS prices verified","Cross-line prices must not be read as probabilities",
          "Telegram reports selected alerts, not all market changes"]}
