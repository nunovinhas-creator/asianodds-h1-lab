"""Read-only V4 vs legacy audit. No imports from H1 betting or collection code."""
from __future__ import annotations

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
    # Even clean latest-run logs do not establish absence of all failures over 24h.
    log_evidence = log_evidence or {"status": "unverified", "reason": "No complete 24h collection-log evidence"}
    elapsed = now >= end
    data_sufficient = window["eligible"] >= 100 and all(
        by_market[x]["totals"].get("compared", 0) > 0 for x in FIELDS
    )
    gates = {
        "window_elapsed": elapsed,
        "minimum_evidence": data_sufficient,
        "coverage_99": window["pct"] is not None and window["pct"] >= 99,
        "field_agreement_100": clean_compare and not errors_window,
        "logs_clean_24h": log_evidence.get("status") == "verified_24h_clean",
    }
    report_status = "PASS" if all(gates.values()) and not (source_errors or []) else (
        "FAIL" if log_evidence.get("status") == "errors_detected" or (
            elapsed and window["eligible"] >= 100 and
            (not gates["coverage_99"] or not gates["field_agreement_100"]))
        else "PENDING")
    return {
        "schema_version": 1, "status": report_status, "source_commit": source_commit,
        "generated_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "cutover_utc": CUTOVER, "first_24h_end_utc": end.isoformat(timespec="seconds"),
        "phase_coverage": {k: coverage(v) for k, v in phases.items()},
        "post_cutover_coverage": active, "markets": by_market,
        "markets_by_phase": markets_by_phase,
        "legacy_alerts": len(legacy), "format_events": len(format_index),
        "v4_observations": len(v4), "active_missing_v4_ids": missing,
        "problem_events": cases, "issues": issues,
        "issue_counts": dict(Counter(p["type"] for p in issues)),
        "issue_counts_by_phase": issue_counts_by_phase,
        "log_evidence": log_evidence, "acceptance_gates": gates,
        "limitations": [
            "Only Telegram alert observations are measured, not all market moves",
            "Historical formats before V4 deployment are excluded from live coverage denominator",
            "One 1x2 message contains correlated 1x2, AH and Total tables, not three independent alerts",
            "The 99% threshold with fewer than 100 real alerts is insufficient evidence",
            "No 24h clean-log claim without evidence from all collection runs",
            "Field agreement excludes invalid or absent values; complete_pct includes those failures",
        ],
    }


def read_jsonl(root, prefix):
    records, errors = [], []
    directory = root / "data" / "lab"
    for path in sorted(directory.glob(prefix + "-????-??.jsonl")):
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
