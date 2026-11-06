"""Read-only P1 A1 audit. No providers, registration, append or promotion.

Run with python -m scripts.master_brain_a1_audit --root . --source-sha SHA
--output /tmp/a1.json. The evaluation clock defaults to the published P0 clock.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from h1lab.lab_archive import monthly_paths
from h1lab.timeline import collect_timelines, read_sources, utc
from h1lab.v4_revisions import read_events
from h1lab.v6_p0_gates import ft_chronology
from h1lab.v6_readiness import measure
from h1lab.v6_science_memory import read_stream
from h1lab.v6_shadow import canonical, read_journal


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def identity_ok(timeline):
    i = timeline.get("identity") or {}
    return (len(i.get("kickoff_utc") or []) == 1
            and i.get("kickoff_consistent") and i.get("team_names_consistent")
            and not i.get("per_message_conflicts"))


def missing_reason(timeline, forecasts, revisions):
    """Recorded first sight is evidence of processing, not Telegram delivery."""
    if not identity_ok(timeline):
        return "IDENTITY_OR_KICKOFF_CONFLICT"
    ko = utc(timeline["identity"]["kickoff_utc"][0])
    if ko is None:
        return "SOURCE_WITHOUT_KICKOFF_EVIDENCE"
    if any(utc(x.get("kickoff_utc")) != ko for x in forecasts):
        return "FORECAST_KICKOFF_ALIGNMENT_CONFLICT"
    if not any(utc(e.get("observed_at")) and utc(e["observed_at"]) < ko
               for e in timeline.get("events", [])):
        return "SOURCE_WITHOUT_PREKICKOFF_EVIDENCE"
    # Historical imports establish no original arrival time.
    receipts = [r for r in revisions if r.get("kind") == "FIRST_SEEN_BY_COLLECTOR"
                and utc(r.get("known_at"))]
    if not receipts:
        return "NO_FIRST_COLLECTOR_RECORD"
    first = min(utc(r["known_at"]) for r in receipts)
    if first >= ko:
        return "FIRST_COLLECTOR_RECORD_AT_OR_AFTER_KICKOFF"
    return "PREKICKOFF_COLLECTOR_RECORD_WITHOUT_FREEZE"


def ft_rows(forecasts, evidence, registered_at, now):
    """Audit the exact forecast SHA referenced by each event, retaining all rows."""
    by_sha = {r["sha256"]: r for r in forecasts}
    latest = {x["event"]["match_key"]: x["id"] for x in evidence}
    out = []
    for row in evidence:
        e = row["event"]
        f = by_sha.get(e.get("frozen_source_sha256"))
        known = utc(f.get("known_at")) if f else None
        ko = utc(f.get("kickoff_utc")) if f else None
        checked, written = utc(e.get("ft_checked_at")), utc(row.get("written_at"))
        codes = []
        if not f or f.get("match_key") != e.get("match_key"):
            codes.append("EXACT_FORECAST_REFERENCE_MISSING_OR_WRONG_MATCH")
        if not known or not ko or not registered_at <= known < ko:
            codes.append("NOT_REGISTERED_PREKICKOFF")
        if f and (e.get("kickoff_utc") != f.get("kickoff_utc")
                  or e.get("frozen_known_at") != f.get("known_at")):
            codes.append("EVIDENCE_FORECAST_TIME_ALIGNMENT_CONFLICT")
        if not checked or not ko or checked < ko + timedelta(minutes=90):
            codes.append("NO_POST_90MIN_FT_CHECK")
        if not written or not checked or written < checked or (known and written < known):
            codes.append("FT_INGEST_BEFORE_CHECK_OR_FREEZE")
        if not written or written > now:
            codes.append("FT_INGEST_IN_FUTURE")
        if checked and checked > now:
            codes.append("FT_CHECK_IN_FUTURE")
        if e.get("state") != "CONFIRMED":
            codes.append("FT_NOT_CONFIRMED")
        if e.get("source_conflict"):
            codes.append("FT_SOURCE_CONFLICT")
        out.append({"match_key": e["match_key"], "evidence_event_id": e["event_id"],
                    "state": e.get("state"), "is_latest": latest[e["match_key"]] == row["id"],
                    "referenced_forecast_sha256": e.get("frozen_source_sha256"),
                    "frozen_known_at": f.get("known_at") if f else None,
                    "kickoff_utc": f.get("kickoff_utc") if f else None,
                    "ledger_ft_checked_at": e.get("ft_checked_at"),
                    "journal_written_at": row.get("written_at"),
                    "independently_proven_provider_checked_at": None,
                    "failure_codes": codes,
                    "chronology_status": "INVALID" if codes else "CONSISTENT_NOT_INDEPENDENTLY_PROVEN",
                    "training_or_result_eligible": False,
                    "blocked_reason": "INDEPENDENT_PROVIDER_CHRONOLOGY_NOT_ESTABLISHED"})
    return out


def rates(rows, field):
    groups = defaultdict(lambda: {"source_eligible": 0, "frozen_pre_kickoff": 0,
                                  "quarantined_or_conflicting": 0})
    for row in rows:
        for value in row[field]:
            group = groups[value]
            group["source_eligible"] += 1
            group["frozen_pre_kickoff"] += row["frozen_pre_kickoff"]
            group["quarantined_or_conflicting"] += row["quarantined_or_conflicting"]
    return {key: {**v, "ratio": v["frozen_pre_kickoff"] / v["source_eligible"],
                  "missing": v["source_eligible"] - v["frozen_pre_kickoff"]}
            for key, v in sorted(groups.items())}


def input_paths(root):
    paths = [root / x for x in ("data/state.json", "data/lab/v6-hypotheses.jsonl",
                               "docs/lab/v6-readiness.json", "docs/lab/v6-p0-gates.json")]
    for prefix in ("markets", "v4-revisions", "v6-forecasts", "v6-memory-evidence"):
        monthly = monthly_paths(root, prefix)
        if not monthly:
            raise ValueError("Missing required journal/projection: " + prefix)
        paths.extend(monthly)
    paths.extend(sorted((root / "reports/incidents").glob("**/*receipt.json")))
    return sorted(set(paths))


def audit(root, source_sha, as_of=None):
    root = Path(root).resolve()
    if len(source_sha) != 40 or any(c not in "0123456789abcdef" for c in source_sha):
        raise ValueError("Full immutable source commit SHA required")
    paths = input_paths(root)
    before = {str(p.relative_to(root)): sha256(p.read_bytes()) for p in paths}
    published = json.loads((root / "docs/lab/v6-readiness.json").read_text())
    p0 = json.loads((root / "docs/lab/v6-p0-gates.json").read_text())
    now = utc(as_of or p0["evaluation_clock"])
    if now is None:
        raise ValueError("Timezone-aware evaluation clock required")
    # Read the registration without invoking ensure_registered (which can write).
    registration_lines = (root / "data/lab/v6-hypotheses.jsonl").read_text().splitlines()
    if len(registration_lines) != 1:
        raise ValueError("Exactly one existing registration required")
    registration = json.loads(registration_lines[0])
    registration_body = {k: v for k, v in registration.items() if k != "sha256"}
    if sha256(canonical(registration_body).encode()) != registration.get("sha256"):
        raise ValueError("Registration hash mismatch")
    registered_at = utc(registration.get("registered_at"))
    if registered_at is None:
        raise ValueError("Invalid registration timestamp")
    forecasts, revisions = read_journal(root), read_events(root)
    evidence = read_stream(root, "evidence")
    alerts, markets, errors = read_sources(root)
    timelines, issues, excluded = collect_timelines(alerts, markets, source_errors=errors)
    if errors or issues or excluded:
        raise ValueError("Source timeline errors: cannot reconcile denominators")
    readiness = measure(timelines, forecasts, now)
    # Independently replay the published artifact at its own clock.
    published_replay = measure(timelines, forecasts, utc(published["generated_at"]))
    if published_replay != published:
        raise ValueError("Published readiness does not replay from source inputs")
    p0_ft = ft_chronology(forecasts, evidence, registered_at, now)
    by_match, rev_by_match, alert_by_match = defaultdict(list), defaultdict(list), defaultdict(list)
    for f in forecasts:
        by_match[f["match_key"]].append(f)
    for r in revisions:
        rev_by_match[r["snapshot"].get("match_key")].append(r)
    for a in alerts:
        alert_by_match[a.get("match_key")].append(a)
    latest_evidence = {r["event"]["match_key"]: r["event"] for r in evidence}
    first = utc(readiness["first_prospective_known_at"])
    frozen_keys = {f["match_key"] for f in forecasts
                   if utc(f.get("known_at")) and utc(f.get("kickoff_utc"))
                   and utc(f["known_at"]) < utc(f["kickoff_utc"])}
    rows, identity_exclusions = [], []
    for t in sorted(timelines, key=lambda x: x["match_key"]):
        if not identity_ok(t):
            identity_exclusions.append({"match_key": t["match_key"], "identity": t["identity"],
                                        "reason": "IDENTITY_OR_KICKOFF_CONFLICT"})
            continue
        ko = utc(t["identity"]["kickoff_utc"][0])
        if not first or not ko or not max(first, now - timedelta(days=7)) <= ko <= now:
            continue
        pre = [e for e in t["events"] if utc(e.get("observed_at")) and utc(e["observed_at"]) < ko]
        if not pre:
            continue
        key = t["match_key"]
        captured = key in frozen_keys
        revs = rev_by_match[key]
        e = latest_evidence.get(key, {})
        quarantined = e.get("state") == "QUARANTINED" or bool(e.get("source_conflict"))
        reason = None if captured else missing_reason(t, by_match[key], revs)
        rows.append({"match_key": key, "match_label": t["match_label"],
                     "kickoff_utc": ko.isoformat(), "event_ids": [x["event_id"] for x in pre],
                     "competitions": sorted({a.get("competition") or "UNKNOWN"
                                             for a in alert_by_match[key]}) or ["UNKNOWN"],
                     "markets": sorted({m for x in pre for m in x["snapshots"]}) or ["UNKNOWN"],
                     "frozen_pre_kickoff": captured, "missing_reason": reason,
                     "collector_revision_receipts": [{"revision_id": r["revision_id"],
                         "event_id": r["event_id"], "known_at": r["known_at"], "kind": r["kind"],
                         "sha256": r["sha256"]} for r in revs],
                     "first_decision_freeze": min((f["known_at"] for f in by_match[key]), default=None),
                     "latest_ft_state": e.get("state", "ABSENT"),
                     "quarantined_or_conflicting": quarantined,
                     "training_or_result_eligible": False,
                     "blocked_reasons": ([reason] if reason else [])
                         + (["QUARANTINED_OR_CONFLICTING"] if quarantined else [])
                         + ["P0_AND_INDEPENDENT_FT_VALIDATION_BLOCKED"],
                     "independent_run_receipt_reconciled": False})
    missing = [r for r in rows if not r["frozen_pre_kickoff"]]
    week = readiness["last_7_kickoff_days"]
    if (len(rows) != week["source_eligible"] or len(missing) != week["missing_count"]
            or sum(r["frozen_pre_kickoff"] for r in rows) != week["frozen_pre_kickoff"]):
        raise ValueError("Per-match counts do not reconcile")
    ft = ft_rows(forecasts, evidence, registered_at, now)
    receipts = [{"path": str(p.relative_to(root)), "receipt": json.loads(p.read_text())}
                for p in paths if p.name.endswith("receipt.json")]
    after = {str(p.relative_to(root)): sha256(p.read_bytes()) for p in paths}
    if before != after:
        raise ValueError("Input changed during audit")
    return {"schema_version": 1, "phase": "P1_A1_READ_ONLY",
            "status": "BLOCKED_PENDING_INDEPENDENT_RECEIPT_AUDIT",
            "source_commit": source_sha, "evaluation_clock": now.isoformat(),
            "cost": {"llm_calls": 0, "neurons": 0, "provider_calls": 0},
            "input_sha256": before, "source_bytes_unchanged": True,
            "published_readiness_replayed": True,
            "coverage_7d": {**week, "exact_ratio": len(rows) and (len(rows)-len(missing))/len(rows),
                            "missing_reason_counts": dict(Counter(r["missing_reason"] for r in missing))},
            "coverage_by_market": rates(rows, "markets"),
            "coverage_by_competition": rates(rows, "competitions"),
            "matches": rows, "missing_matches": missing,
            "identity_exclusions": identity_exclusions,
            "ft_p0_replay": p0_ft,
            "ft_published_reconciled": p0_ft == p0["ft_knowledge_timeline"],
            "ft_exact_reference_status_counts": dict(Counter(r["chronology_status"] for r in ft)),
            "ft_failure_counts": dict(Counter(c for r in ft for c in r["failure_codes"])),
            "ft_events": ft, "published_lineage": p0["data_lineage"],
            "observed_lineage": {"frozen_records": len(forecasts), "v4_revision_rows": len(revisions),
                                 "ft_memory_events": len(evidence)},
            "available_publication_receipts": receipts,
            "training_rows_exported": 0, "promotions": 0,
            "limitations": [
                "First collector record is processing time, not independent message delivery proof.",
                "A missing freeze with a pre-kickoff receipt needs run-log reconciliation; no cause is invented.",
                "Source coverage uses published eligibility, not all fixtures or usable model features.",
                "Market denominators overlap; one match counts once per observed pre-kickoff market.",
                "Hash chains establish snapshot consistency; commit-by-commit history remains unaudited.",
                "Available incident receipts are listed, not assigned to games without explicit evidence.",
                "No provider timestamp is independently certified; zero rows are admitted to training/results.",
                "A1 acceptance remains incomplete until independent run receipts and historical lineage are reconciled.",
            ]}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path("."))
    p.add_argument("--source-sha", required=True)
    p.add_argument("--as-of")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    root, output = args.root.resolve(), args.output.resolve()
    if output.is_relative_to(root) and not output.is_relative_to(root / "reports/master-brain-a1"):
        raise ValueError("In-repository output must stay under reports/master-brain-a1")
    result = audit(root, args.source_sha, args.as_of)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite historical evidence, even when the caller reuses a path.
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print("MASTER_BRAIN_A1", result["status"], "missing", len(result["missing_matches"]),
          "ft_events", len(result["ft_events"]), "llm_calls=0")
    return result


if __name__ == "__main__":
    main()
