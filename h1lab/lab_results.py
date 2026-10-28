"""Independent, bounded, fail-closed FT result collection for *all* observed LAB fixtures.

Never modifies or invokes H1 result syncing. Only reuses the existing pure
provider validators (BSD, TheSportsDB) in the executable adapter.
"""
from __future__ import annotations

import copy
import re
from .lab_reviewed_aliases import SPORTSCORE_REVIEWED, reviewed_provider_pair
from .lab_reviewed_bsd_ids import REVIEWED_BSD_FIXTURES
from .lab_sportscore import source_order_conflict
from .lab_ft_crosswalk import event_id, providers_from_final
from .lab_ft_evidence import fingerprint as evidence_fingerprint
from .lab_ft_reviewed_evidence import (REVIEWED_PUBLIC_FT, REVIEWED_PENDING_FT,
                                       public_evidence_urls, verified_public_ft)
from collections import Counter
from datetime import datetime, timedelta, timezone

SCHEMA = 1
MAX_CHECKS_CAP = 30
DELAY = timedelta(hours=3)
RETRY = timedelta(hours=4)
# Repeated no-result cycles use slower retries; never mark a missing FT final.
# A new source version or explicitly reviewed evidence may still bypass this.
def retry_wait(entry):
    attempts = max(0, int(entry.get("evidence_attempts", entry.get("attempts", 0))))
    if attempts >= 10:
        return timedelta(hours=24)
    if attempts >= 6:
        return timedelta(hours=12)
    return RETRY

HORIZON = timedelta(days=30)
STATUS = "LAB_FT_OBSERVATION_ONLY_NOT_CERTIFIED"
LOOKUP_SOURCE_VERSION = 9  # default sources; do not consume V10 retry without an API key
# Retain meaningful last-seen GOAL evidence independently from last-attempt
# telemetry. Rotation deferrals are not a negative finding about a fixture.
GOAL_ID_RECHECK_EVIDENCE = frozenset({
    "goal_no_regulation_score", "goal_not_finished_or_unverified",
    "goal_et_evidence_missing", "goal_penalty_evidence_missing",
})

API_FOOTBALL_SOURCE_VERSION = 10  # only the official API-enabled LAB run upgrades
OPEN_RESULT_SOURCES_VERSION = 11  # GOAL and OpenFoot FT coverage verified in the LAB only


def utc(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _label(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def build_catalog(alerts, v4rows):
    """Every match_key in H1 alerts or V4 records, not merely H1 signals.

    A V4-only row may have match_key/time but no team names; keep it visible
    as insufficient identity rather than guessing its fixture via IDs.
    """
    games = {}
    errors = 0
    for origin, rows in (("H1_ALERT", alerts), ("V4", v4rows)):
        for row in rows:
            if not isinstance(row, dict):
                errors += 1
                continue
            key = _label(row.get("match_key"))
            if not key:
                errors += 1
                continue
            match = games.setdefault(key, {"match_key": key, "home": None, "away": None,
                                           "kickoff_utc": None, "sources": set(),
                                           "identity_conflict": False, "alerts": 0})
            match["sources"].add(origin)
            if origin == "H1_ALERT":
                match["alerts"] += 1
            for field in ("home", "away", "kickoff_utc"):
                value = _label(row.get(field))
                if not value:
                    continue
                if field == "kickoff_utc":
                    parsed = utc(value)
                    if parsed is None:
                        match["identity_conflict"] = True
                        continue
                    value = parsed.isoformat(timespec="seconds")
                prior = match[field]
                if prior is None:
                    match[field] = value
                elif prior.casefold() != value.casefold():
                    match["identity_conflict"] = True
    return games, errors


def _safe_reason(value):
    return re.sub(r"[^a-zA-Z0-9_,;: -]", "_", str(value or "unknown"))[:120]


def _validate_result(result, key):
    if not isinstance(result, dict) or result.get("match_key") != key or result.get("status") != "final":
        return None
    h, a, source = result.get("home_goals"), result.get("away_goals"), result.get("source")
    if type(h) is not int or type(a) is not int or h < 0 or a < 0:
        return None
    if not isinstance(source, str) or not source.startswith("https://") or len(source) > 512:
        return None
    out = {"home_goals": h, "away_goals": a, "source": source}
    # Provenance of the team-name identity rule (absent = exact legacy rule).
    if result.get("identity_match") in ("EXACT", "CORE_NAME", "REVIEWED_PAIR"):
        out["identity_match"] = result["identity_match"]
    return out


def reconcile(state, v4rows, previous, *, now, bsd_lookup, tsdb_lookup, max_checks=20, espn_lookup=None, sportscore_lookup=None, fotmob_lookup=None, api_football_lookup=None, goal_lookup=None, openfoot_lookup=None, lookup_source_version=None, force_recheck=False, priority_hints=None, evidence_retry=False):
    """Return (new ledger, aggregate/public report, count of API-search attempts).

    Lookup callables accept {match_key,home,away,kickoff_utc} and return
    (result_or_None, diagnostic). Neither callable mutates H1 files.
    """
    if now.tzinfo is None:
        raise ValueError("now requires timezone")
    now = now.astimezone(timezone.utc)
    source_version = LOOKUP_SOURCE_VERSION if lookup_source_version is None else lookup_source_version
    if type(source_version) is not int or not LOOKUP_SOURCE_VERSION <= source_version <= OPEN_RESULT_SOURCES_VERSION:
        raise ValueError("Unsupported LAB FT lookup source version")
    if not isinstance(max_checks, int) or not 0 <= max_checks <= MAX_CHECKS_CAP:
        raise ValueError("max_checks outside safe range 0..30")
    if type(force_recheck) is not bool or type(evidence_retry) is not bool:
        raise ValueError("force_recheck and evidence_retry must be boolean")
    if priority_hints is None:
        priority_hints = {}
    if (not isinstance(priority_hints, dict) or
            any(not isinstance(k, str) or type(v) is not int or v not in (1, 2, 3)
                for k, v in priority_hints.items())):
        raise ValueError("Invalid LAB research priority hints")
    if not isinstance(state, dict) or not isinstance(state.get("alerts"), list):
        raise ValueError("H1 alerts missing or invalid")
    if not isinstance(v4rows, list):
        raise ValueError("V4 rows invalid")
    if not isinstance(previous, dict) or previous.get("schema_version", SCHEMA) != SCHEMA:
        raise ValueError("Incompatible LAB FT ledger")
    original = previous.get("matches", {})
    if not isinstance(original, dict):
        raise ValueError("Invalid previous LAB FT ledger")

    games, input_errors = build_catalog(state["alerts"], v4rows)
    entries = copy.deepcopy(original)
    new_keys = 0
    for key, game in games.items():
        if key not in entries:
            entries[key] = {"status": "NEW", "attempts": 0}
            new_keys += 1
        row = entries[key]
        identity = {k: game[k] for k in ("home", "away", "kickoff_utc")}
        old_identity = {k: row.get(k) for k in identity}
        identity_changed = any(old_identity[k] not in (None, identity[k])
                               for k in identity)
        # A changed H1 identity invalidates the historical GOAL clue.
        if identity_changed:
            row.pop("goal_ft_last_evidence", None)
            row.pop("goal_id_last_attempt_at", None)
        identity_changed_final = (row.get("status") == "FINAL" and identity_changed)
        if identity_changed_final:
            row["status"] = "IDENTITY_CONFLICT"  # quarantine prior result
            row.pop("result", None)
            row["reason"] = "identity_changed_since_ft"
        row.update(identity)
        row["sources"] = sorted(game["sources"])
        row["observed_alerts"] = game["alerts"]
        if game["identity_conflict"]:
            row["status"] = "IDENTITY_CONFLICT"
            row.pop("result", None)
            row["reason"] = "conflicting_observed_identity"
        elif not all(identity.values()):
            row["status"] = "INSUFFICIENT_IDENTITY"
            row.pop("result", None)
            row["reason"] = "missing_team_or_kickoff"
        elif row["status"] in ("NEW", "INSUFFICIENT_IDENTITY"):
            # A formerly incomplete V4 fixture may now have complete H1 identity.
            row["status"] = "PENDING"
            row["reason"] = "awaiting_ft"
        # Existing identity conflicts remain quarantined until human review.
        # Historical single-source SportScore results must also be audited
        # after detecting a provider disagreement between its teams and URL.
        recorded = row.get("result") if row.get("status") == "FINAL" else None
        if isinstance(recorded, dict) and recorded.get("evidence") == "sportscore_only":
            original_signal = {"match_key": key, **identity}
            source_pair = reviewed_provider_pair(original_signal) or (
                identity["home"], identity["away"])
            if source_order_conflict(recorded.get("source"), *source_pair):
                row["status"] = "SOURCE_ORDER_CONFLICT"
                row["reason"] = "sportscore_source_url_reverses_home_away"
                row.pop("result", None)  # not a valid 90m score assignment

    # Previously confirmed provider IDs belong to one observed match_key.
    # Never reuse an event ID from a different fixture for new auto settlement.
    claimed_ids = {}
    for confirmed_key, confirmed_row in original.items():
        if not isinstance(confirmed_row, dict) or confirmed_row.get("status") != "FINAL":
            continue
        for provider, url in providers_from_final(confirmed_row).items():
            eid = event_id(provider, url)
            if eid:
                identity = (provider, eid)
                claimed_ids.setdefault(identity, set()).add(confirmed_key)

    # Only independent providers can resolve a quarantined SportScore fixture.
    source_order_keys = {key for key in games
                         if entries[key]["status"] == "SOURCE_ORDER_CONFLICT"}
    candidates = []
    for key in games:
        entry = entries[key]
        if entry["status"] not in ("PENDING", "PROVIDER_ERROR", "SOURCE_ORDER_CONFLICT"):
            continue
        kickoff = utc(entry["kickoff_utc"])
        if kickoff is None:
            entry["status"] = "INSUFFICIENT_IDENTITY"
            continue
        if now > kickoff + HORIZON:
            if entry["status"] != "SOURCE_ORDER_CONFLICT":
                entry["status"] = "EXPIRED_UNVERIFIED"
                entry["reason"] = "beyond_30_day_lookup_window"
            continue
        if now < kickoff + DELAY:
            continue
        last = utc(entry.get("evidence_checked_at" if evidence_retry else "checked_at"))
        visit = utc(entry.get("queue_visited_at")) if evidence_retry else None
        # A newly added provider may be checked once immediately, without
        # disabling the normal four-hour cooldown on subsequent runs.
        upgrade = (entry["status"] != "SOURCE_ORDER_CONFLICT" and
                   int(entry.get("lookup_source_version", 0)) < source_version)
        alias_due = (entry["status"] != "SOURCE_ORDER_CONFLICT" and
                     key in SPORTSCORE_REVIEWED and
                     entry.get("reviewed_alias_check_version") != 1)
        bsd_id_due = (key in REVIEWED_BSD_FIXTURES and
                      entry.get("reviewed_bsd_id_check_version") != 1)
        public_due = (
            ((entry["status"] == "SOURCE_ORDER_CONFLICT" and
              (original.get(key) or {}).get("status") == "SOURCE_ORDER_CONFLICT" and
              key in REVIEWED_PUBLIC_FT) or
             (entry["status"] in ("PENDING", "PROVIDER_ERROR") and
              (original.get(key) or {}).get("status") in ("PENDING", "PROVIDER_ERROR") and
              key in REVIEWED_PENDING_FT))
            and entry.get("reviewed_public_ft_check_version") != 1)
        if last and now < last + retry_wait(entry) and not (upgrade or alias_due or bsd_id_due or public_due or force_recheck):
            continue
        # Fairness gate for a visit that found no new authenticated evidence.
        # This is NOT an FT attempt and never increases the exponential retry.
        if evidence_retry and visit and now < visit + timedelta(minutes=45) and not (force_recheck or public_due or bsd_id_due):
            continue
        # Proven real BSD IDs take precedence for a single immediate check.
        priority = (-4 if last is None and not force_recheck else
                    -3 if entry["status"] == "SOURCE_ORDER_CONFLICT" else
                    -2 if public_due or (force_recheck and last) else
                    -1 if bsd_id_due else 0 if alias_due else 1)
        candidates.append((priority, last or visit or datetime.min.replace(tzinfo=timezone.utc),
                           kickoff, key))

    # Coverage invariant: never-consulted eligible games lead every retry tier.
    # Research hints only sort within a tier and may never starve first checks.
    # Research hints only reorder eligible candidates WITHIN the same priority
    # tier; a new retry cannot leapfrog source-order/public-evidence review.
    # A game remains subject to the existing 3h grace and 4h cooldown.
    candidates.sort(key=lambda candidate: (
        candidate[0], -priority_hints.get(candidate[3], 0),
        candidate[1], candidate[2], candidate[3]))
    selected_keys = [item[3] for item in candidates[:max_checks]]
    deferred_keys = [item[3] for item in candidates[max_checks:]]
    queue_plan = {
        "eligible": len(candidates),
        "selected": len(selected_keys),
        "deferred_by_capacity": len(deferred_keys),
        "never_checked_eligible": sum(utc(entries[item[3]].get("evidence_checked_at" if evidence_retry else "checked_at")) is None for item in candidates),
        "never_checked_deferred": sum(utc(entries[key].get("evidence_checked_at" if evidence_retry else "checked_at")) is None for key in deferred_keys),
        "selected_keys": selected_keys,
        "deferred_keys": deferred_keys[:100],
        "retry_policy": ("V7: only changed authenticated snapshots count; 4h/12h/24h" if evidence_retry else "4h after 1-5 attempts; 12h after 6-9; 24h after 10+"),
    }
    attempts = 0
    for _, _, _, key in candidates[:max_checks]:
        row = entries[key]
        signal = {"match_key": key, **{field: row[field] for field in ("home", "away", "kickoff_utc")}}
        found = {}
        reasons = {}
        if key in source_order_keys:
            reasons["sportscore"] = "quarantined_source_not_reused"
        providers = [("bsd", bsd_lookup), ("thesportsdb", tsdb_lookup)]
        if espn_lookup is not None:
            providers.append(("espn", espn_lookup))
        if sportscore_lookup is not None and key not in source_order_keys:
            providers.append(("sportscore", sportscore_lookup))
        if fotmob_lookup is not None:
            providers.append(("fotmob", fotmob_lookup))
        if api_football_lookup is not None:
            providers.append(("api_football", api_football_lookup))
        if goal_lookup is not None:
            providers.append(("goal", goal_lookup))
        if openfoot_lookup is not None:
            providers.append(("openfoot", openfoot_lookup))
        if ((key in source_order_keys and key in REVIEWED_PUBLIC_FT) or
                (key in REVIEWED_PENDING_FT and
                 (original.get(key) or {}).get("status") in ("PENDING", "PROVIDER_ERROR"))):
            providers.append(("reviewed_public", verified_public_ft))
        for provider, lookup in providers:
            try:
                candidate, reason = lookup(signal)
                found[provider] = _validate_result(candidate, key) if candidate is not None else None
                reasons[provider] = ("invalid_provider_result" if candidate is not None and found[provider] is None
                                     else _safe_reason(reason))
            except Exception:
                found[provider] = None
                reasons[provider] = "provider_unavailable"  # never expose credentials/URLs
        attempts += 1
        stamp = now.isoformat(timespec="seconds")
        snapshots = {}
        if evidence_retry:
            # Record a complete authenticated date list only when its score-free
            # signature changed for THIS match's kickoff window.
            for provider, lookup in providers:
                if provider in ("api_football", "goal", "openfoot"):
                    snap = evidence_fingerprint(lookup, provider, signal)
                    old = (row.get("examined_against") or {}).get(provider) or {}
                    if snap is not None and snap["fingerprint"] != old.get("fingerprint"):
                        snapshots[provider] = {**snap, "observed_at": stamp}
        effective = (not evidence_retry or bool(snapshots) or
                     any(value is not None for value in found.values()) or
                     any(name == "reviewed_public" for name, _ in providers))
        if evidence_retry:
            row["queue_visited_at"] = stamp
            if snapshots:
                row.setdefault("examined_against", {}).update(snapshots)
            if effective:
                row["evidence_checked_at"] = stamp
                row["evidence_attempts"] = int(row.get("evidence_attempts", 0)) + 1
        if effective:
            row["checked_at"] = stamp
            row["lookup_source_version"] = max(int(row.get("lookup_source_version", 0)), source_version)
        if key in SPORTSCORE_REVIEWED:
            row["reviewed_alias_check_version"] = 1
        if key in REVIEWED_BSD_FIXTURES:
            row["reviewed_bsd_id_check_version"] = 1
        if any(name == "reviewed_public" for name, _ in providers):
            row["reviewed_public_ft_check_version"] = 1
        if effective:
            row["attempts"] = int(row.get("attempts", 0)) + 1
        if evidence_retry:
            # Never erase the last meaningful GOAL/OpenFoot/API finding with a
            # disabled, deferred or failed adapter invocation.
            meaningful = {p: why for p, why in reasons.items()
                          if p in snapshots or found.get(p) is not None or p == "reviewed_public"}
            row["provider_reasons"] = {**(row.get("provider_reasons") or {}), **meaningful}
        else:
            row["provider_reasons"] = reasons
        if reasons.get("goal") in GOAL_ID_RECHECK_EVIDENCE:
            row["goal_ft_last_evidence"] = {
                "reason": reasons["goal"],
                "observed_at": now.isoformat(timespec="seconds"),
            }
        # Counters mean adapter invocations, not necessarily remote HTTP calls:
        # adapters may use day caches or return an unsupported-competition reason.
        history = row.setdefault("provider_attempts", {})
        for provider, _ in providers:
            if evidence_retry and provider not in snapshots and found.get(provider) is None:
                continue
            old = history.get(provider, {})
            history[provider] = {
                "invocations": int(old.get("invocations", 0)) + 1,
                "first_at": old.get("first_at") or now.isoformat(timespec="seconds"),
                "last_at": now.isoformat(timespec="seconds"),
                "last_reason": reasons[provider],
                "confirmed": int(old.get("confirmed", 0)) + int(found[provider] is not None),
            }
        confirmed = [(name, found[name]) for name, _ in providers if found[name] is not None]
        collisions = [
            name for name, evidence in confirmed
            if (eid := event_id(name, evidence["source"]))
            and claimed_ids.get((name, eid), set()) - {key}
        ]
        scores = {(item["home_goals"], item["away_goals"]) for _, item in confirmed}
        if collisions:
            row["status"] = "PENDING"
            row["reason"] = "provider_event_id_collision_review"
            row.pop("result", None)
        elif len(scores) > 1:
            row["status"] = ("SOURCE_ORDER_CONFLICT" if key in source_order_keys
                             else "SCORE_CONFLICT")
            row["reason"] = ("independent_sources_disagree_manual_review"
                             if key in source_order_keys else
                             "provider_score_conflict_manual_review")
            row.pop("result", None)
            # Any disagreement, including ESPN vs BSD, quarantines the score.
        elif confirmed:
            selected = confirmed[0][1]  # provider priority: BSD, TSDB, ESPN
            names = [name for name, _ in confirmed]
            row["status"] = "FINAL"
            row["verified_provider_sources"] = {
                name: {"source": evidence["source"],
                       "identity_match": evidence.get("identity_match", "EXACT")}
                for name, evidence in confirmed
            }
            for name, evidence in confirmed:
                eid = event_id(name, evidence["source"])
                if eid:
                    claimed_ids.setdefault((name, eid), set()).add(key)
            row["result"] = {"home_goals": selected["home_goals"],
                             "away_goals": selected["away_goals"],
                             "source": selected["source"],
                             "evidence": ("_and_".join(names) if len(names)>1 else names[0]+"_only")}
            methods = sorted({item.get("identity_match", "EXACT") for _, item in confirmed})
            if methods != ["EXACT"]:
                row["result"]["identity_match"] = "+".join(methods)
            if key in REVIEWED_PENDING_FT and "reviewed_public" in names:
                row["reviewed_public_resolution"] = {
                    "method": "reviewed_two_independent_public_ft",
                    "verified_at_utc": now.isoformat(timespec="seconds"),
                    "corroboration_urls": public_evidence_urls(key),
                }
            if key in source_order_keys:
                row["source_order_resolution"] = {
                    "method": ("reviewed_two_independent_public_ft"
                               if "reviewed_public" in names else
                               "independent_non_sportscore_90m_ft"),
                    "verified_by": names,
                    "verified_at_utc": now.isoformat(timespec="seconds"),
                    "corroboration_urls": (public_evidence_urls(key)
                                          if "reviewed_public" in names else []),
                }
                row["reason"] = "independent_ft_resolved_source_order_conflict"
            else:
                row["reason"] = "ft_recorded_with_source"
        else:
            if key in source_order_keys:
                row["status"] = "SOURCE_ORDER_CONFLICT"
                row["reason"] = "sportscore_source_url_reverses_home_away"
            else:
                if effective:
                    row["status"] = "PROVIDER_ERROR" if any(
                        r in ("provider_unavailable", "invalid_provider_result") for r in reasons.values()
                    ) else "PENDING"
                    row["reason"] = "no_verified_ft_yet"
            row.pop("result", None)

    # Distinguish not-started matches from real provider gaps. The "unverified"
    # total includes future fixtures and must never be called an overdue backlog.
    timing = Counter()
    for key in games:
        row = entries[key]
        kickoff = utc(row.get("kickoff_utc"))
        if row["status"] == "FINAL":
            timing["FINAL_RECORDED"] += 1
        elif kickoff is None:
            timing["IDENTITY_UNKNOWN"] += 1
        elif now < kickoff:
            timing["FUTURE"] += 1
        elif now < kickoff + DELAY:
            timing["IN_3H_GRACE"] += 1
        elif row["status"] in ("SCORE_CONFLICT", "IDENTITY_CONFLICT", "INSUFFICIENT_IDENTITY", "SOURCE_ORDER_CONFLICT"):
            timing["BLOCKED_REVIEW"] += 1
        elif row["status"] == "EXPIRED_UNVERIFIED":
            timing["EXPIRED"] += 1
        elif not row.get("evidence_checked_at" if evidence_retry else "checked_at"):
            timing["ELIGIBLE_NEVER_QUERIED"] += 1
        elif key in REVIEWED_BSD_FIXTURES and row.get("reviewed_bsd_id_check_version") != 1:
            timing["ELIGIBLE_REVIEWED_BSD_ID"] += 1
        elif key in SPORTSCORE_REVIEWED and row.get("reviewed_alias_check_version") != 1:
            timing["ELIGIBLE_REVIEWED_ALIAS"] += 1
        elif int(row.get("lookup_source_version", 0)) < LOOKUP_SOURCE_VERSION:
            timing["ELIGIBLE_SOURCE_UPGRADE"] += 1
        elif utc(row.get("evidence_checked_at" if evidence_retry else "checked_at")) and now < utc(row["evidence_checked_at" if evidence_retry else "checked_at"]) + retry_wait(row):
            timing["ELIGIBLE_COOLDOWN"] += 1
        else:
            timing["ELIGIBLE_RETRY_DUE"] += 1

    counts = Counter(row.get("status", "UNKNOWN") for key, row in entries.items() if key in games)
    # Do not publish private original channel content; all matches are public fixtures.
    rows = []
    for key, game in sorted(games.items(), key=lambda kv: (kv[1].get("kickoff_utc") or "", kv[0]), reverse=True)[:500]:
        row = entries[key]
        record = {"match_key": key, "home": row.get("home"), "away": row.get("away"),
                  "kickoff_utc": row.get("kickoff_utc"), "status": row["status"],
                  "evidence": (row.get("result") or {}).get("evidence"),
                  "reason": row.get("reason"),
                  "last_checked_at": row.get("evidence_checked_at" if evidence_retry else "checked_at"),
                  "legacy_last_checked_at": row.get("checked_at") if evidence_retry else None,
                  "evidence_attempts": row.get("evidence_attempts", 0),
                  "observed_alerts": row.get("observed_alerts", 0)}
        if row["status"] == "FINAL":
            record["home_goals"] = row["result"]["home_goals"]
            record["away_goals"] = row["result"]["away_goals"]
            record["source"] = row["result"]["source"]
        rows.append(record)
    report = {
        "schema_version": SCHEMA, "status": STATUS,
        "universe": "every distinct match_key in H1 alerts and V4 market logs, including non-H1 signals",
        "matches": len(games), "h1_signals_count_in_state": len(state.get("signals", [])),
        "h1_alerts_count": len(state["alerts"]), "invalid_source_rows": input_errors,
        "source_only_v4_matches": sum("H1_ALERT" not in g["sources"] for g in games.values()),
        "status_counts": dict(sorted(counts.items())),
        "timing_counts": dict(sorted(timing.items())),
        "reviewed_alias_catalog_matches": sum(key in SPORTSCORE_REVIEWED for key in games),
        "reviewed_bsd_id_catalog_matches": sum(key in REVIEWED_BSD_FIXTURES for key in games),
        "final_recorded": counts["FINAL"], "unverified": len(games) - counts["FINAL"],
        "pending_due_checks": max(0, len(candidates) - attempts),
        "ft_queue": queue_plan,
        "v6_ft_priority": {
            "mode": "SAME_REVIEW_TIER_ONLY_NO_EXTRA_API",
            "hinted_eligible": sum(key in priority_hints for *_, key in candidates),
            "hinted_selected": sum(key in priority_hints for *_, key in candidates[:max_checks]),
            "budget": max_checks,
            "hints_do_not_override": ["3h grace", "4h cooldown", "source order quarantine"],
        },
        "last_updated_at": (now.isoformat(timespec="seconds")
                            if entries != original else previous.get("last_updated_at")),
        "displayed_matches": len(rows), "matches_omitted_from_display": max(0, len(games)-len(rows)),
        "games": rows,
        "limitations": [
            "A missing FT is not a lost wager or proof about goals.",
            "A single provider FT is identified as single-source, not independent cross-verification.",
            "Unmatched, conflicting, postponed and ambiguous fixtures remain unverified.",
            "SportScore results with a provably reversed home-away URL are quarantined.",
            "No betting ROI or predictive accuracy is computed; matches are the unit of analysis.",
        ],
    }
    report["source_order_audit"] = {
        "quarantined_identified": len(source_order_keys),
        "recovered_with_independent_ft": sum(
            entries[key]["status"] == "FINAL" for key in source_order_keys),
        "remaining_quarantined": sum(
            entries[key]["status"] == "SOURCE_ORDER_CONFLICT" for key in source_order_keys),
        "cases": [
            {"match_key": key,
             "home": entries[key]["home"], "away": entries[key]["away"],
             "status": entries[key]["status"],
             "reason": entries[key].get("reason"),
             "checked_at": entries[key].get("checked_at"),
             "provider_reasons": entries[key].get("provider_reasons", {}),
             "recovered_from": (entries[key].get("source_order_resolution") or {}).get("verified_by", [])}
            for key in sorted(source_order_keys)
        ],
    }
    return {"schema_version": SCHEMA, "matches": entries,
            "last_updated_at": report["last_updated_at"]}, report, attempts
