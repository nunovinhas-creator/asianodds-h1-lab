"""Read-only identity registry: only event URLs from confirmed FT results."""
from __future__ import annotations
import re

SOURCES = {
 "bsd": ("https://sports.bzzoiro.com/api/v2/events/", r"[0-9]+/"),
 "goal": ("https://api.goal-api.com/v1/fixtures/", r"[0-9]{3,12}"),
 "api_football": ("https://v3.football.api-sports.io/fixtures?id=", r"[0-9]+"),
}

def event_id(provider, url):
    if provider not in SOURCES or not isinstance(url, str):
        return None
    prefix, expression = SOURCES[provider]
    if not url.startswith(prefix):
        return None
    tail = url[len(prefix):]
    if not re.fullmatch(expression, tail):
        return None
    return tail.rstrip("/")

def providers_from_final(row):
    value = row.get("result") or {}
    evidence = value.get("evidence", "")
    sources = row.get("verified_provider_sources") or {}
    found = {}
    for p in SOURCES:
        record = sources.get(p) or {}
        link = record.get("source") if isinstance(record, dict) else None
        if event_id(p, link):
            found[p] = link
        elif p in (evidence.split("_and_") if isinstance(evidence,str) else ()):
            link = value.get("source")
            if event_id(p, link):
                found[p] = link
        elif evidence == p + "_only":
            link = value.get("source")
            if event_id(p, link):
                found[p] = link
    return found

def build_registry(ledger, existing=None):
    previous = existing or {"schema_version":1,"entries":{}}
    if previous.get("schema_version") != 1 or not isinstance(previous.get("entries"),dict):
        raise ValueError("Invalid FT identity registry")
    rows = previous["entries"].copy()
    matches = ledger.get("matches")
    if not isinstance(matches, dict):
        raise ValueError("Invalid FT ledger")
    for key, item in sorted(matches.items()):
        if item.get("status") != "FINAL":
            continue
        if not all(isinstance(item.get(f),str) and item[f] for f in ("home","away","kickoff_utc")):
            continue
        for provider, url in providers_from_final(item).items():
            identity = provider + ":" + event_id(provider,url)
            old = rows.get(identity)
            if old and old.get("match_key") != key:
                rows[identity] = {**old, "status":"COLLISION_REVIEW",
                                  "conflicting_match_keys":sorted(set(
                                      old.get("conflicting_match_keys",[]) + [key,old["match_key"]]))}
            elif not old:
                rows[identity] = {"status":"CONFIRMED_FT_SOURCE_ID",
                                   "provider":provider, "event_id":event_id(provider,url),
                                   "source":url,"match_key":key,
                                   "home":item["home"],"away":item["away"],
                                   "kickoff_utc":item["kickoff_utc"]}
    return {"schema_version":1,"entries":dict(sorted(rows.items())),
            "confirmed_ids":sum(x.get("status")=="CONFIRMED_FT_SOURCE_ID" for x in rows.values()),
            "collision_ids":sum(x.get("status")=="COLLISION_REVIEW" for x in rows.values())}
