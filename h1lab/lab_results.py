"""Independent, bounded, fail-closed FT result collection for *all* observed LAB fixtures.

Never modifies or invokes H1 result syncing. Only reuses the existing pure
provider validators (BSD, TheSportsDB) in the executable adapter.
"""
from __future__ import annotations

import copy
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

SCHEMA = 1
MAX_CHECKS_CAP = 30
DELAY = timedelta(hours=3)
RETRY = timedelta(hours=4)
HORIZON = timedelta(days=30)
STATUS = "LAB_FT_OBSERVATION_ONLY_NOT_CERTIFIED"


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
    return {"home_goals": h, "away_goals": a, "source": source}


def reconcile(state, v4rows, previous, *, now, bsd_lookup, tsdb_lookup, max_checks=20):
    """Return (new ledger, aggregate/public report, count of API-search attempts).

    Lookup callables accept {match_key,home,away,kickoff_utc} and return
    (result_or_None, diagnostic). Neither callable mutates H1 files.
    """
    if now.tzinfo is None:
        raise ValueError("now requires timezone")
    now = now.astimezone(timezone.utc)
    if not isinstance(max_checks, int) or not 0 <= max_checks <= MAX_CHECKS_CAP:
        raise ValueError("max_checks outside safe range 0..30")
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
        identity_changed_final = (row.get("status") == "FINAL"
                                  and any(old_identity[k] != identity[k] for k in identity))
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

    candidates = []
    for key in games:
        entry = entries[key]
        if entry["status"] not in ("PENDING", "PROVIDER_ERROR"):
            continue
        kickoff = utc(entry["kickoff_utc"])
        if kickoff is None:
            entry["status"] = "INSUFFICIENT_IDENTITY"
            continue
        if now > kickoff + HORIZON:
            entry["status"] = "EXPIRED_UNVERIFIED"
            entry["reason"] = "beyond_30_day_lookup_window"
            continue
        if now < kickoff + DELAY:
            continue
        last = utc(entry.get("checked_at"))
        if last and now < last + RETRY:
            continue
        candidates.append((last or datetime.min.replace(tzinfo=timezone.utc), kickoff, key))

    # Oldest attempted first; tie-break by kickoff/key to avoid starved matches.
    candidates.sort()
    attempts = 0
    for _, _, key in candidates[:max_checks]:
        row = entries[key]
        signal = {field: row[field] for field in ("match_key", "home", "away", "kickoff_utc")}
        found = {}
        reasons = {}
        for provider, lookup in (("bsd", bsd_lookup), ("thesportsdb", tsdb_lookup)):
            try:
                candidate, reason = lookup(signal)
                found[provider] = _validate_result(candidate, key) if candidate is not None else None
                reasons[provider] = ("invalid_provider_result" if candidate is not None and found[provider] is None
                                     else _safe_reason(reason))
            except Exception:
                found[provider] = None
                reasons[provider] = "provider_unavailable"  # never expose credentials/URLs
        attempts += 1
        row["checked_at"] = now.isoformat(timespec="seconds")
        row["attempts"] = int(row.get("attempts", 0)) + 1
        row["provider_reasons"] = reasons
        b, t = found["bsd"], found["thesportsdb"]
        if b and t and (b["home_goals"], b["away_goals"]) != (t["home_goals"], t["away_goals"]):
            row["status"] = "SCORE_CONFLICT"
            row["reason"] = "provider_score_conflict_manual_review"
            row.pop("result", None)
            # Do not silently pick a winning score or auto-retry conflicts.
        elif b or t:
            selected = b or t
            row["status"] = "FINAL"
            row["result"] = {"home_goals": selected["home_goals"],
                             "away_goals": selected["away_goals"],
                             "source": selected["source"],
                             "evidence": ("bsd_and_thesportsdb" if b and t else
                                          "bsd_only" if b else "thesportsdb_only")}
            row["reason"] = "ft_recorded_with_source"
        else:
            row["status"] = "PROVIDER_ERROR" if any(
                r in ("provider_unavailable", "invalid_provider_result") for r in reasons.values()
            ) else "PENDING"
            row["reason"] = "no_verified_ft_yet"
            row.pop("result", None)

    counts = Counter(row.get("status", "UNKNOWN") for key, row in entries.items() if key in games)
    # Do not publish private original channel content; all matches are public fixtures.
    rows = []
    for key, game in sorted(games.items(), key=lambda kv: (kv[1].get("kickoff_utc") or "", kv[0]), reverse=True)[:500]:
        row = entries[key]
        record = {"match_key": key, "home": row.get("home"), "away": row.get("away"),
                  "kickoff_utc": row.get("kickoff_utc"), "status": row["status"],
                  "evidence": (row.get("result") or {}).get("evidence"),
                  "reason": row.get("reason"), "last_checked_at": row.get("checked_at"),
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
        "final_recorded": counts["FINAL"], "unverified": len(games) - counts["FINAL"],
        "pending_due_checks": max(0, len(candidates) - attempts),
        "last_updated_at": (now.isoformat(timespec="seconds")
                            if entries != original else previous.get("last_updated_at")),
        "displayed_matches": len(rows), "matches_omitted_from_display": max(0, len(games)-len(rows)),
        "games": rows,
        "limitations": [
            "A missing FT is not a lost wager or proof about goals.",
            "A single provider FT is identified as single-source, not independent cross-verification.",
            "Unmatched, conflicting, postponed and ambiguous fixtures remain unverified.",
            "No betting ROI or predictive accuracy is computed; matches are the unit of analysis.",
        ],
    }
    return {"schema_version": SCHEMA, "matches": entries,
            "last_updated_at": report["last_updated_at"]}, report, attempts
