"""Read-only V4 vs legacy audit. No imports from H1 betting or collection code."""
from __future__ import annotations
from .lab_archive import monthly_paths

import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

# First V4 code merge into main (59d761bd); not the time of old fixture rows.
CUTOVER = "2026-10-27T16:40:50+00:00"
FIELDS = {
    "total": ("line", "over_price", "under_price"),
    "asian_handicap": ("line", "home_price", "away_price"),
    "one_x_two": ("1", "X", "2"),
}
SIDES = ("before", "after")
PROVENANCE_REVISION = "v4-provenance-1"
FAMILIES = ("total", "1x2")


def clopper_pearson_lower(successes, trials, alpha=0.05):
    """Exact one-sided lower confidence bound, binomial observations (not fields).

    For k=n, P(X=n|p)=p**n and the lower bound is alpha**(1/n).
    The general k<n case uses a stable log-binomial survival tail.
    """
    if not isinstance(trials, int) or not isinstance(successes, int) or not 0 <= successes <= trials:
        raise ValueError("invalid binomial counts")
    if not 0 < alpha < 1:
        raise ValueError("invalid alpha")
    if not trials or not successes:
        return None if not trials else 0.0
    if successes == trials:
        return alpha ** (1.0 / trials)

    def tail(p):
        if p <= 0: return 0.0
        if p >= 1: return 1.0
        values = [(math.lgamma(trials+1)-math.lgamma(j+1)-math.lgamma(trials-j+1)
                   + j*math.log(p) + (trials-j)*math.log1p(-p))
                  for j in range(successes,trials+1)]
        greatest = max(values)
        return math.exp(greatest) * sum(math.exp(v-greatest) for v in values)

    low,high=0.0,successes/trials
    for _ in range(44):
        mid=(low+high)/2
        if tail(mid) >= alpha: high=mid
        else: low=mid
    return (low+high)/2



def instant(value):
    if not isinstance(value, str):
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except ValueError:
        return None


def numeric(value, field):
    if isinstance(value, bool) or value is None:
        return None
    try:
        v = float(value.replace(",", ".") if isinstance(value, str) else value)
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(v):
        return None
    if field == "line":
        return v if abs(v * 4 - round(v * 4)) < 1e-7 else None
    return v if 1 < v < 1000 else None


def format_eligible(item):
    if not isinstance(item, dict):
        return False
    classes = item.get("line_classes") or []
    mentioned = item.get("markets_mentioned") or []
    if any(m in ("total", "1x2", "asian_handicap") for m in mentioned):
        return True
    if any(isinstance(c, str) and c.startswith(("HDR_TOTAL", "HDR_1X2", "HDR_AH")) for c in classes):
        return True
    # An alert-shaped but unclassified message must be visible in coverage.
    return "VS" in classes and "CLOCK" in classes and any(
        isinstance(c, str) and c.startswith("WAS:") for c in classes
    ) and any(isinstance(c, str) and c.startswith("NOW:") for c in classes)


def index_records(rows, source, issues):
    indexed = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("event_id"), str) or not row["event_id"]:
            issues.append({"type": "missing_event_id", "source": source})
            continue
        key = row["event_id"]
        if key in indexed:
            issues.append({"type": "duplicate_event_id", "source": source,
                           "event_id": key, "conflicting": indexed[key] != row})
            continue  # deterministic first occurrence; duplicates remain visible
        indexed[key] = row
    return indexed


def legacy_value(item, market, field, side):
    if market == "total":
        prefix = {"line": "total", "over_price": "over", "under_price": "under"}[field]
        return item.get(prefix + "_" + side)
    if market == "one_x_two":
        return ((item.get("one_x_two") or {}).get(field) or {}).get(side)
    source = (item.get("asian_handicap") or {}).get(side) or {}
    return source.get({"line": "line", "home_price": "home_odds",
                       "away_price": "away_odds"}[field])


def v4_value(item, market, field, side):
    market_data = (item.get("markets") or {}).get(market)
    if not isinstance(market_data, dict):
        return None
    if market == "one_x_two":
        return (market_data.get(field) or {}).get(side)
    return (market_data.get(side) or {}).get(field)


def expected_markets(item):
    kind = item.get("market")
    if kind == "total":
        return ("total",)
    if kind == "1x2":
        return ("one_x_two", "asian_handicap", "total")
    return ()


def audit(state, formats, markets, *, now=None, source_commit="unknown",
          source_errors=None, log_evidence=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now requires timezone")
    cutover = instant(CUTOVER)
    end = cutover + timedelta(hours=24)
    issues = list(source_errors or [])
    legacy = index_records(state.get("alerts", []), "legacy", issues)
    format_index = index_records(formats, "formats", issues)
    v4 = index_records(markets, "v4", issues)
    eligible = set(k for k, v in legacy.items() if v.get("market") in ("total", "1x2"))
    eligible |= {k for k, v in format_index.items() if format_eligible(v)}

    phases = {"historical": [], "first_24h": [], "after_24h": [], "unknown_time": []}
    for eid in sorted(eligible):
        record = legacy.get(eid) or format_index.get(eid)
        observed = instant(record.get("observed_at"))
        if observed is None:
            phase = "unknown_time"
            issues.append({"type": "invalid_observed_at", "event_id": eid})
        elif observed < cutover:
            phase = "historical"
        elif observed < end:
            phase = "first_24h"
        else:
            phase = "after_24h"
        phases[phase].append(eid)
    active_ids = set(phases["first_24h"] + phases["after_24h"])
    stats = {phase: {market: {field + "_" + side: dict(
        legacy_available=0, compared=0, matched=0, mismatch=0,
        missing_v4=0, invalid_v4=0, legacy_missing_or_invalid=0)
        for field in FIELDS[market] for side in SIDES}
        for market in FIELDS} for phase in phases}

    cases = []
    for eid in sorted(eligible):
        old, new, fmt = legacy.get(eid), v4.get(eid), format_index.get(eid)
        phase = next(p for p, arr in phases.items() if eid in arr)
        problems = []
        def flag(code, **extra):
            issue = {"type": code, "event_id": eid, "phase": phase, **extra}
            issues.append(issue)
            problems.append(issue)
        if not old:
            flag("missing_legacy", legacy_parsed=fmt.get("legacy_parsed") if fmt else None)
        if not new:
            flag("missing_v4")
        if fmt and not fmt.get("legacy_parsed") and not old:
            flag("unrecognized_legacy_format")
        if old and not old.get("match_key"):
            flag("missing_legacy_match_key")
        if new and not new.get("match_key"):
            flag("missing_v4_match_key")
        if new and phase in ("first_24h", "after_24h"):
            sources = new.get("identity_source")
            if not isinstance(sources, dict):
                flag("identity_provenance_unverified")
            else:
                for k in ("match_key", "kickoff_utc"):
                    if sources.get(k) in ("legacy_fallback", "missing"):
                        flag("identity_inherited_or_missing", field=k, source=sources.get(k))
                    elif sources.get(k) not in (("url_match", "telegram_teams_kickoff") if k == "match_key" else ("telegram_clock",)):
                        flag("identity_provenance_unverified", field=k)
            if new.get("parser_revision") != PROVENANCE_REVISION:
                flag("parser_revision_unverified")
            if not new.get("parser_commit"):
                flag("parser_commit_unverified")
            if new.get("field_source") != "telegram_explicit_rows":
                flag("field_provenance_unverified")
        if old and new:
            if old.get("match_key") and new.get("match_key") != old["match_key"]:
                flag("match_key_mismatch", legacy=old["match_key"], v4=new.get("match_key"))
            if old.get("kickoff_utc") and instant(old.get("kickoff_utc")) != instant(new.get("kickoff_utc")):
                flag("kickoff_mismatch", legacy=old.get("kickoff_utc"), v4=new.get("kickoff_utc"))
            if new.get("schema_version") != 4:
                flag("invalid_v4_schema", observed=new.get("schema_version"))
            if new.get("trigger_market") != old.get("market"):
                flag("trigger_market_mismatch", legacy=old.get("market"),
                     v4=new.get("trigger_market"))
        if old:
            for market in expected_markets(old):
                new_market = (new.get("markets") or {}).get(market) if new else None
                available = False
                for field in FIELDS[market]:
                    for side in SIDES:
                        label = field + "_" + side
                        counts = stats[phase][market][label]
                        old_raw = legacy_value(old, market, field, side)
                        old_val = numeric(old_raw, "line" if field == "line" else "price")
                        if old_val is None:
                            counts["legacy_missing_or_invalid"] += 1
                            flag("legacy_field_unavailable", market=market, field=label,
                                 reason="missing" if old_raw is None else "invalid")
                            continue
                        available = True
                        counts["legacy_available"] += 1
                        raw = v4_value(new, market, field, side) if new else None
                        if raw is None:
                            counts["missing_v4"] += 1
                            flag("missing_field", market=market, field=label)
                            continue
                        val = numeric(raw, "line" if field == "line" else "price")
                        if val is None:
                            counts["invalid_v4"] += 1
                            flag("invalid_v4_field", market=market, field=label)
                            continue
                        counts["compared"] += 1
                        if math.isclose(old_val, val, abs_tol=1e-8, rel_tol=0):
                            counts["matched"] += 1
                        else:
                            counts["mismatch"] += 1
                            flag("field_mismatch", market=market, field=label,
                                 legacy=old_val, v4=val)
                if available and not isinstance(new_market, dict):
                    flag("rejected_or_missing_table", market=market)
        if new and old:
            unexpected = set(new.get("markets") or {}) - set(expected_markets(old))
            for market in sorted(unexpected):
                flag("unexpected_v4_market", market=market)
        if problems:
            cases.append({"event_id": eid, "phase": phase,
                          "legacy_market": old.get("market") if old else None,
                          "problems": problems})
    markets_by_phase = {}
    for phase, market_counts in stats.items():
        summary = {}
        for market, fields in market_counts.items():
            total = Counter()
            for entry in fields.values():
                total.update(entry)
                entry["agreement_pct"] = round(100 * entry["matched"] / entry["compared"], 2) if entry["compared"] else None
                entry["complete_pct"] = round(100 * entry["matched"] / entry["legacy_available"], 2) if entry["legacy_available"] else None
            summary[market] = {"fields": fields, "totals": dict(total),
                 "agreement_pct": round(100 * total["matched"] / total["compared"], 2) if total["compared"] else None,
                 "complete_pct": round(100 * total["matched"] / total["legacy_available"], 2) if total["legacy_available"] else None}
        markets_by_phase[phase] = summary
    by_market = markets_by_phase["first_24h"]
    def coverage(ids):
        have = sum(eid in v4 for eid in ids)
        return {"eligible": len(ids), "captured": have, "missing": len(ids) - have,
                "pct": round(100 * have / len(ids), 2) if ids else None}
    window = coverage(phases["first_24h"])
    active = coverage(sorted(active_ids))
    missing = [k for k in sorted(active_ids) if k not in v4]
    issue_counts_by_phase = {
        p: dict(Counter(x["type"] for x in issues if x.get("phase") == p))
        for p in phases
    }
    issue_counts_by_phase["source"] = dict(
        Counter(x["type"] for x in issues if x.get("phase") is None))
    errors_window = [p for p in issues if p.get("phase") == "first_24h"]
    clean_compare = all(
        x["mismatch"] == x["missing_v4"] == x["invalid_v4"] == 0
        for market in by_market.values() for x in market["fields"].values()
    )
    log_evidence = log_evidence or {"status": "unverified", "reason": "No complete 24h collection-log evidence"}
    elapsed = now >= end

    # Each message is ONE independent observation; AH and Total within an
    # 1x2 notification must never count as two extra samples.
    window_problems = {p.get("event_id") for p in errors_window if p.get("event_id")}
    family_members = {x: [] for x in FAMILIES}
    family_members["unclassified"] = []
    for eid in phases["first_24h"]:
        old = legacy.get(eid)
        fmt = format_index.get(eid) or {}
        mentioned = fmt.get("markets_mentioned") or []
        family = old.get("market") if old else (
            "1x2" if "1x2" in mentioned else "total" if "total" in mentioned else "unclassified")
        family_members[family if family in family_members else "unclassified"].append(eid)
    statistical = {}
    for family, ids in family_members.items():
        captured = sum(eid in v4 for eid in ids)
        independently_complete = sum(eid in v4 and eid not in window_problems for eid in ids)
        statistical[family] = {
            "messages": len(ids), "captured": captured,
            "independently_complete": independently_complete,
            "capture_lower_95": round(clopper_pearson_lower(captured, len(ids)), 6)
                                if ids else None,
            "strict_lower_95": round(clopper_pearson_lower(independently_complete, len(ids)), 6)
                               if ids else None,
        }
    required = all(statistical[x]["messages"] and statistical[x]["strict_lower_95"] >= 0.99
                   for x in FAMILIES) and statistical["unclassified"]["messages"] == 0
    integrity_errors = [p for p in issues if p.get("type") in
                        ("invalid_observed_at", "invalid_jsonl", "jsonl_read_error", "missing_event_id")
                        or (p.get("type") == "duplicate_event_id" and p.get("conflicting"))]
    # Golden source messages must be verified independently by a human against
    # original Telegram messages. No such approval can be inferred from H1/V4.
    golden = {"status": "NOT_VERIFIED", "manually_verified": 0,
              "reason": "No independently signed and checked golden corpus"}
    gates = {
        "window_elapsed": elapsed,
        "minimum_evidence": bool(required),
        "coverage_99": window["pct"] is not None and window["pct"] >= 99,
        "field_agreement_100": clean_compare and not errors_window,
        "independent_identity": all(
            eid in v4 and (v4[eid].get("identity_source") or {}).get("match_key")
            in ("url_match", "telegram_teams_kickoff") and
            (v4[eid].get("identity_source") or {}).get("kickoff_utc") == "telegram_clock"
            for eid in phases["first_24h"]),
        "data_integrity": not integrity_errors,
        "golden_set_verified": False,
        "logs_clean_24h": log_evidence.get("status") == "verified_24h_clean",
    }
    report_status = "PASS" if all(gates.values()) else (
        "FAIL" if log_evidence.get("status") in ("v4_errors_detected", "errors_detected")
        or bool(integrity_errors)
        or (elapsed and required and
            (not gates["coverage_99"] or not gates["field_agreement_100"]))
        else "PENDING")
    # Historical V4 absence is expected before deployment. Keep FULL counters,
    # but publish only a bounded historical detail sample to avoid repeatedly
    # committing hundreds of redundant legacy-only issues every five minutes.
    historic_issues = [p for p in issues if p.get("phase") == "historical"]
    live_issues = [p for p in issues if p.get("phase") != "historical"]
    visible_issues = live_issues + historic_issues[:24]
    historic_cases = [p for p in cases if p.get("phase") == "historical"]
    live_cases = [p for p in cases if p.get("phase") != "historical"]
    visible_cases = live_cases + historic_cases[:8]
    return {
        "schema_version": 1, "status": report_status, "source_commit": source_commit,
        "generated_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "cutover_utc": CUTOVER, "first_24h_end_utc": end.isoformat(timespec="seconds"),
        "phase_coverage": {k: coverage(v) for k, v in phases.items()},
        "post_cutover_coverage": active, "markets": by_market,
        "statistical_evidence": {"method":"one-sided exact Clopper-Pearson 95%",
                                 "unit":"Telegram message", "families":statistical,
                                 "threshold":0.99},
        "golden_set": golden,
        "markets_by_phase": markets_by_phase,
        "legacy_alerts": len(legacy), "format_events": len(format_index),
        "v4_observations": len(v4), "active_missing_v4_ids": missing,
        "problem_events": visible_cases, "issues": visible_issues,
        "total_issue_count": len(issues),
        "historical_issue_details_omitted": max(0, len(historic_issues) - 24),
        "historical_event_details_omitted": max(0, len(historic_cases) - 8),
        "issue_counts": dict(Counter(p["type"] for p in issues)),
        "issue_counts_by_phase": issue_counts_by_phase,
        "log_evidence": log_evidence, "acceptance_gates": gates,
        "quality_dimensions": quality_dimensions(state, markets, now=now, phases=phases),
        "limitations": [
            "Only Telegram alert observations are measured, not all market moves",
            "Historical formats before V4 deployment are excluded from live coverage denominator",
            "One 1x2 message contains correlated 1x2, AH and Total tables, not three independent alerts",
            "At least approximately 299 independently complete messages per family are needed for 99% lower 95% confidence with zero failures",
            "The source of identity and parser revision may be unverified for records captured before provenance support",
            "No 24h clean-log claim without evidence from all collection runs",
            "Field agreement excludes invalid or absent values; complete_pct includes those failures",
            "A manual golden set of original Telegram messages is required before any statistical certification",
        ],
    }


# ---------------------------------------------------------------------------
# Separate quality dimensions (informational; official gates are unchanged).

# Main merge of the parser change that anchored Was/Now and 1X2 rows (#16).
# parser_commit records the collector checkout HEAD, not the parser code, so
# periods are assigned by observation time (approximate by one collect cycle).
PARSER_PERIODS = (
    ("v4_initial_no_provenance", CUTOVER),
    ("v4_provenance_1", "2026-10-27T17:34:46+00:00"),
    ("v4_provenance_1_anchored_rows", "2026-10-27T19:56:41+00:00"),
)
SIMPLE_PCT_TOLERANCE = 0.2


def parser_period(row):
    when = instant((row or {}).get("observed_at"))
    if when is None:
        return "unknown_time"
    digest = (row or {}).get("parser_source_sha256")
    if isinstance(digest, str) and len(digest) == 64:
        return "v4_source_" + digest[:12]
    if not (row or {}).get("parser_revision"):
        return "v4_initial_no_provenance" if when >= instant(CUTOVER) else "pre_cutover"
    # A record carrying a revision is at least v4_provenance_1, whatever the
    # commit clock says; later code changes are split by main merge time.
    label = "v4_provenance_1"
    for name, start in PARSER_PERIODS[2:]:
        if when >= instant(start):
            label = name
    return label


def message_agreement(old, new):
    """Per-message value agreement for the tables that the H1 record has."""
    compared = agreed = 0
    complete = True
    for market in expected_markets(old):
        for field in FIELDS[market]:
            for side in SIDES:
                ov = numeric(legacy_value(old, market, field, side),
                             "line" if field == "line" else "price")
                if ov is None:
                    continue
                nv = numeric(v4_value(new, market, field, side) if new else None,
                             "line" if field == "line" else "price")
                if nv is None:
                    complete = False
                    continue
                compared += 1
                agreed += math.isclose(ov, nv, abs_tol=1e-8, rel_tol=0)
    return compared, agreed, complete and compared > 0 and agreed == compared


def bound(k, n):
    return round(clopper_pearson_lower(k, n), 6) if n else None


def quality_dimensions(state, markets, *, now, phases):
    legacy = {a.get("event_id"): a for a in state.get("alerts", []) if isinstance(a, dict)}
    v4 = {m.get("event_id"): m for m in markets if isinstance(m, dict)}
    window = phases["first_24h"]
    family = lambda eid: (legacy.get(eid) or {}).get("market") or "unclassified"

    agreement = {}
    for eid in window:
        old, new = legacy.get(eid), v4.get(eid)
        if not old or not new:
            continue
        compared, agreed, ok = message_agreement(old, new)
        for key in (("family", family(eid)), ("period", parser_period(new) + ":" + family(eid))):
            row = agreement.setdefault(key, {"messages": 0, "messages_all_fields_agree": 0,
                                             "fields_compared": 0, "fields_agree": 0})
            row["messages"] += 1
            row["messages_all_fields_agree"] += ok
            row["fields_compared"] += compared
            row["fields_agree"] += agreed
    for row in agreement.values():
        row["lower_95_by_message"] = bound(row["messages_all_fields_agree"], row["messages"])

    independent, missing_prov = [], []
    for eid in window:
        src = (v4.get(eid) or {}).get("identity_source")
        if (isinstance(src, dict) and src.get("match_key") in ("url_match", "telegram_teams_kickoff")
                and src.get("kickoff_utc") == "telegram_clock"):
            independent.append(eid)
        else:
            missing_prov.append(eid)

    prov_times = sorted(instant(v4[e]["observed_at"]) for e in window
                        if e in v4 and v4[e].get("parser_revision") == PROVENANCE_REVISION
                        and instant(v4[e].get("observed_at")))
    start = prov_times[0] if prov_times else None
    prov_ids = [e for e in phases["first_24h"] + phases["after_24h"]
                if start and instant((legacy.get(e) or {}).get("observed_at")) and
                start <= instant(legacy[e]["observed_at"]) < start + timedelta(hours=24)]
    prov_ok = [e for e in prov_ids if e in v4 and message_agreement(legacy[e], v4[e])[2]]
    prov_ident = [e for e in prov_ids if e in independent or (
        e in v4 and (v4[e].get("identity_source") or {}).get("kickoff_utc") == "telegram_clock"
        and (v4[e].get("identity_source") or {}).get("match_key") in ("url_match", "telegram_teams_kickoff"))]

    pct_rows = []
    for m in v4.values():
        t = m.get("trigger") or {}
        b, a, p = t.get("before"), t.get("after"), t.get("pct")
        if t.get("market") == "1x2" and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                             for x in (b, a, p)) and b:
            pct_rows.append((p, 100 * (a - b) / b))
    simple = sum(abs(p - s) <= SIMPLE_PCT_TOLERANCE for p, s in pct_rows)

    def table(kind):
        return {k[1]: v for k, v in sorted(agreement.items()) if k[0] == kind}
    return {
        "note": "Informational dimensions. They do not change acceptance_gates or status.",
        "collection_coverage": {
            "meaning": "Telegram alert messages in the window that have a V4 record",
            "messages": len(window), "captured": sum(e in v4 for e in window),
            "lower_95_by_message": bound(sum(e in v4 for e in window), len(window))},
        "extraction_exactness": {
            "status": "NOT_MEASURED_BY_PARSER_COMPARISON",
            "evidence_source": "docs/lab/golden-report.json (human transcriptions)",
            "reason": "Agreement between two parsers of the same text is not exactness"},
        "identity_independence": {
            "messages": len(window), "independent": len(independent),
            "unrecorded_or_inherited": len(missing_prov),
            "unrecorded_event_ids": missing_prov[:50],
            "lower_95_by_message": bound(len(independent), len(window))},
        "parser_agreement": {
            "meaning": "V4 explicit values equal to the H1 record, per message, on available fields",
            "by_family": table("family"), "by_parser_period_and_family": table("period"),
            "parser_period_assignment": "observed_at vs main merge time of parser changes; approximate",
            "caveat": "100% on available fields is not global accuracy; both parsers read the same text"},
        "human_validation": {"status": "SEE_GOLDEN_REPORT", "golden_set_verified": False},
        "movement_independence": {
            "status": "SEE_MATCH_TRAJECTORIES",
            "evidence_source": "docs/lab/match-trajectories.json",
            "reason": "1X2 and Total messages of one move are correlated; unit is the match"},
        "statistical_certification": {
            "status": "NOT_CERTIFIED",
            "requires": ["24h window elapsed", "about 299 independent messages per family with 0 failures",
                         "complete log evidence", "verified human Golden Set", "out-of-sample validation"]},
        "provenance_window": {
            "status": "INFORMATIONAL_NOT_A_GATE",
            "reason": "First 24h after the first V4 record with parser provenance; separates the "
                      "transitional records without provenance. Records are never rewritten.",
            "start_utc": start.isoformat(timespec="seconds") if start else None,
            "end_utc": (start + timedelta(hours=24)).isoformat(timespec="seconds") if start else None,
            "elapsed": bool(start and now >= start + timedelta(hours=24)),
            "transitional_messages_without_provenance": len(missing_prov),
            "messages": len(prov_ids), "captured": sum(e in v4 for e in prov_ids),
            "messages_all_fields_agree": len(prov_ok),
            "independent_identity": len(prov_ident),
            "lower_95_agreement_by_message": bound(len(prov_ok), len(prov_ids))},
        "trigger_displayed_pct": {
            "status": "FORMULA_UNVALIDATED", "use_as_predictor": False,
            "messages_with_pct": len(pct_rows),
            "matches_simple_price_change_within_0_2pp": simple,
            "min_abs_displayed_pct": min((abs(p) for p, _ in pct_rows), default=None),
            "reason": "Displayed % does not follow (after-before)/before; keep as shown only"},
    }


def read_jsonl(root, prefix):
    records, errors = [], []
    directory = root / "data" / "lab"
    for path in monthly_paths(root, prefix):
        try:
            lines = path.read_bytes().splitlines()
        except OSError as exc:
            errors.append({"type": "jsonl_read_error", "source": path.name,
                           "reason": type(exc).__name__})
            continue
        for n, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line.decode("utf-8"))
                if not isinstance(row, dict):
                    raise ValueError("row is not an object")
                records.append(row)
            except (UnicodeDecodeError, ValueError):
                errors.append({"type": "invalid_jsonl", "source": path.name, "line": n})
    return records, errors


def generate(root, *, now=None, source_commit="unknown", log_evidence=None):
    state = json.loads((root / "data" / "state.json").read_text(encoding="utf-8"))
    if not isinstance(state, dict) or not isinstance(state.get("alerts"), list):
        raise ValueError("Legacy state must contain an alerts list")
    formats, fe = read_jsonl(root, "formats")
    markets, me = read_jsonl(root, "markets")
    return audit(state, formats, markets, now=now, source_commit=source_commit,
                 source_errors=fe + me, log_evidence=log_evidence)
