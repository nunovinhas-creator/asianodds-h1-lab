"""Safe, read-only live FT backlog diagnostics — one fixture, not one bet.

All counts derive from the reconciled LAB ledger and the actual UTC clock.
The provider list refers ONLY to the LAST attempt's reason set; absence in
that set is NOT proof a service has never been queried historically.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from .lab_results import DELAY, retry_wait, utc

PROVIDERS=("bsd","thesportsdb","espn","sportscore","api_football","goal","openfoot","fotmob")
STATUS="FT_BACKLOG_AUDIT_OBSERVATION_ONLY"


def audit(ledger, now, *, provider_summary=None, queue_plan=None):
    if now.tzinfo is None:
        raise ValueError("Timezone-aware UTC now required")
    now=now.astimezone(timezone.utc)
    matches=ledger.get("matches")
    if not isinstance(matches,dict):
        raise ValueError("Expected LAB FT matches dict")
    plan = queue_plan if isinstance(queue_plan, dict) else {}
    chosen = set(plan.get("selected_keys", []))
    deferred = set(plan.get("deferred_keys", []))
    groups=Counter()
    obstacles=Counter()
    days=defaultdict(lambda:{"overdue":0,"never_checked":0,"last_check_without_provider":Counter()})
    overdue=[]
    for key,item in sorted(matches.items()):
        if not isinstance(item,dict):
            raise ValueError("Invalid LAB FT record")
        ko=utc(item.get("kickoff_utc"))
        if item.get("status")=="FINAL":
            groups["verified_ft"]+=1
            continue
        if ko is None:
            groups["unknown_kickoff"]+=1
            continue
        if now<ko:
            groups["future"]+=1
            continue
        if now<ko+DELAY:
            groups["in_3h_grace"]+=1
            continue
        if item.get("status") in ("SCORE_CONFLICT","SOURCE_ORDER_CONFLICT",
                                   "IDENTITY_CONFLICT","INSUFFICIENT_IDENTITY"):
            groups["quarantined_or_identity_review"]+=1
            continue
        groups["past_due_unverified"]+=1
        day=ko.date().isoformat()
        checked=utc(item.get("checked_at"))
        provider_reasons=item.get("provider_reasons") or {}
        if not isinstance(provider_reasons,dict):
            provider_reasons={}
        if checked is None:
            groups["past_due_never_checked"]+=1
            days[day]["never_checked"]+=1
        days[day]["overdue"]+=1
        for provider in PROVIDERS:
            if provider not in provider_reasons:
                days[day]["last_check_without_provider"][provider]+=1
            else:
                obstacles[(provider,str(provider_reasons[provider]))]+=1
        if item.get("status")=="EXPIRED_UNVERIFIED":
            groups["past_due_expired"]+=1
        next_eligible = (checked + retry_wait(item) if checked is not None else now)
        if item.get("status") == "EXPIRED_UNVERIFIED":
            queue_state = "OUTSIDE_30_DAY_API_WINDOW"
        elif key in chosen:
            queue_state = "CONSULTED_THIS_RUN"
        elif key in deferred:
            queue_state = "DEFERRED_BY_30_GAME_CAP"
        elif next_eligible > now:
            queue_state = "ADAPTIVE_COOLDOWN"
        else:
            queue_state = "DUE_NOT_SELECTED"
        overdue.append({
            "match_key":key,"home":item.get("home"),"away":item.get("away"),
            "kickoff_utc":item.get("kickoff_utc"),
            "last_checked_at":item.get("checked_at"),
            "next_eligible_at": (next_eligible.isoformat(timespec="seconds")
                                 if item.get("status") != "EXPIRED_UNVERIFIED" else None),
            "queue_state": queue_state,
            "overdue_hours": round((now - ko - DELAY).total_seconds()/3600, 1),
            "provider_attempts": item.get("provider_attempts", {}),
            "attempts":item.get("attempts",0),
            "status":item.get("status"),
            "last_attempt_provider_reasons":{k:provider_reasons[k] for k in sorted(provider_reasons)}
        })
    grouped={d:{"overdue":v["overdue"],"never_checked":v["never_checked"],
                "last_check_without_provider":dict(sorted(v["last_check_without_provider"].items()))}
             for d,v in sorted(days.items())}
    # Smallest actionable list first; include all <=500 games and never leak secrets.
    overdue.sort(key=lambda x:(x["last_checked_at"] is not None,
                               x["last_checked_at"] or "",x["kickoff_utc"] or "",
                               x["match_key"]))
    return {
        "schema_version":1,"status":STATUS,
        "measured_at":now.isoformat(timespec="seconds"),
        "total_matches":len(matches),
        "classification":dict(sorted(groups.items())),
        "overdue_by_kickoff_utc_day":grouped,
        "last_attempt_obstacles":[{"provider":p,"reason":why,"games":count}
                                  for (p,why),count in sorted(obstacles.items(),
                                    key=lambda v:(-v[1],v[0]))[:60]],
        "last_run_providers":provider_summary or {},
        "queue_plan": {k:v for k,v in plan.items() if k not in ("selected_keys","deferred_keys")},
        "deferred_games": sorted(deferred),
        "overdue_games":overdue[:500],
        "overdue_omitted":max(0,len(overdue)-500),
        "limitations":[
            "FUTURE and IN_3H_GRACE games are NOT overdue.",
            "last_attempt_provider_reasons are NOT lifetime provider-attempt counters.",
            "provider_attempts counts adapter invocations, including cache hits; not HTTP requests.",
            "next_eligible_at is the routine retry date; a proven new provider/version may trigger earlier.",
            "Providers are never assumed to cover every competition.",
            "No missing FT becomes a loss, an invented score, or an H1 settlement.",
            "A single observed result is not an independently corroborated source.",
        ],
    }
