"""Persist BSD fixture IDs learned from COMPLETE date pages, not guessed team IDs.

A BSD date-list row is a *locator*, not a final result. Discovery checks the
entire date catalogue, exact ordered teams or conservative CORE_NAME at a
five-minute kickoff window, no competing fixture or duplicate observed game.
Once sealed in the registry, subsequent reconciliations use BSD /events/{id}/
and compare the returned event against the frozen provider identities.

No scores, odds, raw API payloads, access tokens or retrospective timestamps
enter this file. A changed ID, team or kickoff quarantines the binding.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timedelta, timezone
from .bsd import ROOT, event_name, event_kickoff
from .lab_identity import pair_level, core_tokens
from .lab_ft_crosswalk import providers_from_final, event_id as final_event_id
from .lab_identity_review import _qualifiers
from .lab_results import utc
from .lab_monte_bsd import validated_result

SCHEMA = 1
WINDOW = timedelta(minutes=5)
COLLISION_WINDOW = timedelta(minutes=90)
RETENTION = timedelta(days=45)
MAX_FIXTURES = 1500
MAX_MATCHES = 3000
MAX_DAYS = 45


def empty():
    return {"schema_version": SCHEMA, "days": {}, "matches": {}, "conflicts": {}, "probes": {}}


def _identity(event, day):
    if not isinstance(event, dict):
        return None
    ident = event.get("id")
    home, away, when = (event_name(event, "home_team"),
                        event_name(event, "away_team"), event_kickoff(event))
    if (type(ident) is not int or ident <= 0 or not isinstance(home, str)
            or not isinstance(away, str) or when is None
            or when.date().isoformat() != day
            or not core_tokens(home) or not core_tokens(away)
            or core_tokens(home) == core_tokens(away)
            or len(home) > 150 or len(away) > 150):
        return None
    return {"event_id": ident, "provider_home": home, "provider_away": away,
            "provider_kickoff_utc": when.astimezone(timezone.utc).isoformat(timespec="seconds")}


def _valid_match(key, row, locator):
    if not isinstance(row, dict) or not isinstance(locator, dict):
        return False
    ko, when = utc(row.get("kickoff_utc")), utc(locator.get("provider_kickoff_utc"))
    if ko is None or when is None or abs(ko-when)>WINDOW:
        return False
    if (row.get("match_key", key) != key or
            not isinstance(row.get("home"), str) or
            not isinstance(row.get("away"), str)):
        return False
    return (pair_level(row["home"], row["away"],
                       locator["provider_home"], locator["provider_away"]) is not None
            and _qualifiers(row["home"]) == _qualifiers(locator["provider_home"])
            and _qualifiers(row["away"]) == _qualifiers(locator["provider_away"]))


def _collision(source, row, available, all_matches, key):
    when = utc(source["provider_kickoff_utc"])
    hc, ac = core_tokens(source["provider_home"]), core_tokens(source["provider_away"])
    for item in available:
        if item["event_id"] == source["event_id"]:
            continue
        dt = utc(item["provider_kickoff_utc"])
        if dt is not None and abs(dt-when)<=COLLISION_WINDOW:
            sides = {core_tokens(item["provider_home"]), core_tokens(item["provider_away"])}
            if hc in sides or ac in sides:
                return "BSD_SOURCE_SIDE_COLLISION"
    for other_key, other in all_matches.items():
        if other_key == key or not isinstance(other,dict):
            continue
        other_ko = utc(other.get("kickoff_utc"))
        if other_ko is None or abs(when-other_ko)>WINDOW:
            continue
        if _valid_match(other_key,other,source):
            return "ASIANODDS_DUPLICATE_FIXTURE"
    return None


def discover(previous, caches, all_matches, now):
    if (not isinstance(previous, dict) or previous.get("schema_version")!=SCHEMA
            or any(not isinstance(previous.get(f),dict)
                   for f in ("days","matches","conflicts"))
            or not isinstance(caches, dict) or not isinstance(all_matches,dict)
            or now.tzinfo is None):
        raise ValueError("Invalid BSD ID discovery inputs")
    now=now.astimezone(timezone.utc)
    out=empty()
    out["conflicts"] = dict(previous["conflicts"])
    out["probes"] = {day: dict(value)
                      for day,value in previous.get("probes",{}).items()
                      if isinstance(value,dict)
                      and utc(day+"T00:00:00+00:00") is not None
                      and timedelta(0) <= now-utc(day+"T00:00:00+00:00")<=RETENTION}
    out["matches"] = {}
    for key,entry in previous["matches"].items():
        if not isinstance(entry,dict):
            raise ValueError("Invalid prior BSD ID mapping")
        ko=utc(entry.get("kickoff_utc"))
        if (ko is not None and timedelta(0)<=now-ko<=RETENTION
                and key in all_matches and
                _valid_match(key,all_matches[key],entry)
                and all_matches[key].get("home")==entry.get("home")
                and all_matches[key].get("away")==entry.get("away")
                and all_matches[key].get("kickoff_utc")==entry.get("kickoff_utc")):
            out["matches"][key]=dict(entry)
        elif key in all_matches:
            out["conflicts"][key]={"reason":"EXISTING_MAPPING_CHANGED_OR_INVALID",
                                  "detected_at_utc":now.isoformat(timespec="seconds")}
    out["days"]={day:dict(info) for day,info in previous["days"].items()
                 if isinstance(info,dict) and utc(day+"T00:00:00+00:00") is not None
                 and timedelta(0)<=now-utc(day+"T00:00:00+00:00")<=RETENTION}
    stats=Counter()
    # Collision claims also include previously verified BSD final results.
    claims={}
    for key, row in all_matches.items():
        if isinstance(row, dict) and row.get("status")=="FINAL":
            sources=providers_from_final(row)
            bid=final_event_id("bsd", sources.get("bsd"))
            if bid: claims.setdefault(int(bid),set()).add(key)
    for key,row in out["matches"].items():
        claims.setdefault(row["event_id"],set()).add(key)
    for day, pair in sorted(caches.items()):
        if isinstance(day,str):
            out["probes"][day]={
                "attempted_at_utc":now.isoformat(timespec="seconds"),
                "status": ("COMPLETE" if isinstance(pair,(tuple,list)) and
                           len(pair)==2 and pair[1]=="complete"
                           else "UNAVAILABLE_OR_INCOMPLETE")}
        if (not isinstance(day,str) or
                not isinstance(pair,(tuple,list)) or len(pair)!=2
                or pair[1]!="complete" or not isinstance(pair[0],list)):
            stats["incomplete_or_failed_days"]+=1
            continue
        items=pair[0]
        if len(items)>MAX_FIXTURES:
            stats["oversize_days"]+=1
            continue
        catalogue=[_identity(event,day) for event in items]
        ids=[r["event_id"] for r in catalogue if r is not None]
        if (len(ids)!=len(items) or len(ids)!=len(set(ids))):
            stats["invalid_or_duplicate_catalogue"]+=1
            continue
        # The BSD search adapter has ALREADY verified every pagination page.
        # Never reconstruct a catalogue from a partial list.
        out["days"][day]={"fetched_at_utc":now.isoformat(timespec="seconds"),
                          "status":"COMPLETE","total_events":len(catalogue)}
        stats["complete_days"]+=1
        for key,g in all_matches.items():
            if (not isinstance(g,dict) or g.get("status")=="FINAL"
                    or g.get("kickoff_utc","")[:10]!=day or key in out["conflicts"]):
                continue
            candidates=[e for e in catalogue if _valid_match(key,g,e)]
            if len(candidates)!=1:
                if len(candidates)>1: stats["ambiguous_id_candidates"]+=1
                continue
            source=candidates[0]
            collision=_collision(source,g,catalogue,all_matches,key)
            if collision:
                stats[collision]+=1
                continue
            previous_claims=claims.get(source["event_id"],set())-{key}
            if previous_claims:
                stats["shared_event_id"]+=1
                out["conflicts"][key]={
                    "reason":"BSD_ID_ALREADY_CLAIMED",
                    "detected_at_utc":now.isoformat(timespec="seconds")}
                continue
            item={"match_key":key,"home":g["home"],"away":g["away"],
                  "kickoff_utc":g["kickoff_utc"],**source,
                  "first_seen_at_utc":now.isoformat(timespec="seconds"),
                  "source":"BSD_COMPLETE_FINISHED_DAY_LIST",
                  "identity_match":pair_level(g["home"],g["away"],
                                             source["provider_home"],
                                             source["provider_away"])}
            old=out["matches"].get(key)
            if old:
                if any(old.get(k)!=item.get(k) for k in
                       ("event_id","provider_home","provider_away","provider_kickoff_utc")):
                    out["conflicts"][key]={
                        "reason":"BSD_DAY_RECHECK_CHANGED_IDENTITY",
                        "detected_at_utc":now.isoformat(timespec="seconds")}
                    stats["recheck_conflicts"]+=1
                continue
            if len(out["matches"])>=MAX_MATCHES:
                raise ValueError("BSD identity registry exceeds capacity")
            out["matches"][key]=item
            claims.setdefault(source["event_id"],set()).add(key)
            stats["new_ids"]+=1
    out["days"]=dict(sorted(out["days"].items())[-MAX_DAYS:])
    out["probes"]=dict(sorted(out["probes"].items())[-MAX_DAYS:])
    stats["total_id_bindings"]=len(out["matches"])
    stats["quarantined_bindings"]=len(out["conflicts"])
    return out,dict(sorted(stats.items()))


class BSDRegistryLookup:
    """Use one shared Monte-Carlos BSD detail quota; NEVER rerequest a team list."""
    def __init__(self, registry, monte):
        self.registry=registry
        self.monte=monte
        self.reasons=Counter()

    def lookup(self,signal):
        key=signal.get("match_key")
        if key in self.registry.get("conflicts",{}):
            return self._fail("bsd_registry_quarantined")
        binding=self.registry.get("matches",{}).get(key)
        if binding is None:
            return self._fail("bsd_registry_no_id")
        if (not _valid_match(key,signal,binding)
                or any(signal.get(f)!=binding.get(f)
                       for f in ("home","away","kickoff_utc"))):
            return self._fail("bsd_registry_identity_changed")
        ident=binding["event_id"]
        for other_key,other in self.registry.get("matches",{}).items():
            if other_key!=key and other.get("event_id")==ident:
                return self._fail("bsd_registry_id_collision")
        event,reason=self.monte._event(ident)
        if event is None:
            self.reasons[reason]+=1
            return None,reason
        if (not isinstance(event,dict) or event.get("id")!=ident or
                event.get("replaced_by")):
            return self._fail("bsd_registry_id_redirect_or_mismatch")
        when=event_kickoff(event)
        source_dt=utc(binding["provider_kickoff_utc"])
        if (when is None or abs(when-source_dt)>WINDOW or
                any(not isinstance(event_name(event,side+"_team"),str)
                    or core_tokens(event_name(event,side+"_team"))!=
                    core_tokens(binding["provider_"+side])
                    or _qualifiers(event_name(event,side+"_team"))!=
                    _qualifiers(binding["provider_"+side])
                    for side in ("home","away"))):
            return self._fail("bsd_registry_detail_changed_identity")
        # Strict BSD 90m validator sees the actual provider names, not a
        # global alias or the AsianOdds IDs.
        scoped=dict(signal,home=binding["provider_home"],away=binding["provider_away"])
        result,reason=validated_result(scoped,event)
        if result is not None:
            result["identity_match"]="REVIEWED_PAIR"
            self.reasons["verified_bsd_from_persisted_id"]+=1
            return result,"verified_bsd_from_persisted_id"
        self.reasons[reason]+=1
        return None,reason

    def _fail(self,reason):
        self.reasons[reason]+=1
        return None,reason

    def summary(self):
        return {"known_ids":len(self.registry.get("matches",{})),
                "conflicts":len(self.registry.get("conflicts",{})),
                "reasons":dict(sorted(self.reasons.items()))}

def plan_days(selected_keys, matches, registry, now, max_days=3):
    """Group due unresolved fixtures by UTC day, honoring 4h day cooldown.

    A date listing is an amortized shared ID discovery request: never run
    it for a fixture with a trusted mapping. No name-search requests.
    """
    if type(max_days) is not int or not 0<=max_days<=4 or now.tzinfo is None:
        raise ValueError("Invalid BSD day plan budget")
    by_day=Counter()
    for key in selected_keys:
        row=matches.get(key)
        if (not isinstance(row,dict) or row.get("status") not in
                ("PENDING","PROVIDER_ERROR")
                or key in registry.get("matches",{})
                or key in registry.get("conflicts",{})):
            continue
        ko=utc(row.get("kickoff_utc"))
        if ko is None or not ko+timedelta(hours=3)<=now<=ko+RETENTION:
            continue
        day=ko.date().isoformat()
        probe=registry.get("probes",{}).get(day) or {}
        attempted=utc(probe.get("attempted_at_utc"))
        if attempted is not None and timedelta(0)<=now-attempted<timedelta(hours=4):
            continue
        by_day[day]+=1
    return [day for day,count in sorted(by_day.items(), key=lambda p:(-p[1],p[0]))][:max_days]
