"""MASTER BRAIN V6.2: weekly, observation-only market/calibration/format drift.

Weekly ISO 8601 UTC snapshots. A calibration row is a genuinely pre-kickoff,
post-registration frozen probability with a later VERIFIED FT score. One row
per match, not per alert. Source quality is computed at real known_at. Format
profiles are by Telegram message date, explicitly NOT ingestion timestamps.

Thresholds are fixed BEFORE observing adequate OOS samples. "SUSPECTED"
requires review; insufficient sample is never a PASS, or proof of no drift.
This module does not approve hypotheses, generate bets, notify, or call APIs.
"""
from __future__ import annotations
from .lab_archive import monthly_paths

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .v6_shadow import read_journal, utc, canonical
from .v6_ft_events import read_events as read_ft_events
from .v6_hypotheses import ensure_registered

VERSION = 1
STATUS = "V6_WEEKLY_DRIFT_MONITOR_SHADOW"
MAX_WEEKS = 12
MIN_QUALITY_N = 50
MIN_FORMAT_N = 30
MIN_MARKET_N = 50
MIN_CALIBRATION_N = 30
MIN_CALIBRATION_COMPARISON_N = 100
QUALITY_DELTA_WATCH = 0.15
FORMAT_JS_WATCH = 0.12  # bits, not a hypothesis-test p-value
NEW_FORMAT_FAMILY_SHARE_WATCH = 0.20
MARKET_PSI_WATCH = 0.25
CALIBRATION_BRIER_DETERIORATION_WATCH = 0.05
BINS_P = (0.2, 0.4, 0.6, 0.8)
EPS = 1e-6


def digest(obj):
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def date_week(value):
    if value.tzinfo is None:
        raise ValueError("Weekly monitor requires timezone-aware date")
    iso = value.astimezone(timezone.utc).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def week_begin(value):
    dt = value.astimezone(timezone.utc)
    day = dt.date() - timedelta(days=dt.weekday())
    return day.isoformat()


def bucket(value, cuts):
    return sum(value >= cut for cut in cuts)


def r(value):
    return round(value, 6) if value is not None else None


def proportions(counts, names):
    total=sum(counts.get(k,0) for k in names)
    return {k:counts.get(k,0)/total if total else 0.0 for k in names}


def psi(a,b,keys):
    """Population stability index (natural-log, smoothed proportions)."""
    p=proportions(a,keys);q=proportions(b,keys)
    return sum((p[k]-q[k])*math.log((p[k]+EPS)/(q[k]+EPS)) for k in keys)


def jensen_shannon(a,b):
    keys=sorted(set(a)|set(b))
    p=proportions(a,keys);q=proportions(b,keys)
    def kl(x,m):
        return sum(v*math.log2(v/m[k]) for k,v in x.items() if v)
    mid={k:(p[k]+q[k])/2 for k in keys}
    return (kl(p,mid)+kl(q,mid))/2


def format_family(row):
    # V4's pre-existing family field takes precedence. Otherwise normalize
    # directional header variations into the same family without using FT.
    if row.get("format_family_id"):
        return str(row["format_family_id"])
    classes=row.get("line_classes") or ()
    mapped=[("HDR_TOTAL" if str(x).startswith("HDR_TOTAL") else str(x))
            for x in classes]
    return hashlib.sha256("|".join(mapped).encode()).hexdigest()[:16]


def load_formats(root):
    records={}
    for path in monthly_paths(root, "formats"):
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                raise ValueError("Blank Telegram format observation")
            row=json.loads(raw)
            if row.get("event_id") and row.get("observed_at"):
                # Source format journal can be a latest projection: only one
                # entry per Telegram event, not per repeated processing run.
                records[row["event_id"]]=row
    return list(records.values())


def latest_before(records, cutoff):
    latest={}
    for row in records:
        when=utc(row.get("known_at"))
        ko=utc(row.get("kickoff_utc"))
        if when is None or ko is None or not when < ko or when > cutoff:
            continue
        key=row["match_key"]
        if key not in latest or (row["known_at"],row["event_id"]) > (
                latest[key]["known_at"],latest[key]["event_id"]):
            latest[key]=row
    return latest


def verified_ft(events, as_of):
    latest={}
    for e in events:
        written=utc(e.get("recorded_at"))
        if written is not None and written <= as_of:
            latest[e["match_key"]]=e
    return latest


def week_summary(key, current, market_rows, format_rows, scored):
    quality=Counter(("USABLE" if (x.get("price_quality") or {}).get("status")=="USABLE"
                      else "UNUSABLE") for x in market_rows)
    flags=Counter(flag for x in market_rows
                  for flag in set((x.get("price_quality") or {}).get("flags") or []))
    clean=[x["market_probability_over_2_5"] for x in market_rows
           if (x.get("price_quality") or {}).get("status")=="USABLE"
           and isinstance(x.get("market_probability_over_2_5"),(int,float))
           and not isinstance(x["market_probability_over_2_5"],bool)
           and math.isfinite(x["market_probability_over_2_5"])
           and 0 < x["market_probability_over_2_5"] < 1]
    p_count=Counter(str(bucket(p,BINS_P)) for p in clean)
    lines=[(x.get("price_quality") or {}).get("after") or {} for x in market_rows]
    lines=[x["line"] for x in lines if isinstance(x.get("line"),(int,float))
           and not isinstance(x["line"],bool) and math.isfinite(x["line"])]
    line_count=Counter(str(bucket(x,(2.25,2.75,3.25))) for x in lines)
    families=Counter(format_family(x) for x in format_rows)
    fmt_unknown=sum(not x.get("legacy_parsed") for x in format_rows)
    calibration_n=len(scored)
    bins=defaultdict(list)
    for p,y in scored:
        bins[str(bucket(p,BINS_P))].append((p,y))
    details=[{"bin":str(i),"n":len(bins[str(i)]),
              "predicted_mean":r(sum(p for p,y in bins[str(i)])/len(bins[str(i)])) if bins[str(i)] else None,
              "observed_rate":r(sum(y for p,y in bins[str(i)])/len(bins[str(i)])) if bins[str(i)] else None}
             for i in range(5)]
    brier=r(sum((p-y)**2 for p,y in scored)/calibration_n) if calibration_n else None
    ece=r(sum(len(v)/calibration_n*abs(sum(p for p,y in v)/len(v)-sum(y for p,y in v)/len(v))
              for v in bins.values() if v)) if calibration_n else None
    n=len(market_rows)
    return {
        "week":key,"period":"CURRENT_INCOMPLETE" if current else "COMPLETED",
        "quality":{
            "n":n,"usable":quality["USABLE"],"unusable":quality["UNUSABLE"],
            "unusable_rate":r(quality["UNUSABLE"]/n) if n else None,
            "flags":dict(sorted(flags.items())),
            "basis":"Latest prospectively known snapshot per match within observation week"},
        "market":{
            "n":len(clean),"p_mean":r(sum(clean)/len(clean)) if clean else None,
            "probability_bins":{str(i):p_count[str(i)] for i in range(5)},
            "line_n":len(lines),"line_bins":{str(i):line_count[str(i)] for i in range(4)},
            "basis":"Model-derived market P(Over 2.5); NOT tradable O2.5 odds"},
        "formats":{
            "n":len(format_rows),"family_counts":dict(sorted(families.items())),
            "distinct_families":len(families),"legacy_unparsed":fmt_unknown,
            "unknown_share":r(fmt_unknown/len(format_rows)) if format_rows else None,
            "basis":"Telegram message timestamps, not guaranteed collector reception times"},
        "calibration":{
            "n":calibration_n,"brier_score":brier,"ece_5bins_descriptive":ece,
            "mean_reference_p":r(sum(p for p,y in scored)/calibration_n) if scored else None,
            "observed_rate":r(sum(y for p,y in scored)/calibration_n) if scored else None,
            "bins":details,"status":"DESCRIPTIVE_MIN_N_REACHED" if calibration_n>=MIN_CALIBRATION_N else "INSUFFICIENT_N",
            "basis":"Post-registration, pre-kickoff frozen reference + verified FT; no H1 picks"},
    }


def _decision(status, n1, n2, value=None, threshold=None, detail=None):
    return {"status":status,"reference_n":n1,"comparison_n":n2,
            "value":r(value),"review_threshold":threshold,
            "detail":detail or ""}


def comparisons(ref, current):
    """Only two *completed* weeks ever reach a drift decision."""
    if ref is None or current is None:
        return {"quality":_decision("INSUFFICIENT_HISTORY",0,0),
                "formats":_decision("INSUFFICIENT_HISTORY",0,0),
                "market":_decision("INSUFFICIENT_HISTORY",0,0),
                "calibration":_decision("INSUFFICIENT_HISTORY",0,0)}
    q1,q2=ref["quality"],current["quality"]
    f1,f2=ref["formats"],current["formats"]
    m1,m2=ref["market"],current["market"]
    c1,c2=ref["calibration"],current["calibration"]
    quality_change=(q2["unusable_rate"]-q1["unusable_rate"]
                    if q1["unusable_rate"] is not None and q2["unusable_rate"] is not None
                    else None)
    quality=_decision(
        "INSUFFICIENT_N" if min(q1["n"],q2["n"])<MIN_QUALITY_N else
        "SUSPECTED_DRIFT_REVIEW" if abs(quality_change)>=QUALITY_DELTA_WATCH else "NO_THRESHOLD_CROSSED",
        q1["n"],q2["n"],quality_change,QUALITY_DELTA_WATCH,
        "Change in unusable market snapshot share, percentage points on 0–1 scale")
    js=jensen_shannon(f1["family_counts"],f2["family_counts"]) if min(f1["n"],f2["n"]) else None
    previously=set(f1["family_counts"])
    new_share=sum(v for k,v in f2["family_counts"].items() if k not in previously)/f2["n"] if f2["n"] else None
    fmt=_decision(
        "INSUFFICIENT_N" if min(f1["n"],f2["n"])<MIN_FORMAT_N else
        "SUSPECTED_DRIFT_REVIEW" if js>=FORMAT_JS_WATCH or new_share>=NEW_FORMAT_FAMILY_SHARE_WATCH
        else "NO_THRESHOLD_CROSSED",
        f1["n"],f2["n"],js,FORMAT_JS_WATCH,
        "Jensen-Shannon divergence (bits) in normalized Telegram message-format families")
    fmt["new_family_share"]=r(new_share)
    fmt["new_family_share_threshold"]=NEW_FORMAT_FAMILY_SHARE_WATCH
    market_psi=psi(m2["probability_bins"],m1["probability_bins"],[str(i) for i in range(5)]) if m1["n"] and m2["n"] else None
    market=_decision(
        "INSUFFICIENT_N" if min(m1["n"],m2["n"])<MIN_MARKET_N else
        "SUSPECTED_DRIFT_REVIEW" if market_psi>=MARKET_PSI_WATCH else "NO_THRESHOLD_CROSSED",
        m1["n"],m2["n"],market_psi,MARKET_PSI_WATCH,
        "Population stability index of model-derived market reference P(Over 2.5)")
    d=(c2["brier_score"]-c1["brier_score"]) if c1["brier_score"] is not None and c2["brier_score"] is not None else None
    calib=_decision(
        "INSUFFICIENT_N" if min(c1["n"],c2["n"])<MIN_CALIBRATION_COMPARISON_N else
        "SUSPECTED_DRIFT_REVIEW" if d >= CALIBRATION_BRIER_DETERIORATION_WATCH else "NO_THRESHOLD_CROSSED",
        c1["n"],c2["n"],d,CALIBRATION_BRIER_DETERIORATION_WATCH,
        "Higher Brier is worse. Descriptive comparison; no statistical significance claim")
    return {"quality":quality,"formats":fmt,"market":market,"calibration":calib}


def analyze(forecasts, ft_events, formats, registration, *, now):
    if now.tzinfo is None:
        raise ValueError("Aware clock required")
    now=now.astimezone(timezone.utc)
    current=date_week(now)
    # Quality and market by actual first collector known_at. Distinct games per
    # week: last forecast of that week; do not count every alert as a new game.
    bucketed=defaultdict(dict)
    for row in forecasts:
        known=utc(row.get("known_at"))
        ko=utc(row.get("kickoff_utc"))
        if not known or not ko or not known < ko or known>now:
            continue
        week=date_week(known)
        old=bucketed[week].get(row["match_key"])
        if old is None or (row["known_at"],row["event_id"])>(old["known_at"],old["event_id"]):
            bucketed[week][row["match_key"]]=row
    # FT calibration by KO week, only last truly pre-kickoff frozen snapshot,
    # and only if registered BEFORE known_at and FT reviewed AFTER kickoff.
    full=latest_before(forecasts,now)
    ft=verified_ft(ft_events,now)
    calib=defaultdict(list)
    eligible=Counter()
    registered=utc(registration["registered_at"])
    for key,row in full.items():
        ko=utc(row["kickoff_utc"])
        known=utc(row["known_at"])
        if ko>now or known<registered:
            continue
        p=row.get("market_probability_over_2_5")
        if ((row.get("price_quality") or {}).get("status")!="USABLE" or
                not isinstance(p,(int,float)) or isinstance(p,bool) or not math.isfinite(p)
                or not 0<p<1):
            continue
        week=date_week(ko)
        eligible[week]+=1
        e=ft.get(key)
        if not e or e.get("snapshot",{}).get("status")!="FINAL":
            continue
        checked=utc(e.get("source_last_checked_at"))
        if not checked or checked<ko or checked>now:
            continue
        score=e["snapshot"].get("score") or {}
        h,a=score.get("home"),score.get("away")
        if type(h) is not int or type(a) is not int or h<0 or a<0:
            continue
        calib[week].append((p,int(h+a>2.5)))
    fmts=defaultdict(list)
    for row in formats:
        dt=utc(row.get("observed_at"))
        if dt and dt<=now:
            fmts[date_week(dt)].append(row)
    weeks=sorted(set(bucketed)|set(fmts)|set(calib)|set(eligible))
    # Keep current plus recent complete weeks; no comparisons against the open
    # current week, because incompleteness could mimic drift.
    weeks=weeks[-MAX_WEEKS:]
    stats=[week_summary(w,w==current,list(bucketed[w].values()),fmts[w],calib[w])
           for w in weeks]
    for s in stats:
        s["calibration"]["eligible_pre_kickoff_post_registration"]=eligible[s["week"]]
    completed=[s for s in stats if s["period"]=="COMPLETED"]
    baseline,compare=(completed[-2:] if len(completed)>=2 else [None,None])
    results=comparisons(baseline,compare)
    reviewed=any(x["status"]=="SUSPECTED_DRIFT_REVIEW" for x in results.values())
    ready=any(x["status"] in ("NO_THRESHOLD_CROSSED","SUSPECTED_DRIFT_REVIEW") for x in results.values())
    overall=("SUSPECTED_DRIFT_REVIEW" if reviewed else
             "PARTIALLY_EVALUATED_NO_ALERT" if ready else "INSUFFICIENT_HISTORY")
    return {
        "schema_version":VERSION,"status":STATUS,
        "as_of":now.isoformat(timespec="seconds"),
        "monitor_week":current,"first_day_of_monitor_week":week_begin(now),
        "overall":overall,
        "last_comparable_completed_weeks":[baseline["week"],compare["week"]] if baseline else [],
        "comparisons":results,"weeks":stats,
        "input": {
            "forecasts_total":len(forecasts),
            "ft_events_total":len(ft_events),
            "formats_total":len(formats),
            "forecast_tail":forecasts[-1]["sha256"] if forecasts else None,
            "ft_tail":ft_events[-1]["sha256"] if ft_events else None,
            "format_projection_digest":digest(formats),
            "registration_sha256":registration["sha256"],
        },
        "thresholds_predeclared":{
            "min_quality_matches_per_completed_week":MIN_QUALITY_N,
            "min_format_messages_per_completed_week":MIN_FORMAT_N,
            "min_market_matches_per_completed_week":MIN_MARKET_N,
            "min_calibration_games_per_completed_week":MIN_CALIBRATION_N,
            "min_calibration_games_per_comparison_week":MIN_CALIBRATION_COMPARISON_N,
            "quality_rate_absolute_change":QUALITY_DELTA_WATCH,
            "format_js_bits":FORMAT_JS_WATCH,
            "new_family_share":NEW_FORMAT_FAMILY_SHARE_WATCH,
            "market_psi":MARKET_PSI_WATCH,
            "brier_deterioration":CALIBRATION_BRIER_DETERIORATION_WATCH,
        },
        "limitations":[
            "Only completed ISO UTC weeks can trigger a drift review; current week is provisional.",
            "All drift signals are heuristic screening, not a causal or statistical significance test.",
            "The latest week with partial FT can have selection bias; review FT coverage before interpretation.",
            "Calibration uses one actual pre-kickoff freeze AFTER formal registration and a verified later FT; no historical backfill.",
            "Probability Over 2.5 is a model reference from Total Asian odds, not an executable O2.5 price.",
            "V4 format timestamps describe original Telegram messages, not proven collector ingestion or immutable revisions.",
            "Daily/weekly sampling variation and competition mix can explain apparent drift.",
            "A lack of threshold crossing is never a proof of stability, quality, edge or profitability.",
            "The monitor has no API calls, notifications, betting actions or power to validate V5/V6 hypotheses.",
        ],
    }


def build(root, now):
    root=Path(root)
    forecasts=read_journal(root)
    ft=read_ft_events(root)
    formats=load_formats(root)
    reg,_=ensure_registered(root,now)
    return analyze(forecasts,ft,formats,reg,now=now)
