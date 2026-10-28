"""P0 7/14-day readiness and per-FT knowledge chronology, independent of H1.

The prospective gate remains BLOCKED until the complete elapsed period, 99%
source-observable coverage AND separate review of Git collector run continuity
and original revisions. No mutable retrospective source is promoted to proof.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from .timeline import collect_timelines, read_sources
from .v4_revisions import read_events as read_v4_revisions
from .v6_shadow import read_journal, utc
from .v6_science_memory import read_stream
from .v6_hypotheses import ensure_registered
from .v6_readiness import measure


def _utc_day(value):
    return value.astimezone(timezone.utc).date().isoformat()


def _daily(timelines, frozen, now, first, days):
    start = max(first, now-timedelta(days=days)) if first else None
    matches = {}
    for t in timelines:
        identity=t.get("identity") or {}
        ko_list=identity.get("kickoff_utc") or []
        if (not start or len(ko_list)!=1 or not identity.get("kickoff_consistent")
                or not identity.get("team_names_consistent")
                or identity.get("per_message_conflicts")):
            continue
        ko=utc(ko_list[0])
        if not ko or not start <= ko <= now:
            continue
        if any((v:=utc(e.get("observed_at"))) and v < ko for e in t.get("events", [])):
            matches[t["match_key"]]=ko
    freezes = {x["match_key"] for x in frozen
               if (known:=utc(x.get("known_at"))) and
               (ko:=utc(x.get("kickoff_utc"))) and known < ko}
    stats=defaultdict(lambda: {"opportunities":0,"captured":0,"missing":0})
    for key,ko in matches.items():
        day=stats[_utc_day(ko)]
        day["opportunities"]+=1
        if key in freezes:
            day["captured"]+=1
        else:
            day["missing"]+=1
    return dict(sorted(stats.items()))


def ft_chronology(forecasts, evidence, registered_at, now):
    """Check every FT scientific event's timestamps against its frozen origin.

    An FT ledger checked_at is NOT an independently verified provider arrival
    time; valid chronology is labelled provisional, not certified.
    """
    frozen={}
    for r in forecasts:
        old=frozen.get(r["match_key"])
        if old is None or (r["known_at"],r["event_id"])>(old["known_at"],old["event_id"]):
            frozen[r["match_key"]]=r
    counts=Counter()
    exceptions=[]
    eligible_keys=set()
    valid_keys=set()
    for key,f in sorted(frozen.items()):
        known=utc(f.get("known_at"))
        ko=utc(f.get("kickoff_utc"))
        if known and ko and registered_at <= known < ko and ko <= now:
            eligible_keys.add(key)
    latest={}
    for item in evidence:
        e=item["event"]
        latest[e["match_key"]]=item
        if e.get("state")!="CONFIRMED":
            counts["non_confirmed_evidence_events"]+=1
            continue
        key=e.get("match_key")
        f=frozen.get(key)
        known=utc(f.get("known_at")) if f else None
        ko=utc(f.get("kickoff_utc")) if f else None
        checked=utc(e.get("ft_checked_at"))
        ingested=utc(item.get("written_at"))
        errors=[]
        if not f or not known or not ko or not registered_at <= known < ko:
            errors.append("NOT_REGISTERED_PREKICKOFF")
        if e.get("frozen_source_sha256")!=(f.get("sha256") if f else None):
            errors.append("FT_FORECAST_SHA_MISMATCH")
        if not checked or not ko or checked < ko+timedelta(minutes=90):
            errors.append("NO_POST_90MIN_FT_CHECK")
        if not ingested or not checked or ingested < checked or (known and ingested < known):
            errors.append("FT_INGEST_BEFORE_CHECK_OR_FREEZE")
        if not ingested or ingested > now:
            errors.append("FT_INGEST_IN_FUTURE")
        if checked and checked > now:
            errors.append("FT_CHECK_IN_FUTURE")
        if errors:
            counts["confirmed_event_chronology_invalid"]+=1
            exceptions.append({"match_key":key,"evidence_event_id":e.get("event_id"),
                               "failure_codes":errors})
        else:
            counts["confirmed_event_chronology_consistent_not_independently_proven"]+=1
    for key in sorted(eligible_keys):
        e=(latest.get(key) or {}).get("event",{})
        if e.get("state")=="CONFIRMED":
            # A previous invalid confirmed event never certifies a new FT.
            is_bad=any(x["match_key"]==key and
                       x["evidence_event_id"]==e.get("event_id") for x in exceptions)
            if not is_bad:
                valid_keys.add(key)
        else:
            counts["eligible_match_without_confirmed_ft"]+=1
    return {
        "registered_eligible_finished_matches":len(eligible_keys),
        "latest_temporally_consistent_ft_matches":len(valid_keys),
        "evidence_events_total":len(evidence),
        "counts":dict(sorted(counts.items())),
        "exceptions":exceptions[:60], "exceptions_total":len(exceptions),
        "chronology_certification":"SOURCE_LEDGER_TIMES_NOT_INDEPENDENT_PROVIDER_PROOF",
        "assumptions": [
            "A checked_at must occur >=90 minutes after kickoff and no later than the evidence memory write.",
            "A confirmed FT must reference the immutable pre-kickoff source SHA and post-registration freeze.",
            "A journal recorded/write timestamp proves system processing, not a provider-side FT assertion.",
            "No retroactive FT observations or missing timestamps are invented.",
        ],
    }


def evaluate(root, now):
    if now.tzinfo is None:
        raise ValueError("Evaluation clock must be timezone-aware")
    now=now.astimezone(timezone.utc)
    forecasts=read_journal(root)
    # Validates the full V4 revision SHA chain, including revisions across files.
    revs=read_v4_revisions(root)
    registration,_=ensure_registered(root,now)
    registered_at=utc(registration["registered_at"])
    if registered_at is None:
        raise ValueError("Invalid registered_at")
    evidence=read_stream(root,"evidence")
    alerts,market,errors=read_sources(root)
    timelines,_,_=collect_timelines(alerts,market,source_errors=errors)
    readiness=measure(timelines,forecasts,now)
    first=utc(readiness["first_prospective_known_at"])
    days=(now-first).total_seconds()/86400 if first else 0
    gates={}
    for period,field in ((7,"last_7_kickoff_days"),(14,"last_14_kickoff_days")):
        source=readiness[field]
        sample={**source,"daily_eligible_kickoff_utc":_daily(
            timelines,forecasts,now,first,period),
            "elapsed_days_since_first_frozen":round(days,4),
            "all_collector_runs_and_git_pushes_independently_audited":False,
            "historical_telegram_message_delivery_at_known_at_proven":False}
        if days < period:
            status="WARMUP"
        elif not source["source_eligible"] or source["ratio"] is None:
            status="NO_SOURCE_OPPORTUNITIES"
        elif source["ratio"] < .99:
            status="BELOW_99_PERCENT"
        else:
            status="SOURCE_COVERAGE_PASSED_EXTERNAL_RUN_AUDIT_REQUIRED"
        sample["scientific_acceptance"]="BLOCKED"
        sample["status"]=status
        gates[str(period)+"_days"]=sample
    ft=ft_chronology(forecasts,evidence,registered_at,now)
    return {
        "schema_version":1,"status":"V6_P0_PROSPECTIVE_GATES_NOT_VALIDATED",
        "scientific_state":"INCONCLUSIVO",
        "evaluation_clock":now.isoformat(timespec="seconds"),
        "first_frozen_known_at":readiness["first_prospective_known_at"],
        "registered_at":registration["registered_at"],
        "data_lineage":{"frozen_records":len(forecasts),"v4_revision_rows":len(revs),
                        "sha_chain_verified":True,"ft_memory_events":len(evidence),
                        "timeline_source_errors":len(errors)},
        "gates":gates,"ft_knowledge_timeline":ft,
        "unverified_requirements":[
            "Continuous 7/14 days of audited Git collector runs and successful nonconflicting pushes",
            "Independent proof of timely Telegram ingestion for every eligible opportunity",
            "Git commit-by-commit evidence of no retrospective modifications to frozen observations",
            "Independent FT provider/check chronology for every prospective outcome",
            "1000 genuine registered prospective FT across >=3 distinct ISO weeks for V6.3",
        ],
        "limitations":[
            "Elapsed days are measured from the first real known_at, never from old Telegram observed_at.",
            "The source denominator is Telegram opportunities already visible, not all scheduled fixtures.",
            "The SHA chain tests current artifact consistency; only a Git-history audit proves no full rewrite.",
            "FT timestamps sourced from a mutable ledger are provisional unless independently corroborated.",
            "No automatic upgrade of gate state, scientific pattern promotion or alerts.",
        ],
    }
