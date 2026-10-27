"""Independent, manually transcribed Telegram golden-set review.

No original Telegram text, screenshots, credentials or signed URLs are stored.
Neither the legacy nor the V4 parser is an authority for expected values.
Two blind reviews provide provisional agreement, NOT proof of original truth.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from .v4_audit import instant, numeric, read_jsonl, CUTOVER

FAMILIES = ("total_up", "total_down", "1x2")
FIELDS = {
    "total": ("line", "over_price", "under_price"),
    "asian_handicap": ("line", "home_price", "away_price"),
    "one_x_two": ("1", "X", "2"),
}
SIDES = ("before", "after")
EXPECTED_MARKETS = {"total_up": ("total",), "total_down": ("total",),
                    "1x2": ("one_x_two", "asian_handicap", "total")}
SHA = re.compile(r"[a-f0-9]{64}\Z")
EVENT = re.compile(r"[0-9]{1,18}:[0-9]{1,18}\Z")
REVIEWER = re.compile(r"R[12]\Z")


def source_family(alert, fmt):
    kind = (alert or {}).get("market")
    if kind not in ("total", "1x2"):
        mentions = (fmt or {}).get("markets_mentioned") or []
        kind = "1x2" if "1x2" in mentions else "total" if "total" in mentions else None
    if kind == "1x2":
        return "1x2"
    if kind == "total" and alert:
        before = numeric(alert.get("total_before"), "line")
        after = numeric(alert.get("total_after"), "line")
        if before is not None and after is not None:
            return "total_up" if after > before else "total_down" if after < before else None
    return None


def select_candidates(state, formats, market_rows, *, per_family=8):
    """Stable oldest-first stratum selection. Never prefill reference odds."""
    if per_family < 1:
        raise ValueError("per_family must be positive")
    fmt = {v.get("event_id"): v for v in formats if isinstance(v, dict)}
    obs = {v.get("event_id"): v for v in market_rows if isinstance(v, dict)}
    strata = {family: [] for family in FAMILIES}
    for alert in state.get("alerts", []):
        if not isinstance(alert, dict):
            continue
        eid = alert.get("event_id")
        if not isinstance(eid, str) or not EVENT.fullmatch(eid) or eid not in obs:
            continue
        family = source_family(alert, fmt.get(eid))
        when = instant(alert.get("observed_at"))
        if family not in strata or when is None:
            continue
        observed = obs[eid]
        # Candidate selection depends on real structured event metadata; no
        # V4 values are copied to the reference or revealed in the review form.
        strata[family].append({
            "event_id": eid, "family": family,
            "observed_at": alert["observed_at"],
            "home": alert.get("home") or "",
            "away": alert.get("away") or "",
            "competition": alert.get("competition") or "",
            "historical_before_cutover": when < instant(CUTOVER),
            "format_id": (fmt.get(eid) or {}).get("format_id"),
            "parser_revision": observed.get("parser_revision") or "unrecorded",
            "expected_markets": list(EXPECTED_MARKETS[family]),
            "v4_available": True,
        })
    for family in strata:
        strata[family].sort(key=lambda x: (x["observed_at"], x["event_id"]))
    # Stable selection: newly collected events never displace a review in progress.
    selected = [row for family in FAMILIES for row in strata[family][:per_family]]
    return {
        "schema_version": 1,
        "status": "REFERENCE_NOT_YET_VERIFIED",
        "selection_policy": "first eligible V4 observations per stratum, oldest first; manual blind review",
        "no_reference_values_prefilled": True,
        "limits_per_family": per_family,
        "eligible_per_family": {k: len(v) for k, v in strata.items()},
        "candidates": selected,
        "limitations": [
            "Selection uses structural metadata; reference odds require direct visual checks",
            "No raw Telegram text or screenshots are published",
            "Candidate selection is not a statistically random sampling design",
            "Historical pre-cutover candidates cannot establish post-deployment accuracy",
        ],
    }


def clean_market(raw, kind):
    if not isinstance(raw, dict):
        raise ValueError("missing_market:" + kind)
    result = {}
    for field in FIELDS[kind]:
        obj = raw.get(field) if kind == "one_x_two" else None
        if kind == "one_x_two":
            if not isinstance(obj, dict):
                raise ValueError("missing_selection:" + field)
            pair = obj
        else:
            pair = None
        if kind == "one_x_two":
            result[field] = {}
            for side in SIDES:
                if side not in pair:
                    raise ValueError("missing_field:" + kind + "." + field + "." + side)
                n = numeric(pair[side], "price")
                if n is None:
                    raise ValueError("invalid_field:" + kind + "." + field + "." + side)
                result[field][side] = n
        else:
            # For table markets field values are stored under before / after.
            for side in SIDES:
                block = raw.get(side)
                if not isinstance(block, dict) or field not in block:
                    raise ValueError("missing_field:" + kind + "." + side + "." + field)
                n = numeric(block[field], "line" if field == "line" else "price")
                if n is None:
                    raise ValueError("invalid_field:" + kind + "." + side + "." + field)
                result.setdefault(side, {})[field] = n
    return result


def validate_review(raw, candidate):
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("invalid_schema")
    eid = candidate["event_id"]
    if raw.get("event_id") != eid:
        raise ValueError("event_id_mismatch")
    reviewer = raw.get("reviewer_code")
    if not isinstance(reviewer, str) or not REVIEWER.fullmatch(reviewer):
        raise ValueError("invalid_reviewer_code")
    if raw.get("source_checked") is not True:
        raise ValueError("source_not_checked")
    if raw.get("source_kind") not in ("telegram_copied_text", "telegram_screenshot"):
        raise ValueError("invalid_source_kind")
    digest = raw.get("source_sha256")
    if not isinstance(digest, str) or not SHA.fullmatch(digest):
        raise ValueError("invalid_source_digest")
    checked = instant(raw.get("checked_at"))
    if checked is None:
        raise ValueError("invalid_checked_at")
    ko = instant(raw.get("kickoff_utc"))
    if ko is None:
        raise ValueError("invalid_kickoff")
    if raw.get("family") != candidate["family"]:
        raise ValueError("family_mismatch")
    source = raw.get("markets")
    if not isinstance(source, dict) or set(source) != set(candidate["expected_markets"]):
        raise ValueError("unexpected_or_missing_market")
    markets = {name: clean_market(source[name], name) for name in candidate["expected_markets"]}
    # Explicitly NO original Telegram text, screenshot, team PII, passwords or link.
    allowed = {"schema_version","event_id","family","reviewer_code","source_kind",
               "source_checked","source_sha256","checked_at","kickoff_utc","markets"}
    if set(raw) != allowed:
        raise ValueError("unknown_or_unsafe_review_keys")
    return {
        "event_id": eid, "family": candidate["family"], "reviewer_code": reviewer,
        "source_kind": raw["source_kind"], "source_sha256": digest,
        "checked_at": checked.isoformat(timespec="seconds"),
        "kickoff_utc": ko.isoformat(timespec="seconds"), "markets": markets,
    }


def review_values(review):
    vals = {"kickoff_utc": review["kickoff_utc"]}
    for name, market in review["markets"].items():
        if name == "one_x_two":
            for field in FIELDS[name]:
                for side in SIDES:
                    vals[name + "." + field + "." + side] = market[field][side]
        else:
            for side in SIDES:
                for field in FIELDS[name]:
                    vals[name + "." + side + "." + field] = market[side][field]
    return vals


def v4_fields(observation):
    vals = {"kickoff_utc": observation.get("kickoff_utc")}
    for kind, table in (observation.get("markets") or {}).items():
        if kind not in FIELDS or not isinstance(table, dict):
            continue
        if kind == "one_x_two":
            for field in FIELDS[kind]:
                for side in SIDES:
                    vals[kind + "." + field + "." + side] = (table.get(field) or {}).get(side)
        else:
            for side in SIDES:
                for field in FIELDS[kind]:
                    vals[kind + "." + side + "." + field] = (table.get(side) or {}).get(field)
    return vals


def compare_reference(reference, observed):
    diffs = []
    for field, truth in review_values(reference).items():
        found = v4_fields(observed or {}).get(field)
        if field == "kickoff_utc":
            eq = instant(truth) is not None and instant(truth) == instant(found)
        else:
            val = numeric(found, "line" if field.split(".")[-1] == "line" else "price")
            eq = val is not None and abs(val - truth) <= 1e-8
        if not eq:
            # Never publish the source message or full review. Field-level
            # expected and observed numbers are already non-sensitive odds.
            diffs.append({"field": field, "reference": truth, "v4": found})
    return diffs


def assemble_report(candidate_document, review_rows, observations, *, source_errors=None):
    issues = list(source_errors or [])
    candidates = candidate_document["candidates"]
    refs = {x["event_id"]: x for x in candidates}
    by_id = {x.get("event_id"): x for x in observations if isinstance(x, dict)}
    reviews = {}
    for filename, row in review_rows:
        eid = row.get("event_id") if isinstance(row, dict) else None
        if eid not in refs:
            issues.append({"type": "review_not_in_candidate_pool", "file": filename})
            continue
        try:
            clean = validate_review(row, refs[eid])
        except (TypeError, ValueError, OverflowError) as exc:
            issues.append({"type": "invalid_review", "event_id": eid,
                           "file": filename, "reason": str(exc)})
            continue
        code = clean["reviewer_code"]
        if code in reviews.setdefault(eid, {}):
            issues.append({"type": "duplicate_reviewer", "event_id": eid, "reviewer": code})
            continue
        reviews[eid][code] = clean
    cases = []
    for cand in candidates:
        eid = cand["event_id"]
        group = reviews.get(eid, {})
        item = {"event_id": eid, "family": cand["family"],
                "reviews_received": len(group)}
        if len(group) != 2:
            item["status"] = "AWAITING_REVIEWS"
        else:
            a, b = group["R1"], group["R2"]
            if a["source_kind"] != b["source_kind"] or a["source_sha256"] != b["source_sha256"]:
                item["status"] = "SOURCE_DISAGREEMENT"
            elif review_values(a) != review_values(b):
                item["status"] = "TRANSCRIPTION_DISAGREEMENT"
                item["fields_disagreed"] = [k for k in review_values(a)
                     if review_values(a)[k] != review_values(b)[k]]
            else:
                differences = compare_reference(a, by_id.get(eid))
                item["status"] = "V4_MISMATCH" if differences else "TWO_REVIEWS_AGREE_WITH_V4"
                if differences:
                    item["differences"] = differences
                item["checked_fields"] = len(review_values(a))
        cases.append(item)
    counts = dict(Counter(x["status"] for x in cases))
    accepted = sum(x["status"] == "TWO_REVIEWS_AGREE_WITH_V4" for x in cases)
    mismatches = sum(x["status"] == "V4_MISMATCH" for x in cases)
    return {
        "schema_version": 1,
        "status": "NOT_CERTIFIED",
        "golden_set_verified": False,
        "authority": "manual original Telegram inspection; not legacy or V4",
        "candidate_count": len(candidates),
        "reviews_received": sum(len(x) for x in reviews.values()),
        "two_review_agreements": accepted,
        "v4_mismatch_cases": mismatches,
        "status_counts": counts, "cases": cases, "issues": issues,
        "limitations": [
            "R1/R2 reviewer codes cannot cryptographically prove distinct humans",
            "SHA-256 proves consistency of a supplied source, not Telegram authenticity",
            "Original Telegram source and embedded text-url entities may differ",
            "All cases remain unc ertified until independent source and manual sign-off".replace("unc ertified","uncertified"),
            "No ROI, predictive validation or probabilistic claims",
        ],
    }


def read_reviews(root):
    directory = root / "data" / "lab" / "golden" / "reviews"
    rows, errors = [], []
    for f in sorted(directory.glob("*.json")):
        try:
            row = json.loads(f.read_text(encoding="utf-8"))
            rows.append((f.name, row))
        except (OSError, ValueError, UnicodeDecodeError):
            errors.append({"type": "review_read_error", "file": f.name})
    return rows, errors


def build(root):
    data = root / "data"
    state = json.loads((data / "state.json").read_text(encoding="utf-8"))
    formats, ferrors = read_jsonl(root, "formats")
    markets, merrors = read_jsonl(root, "markets")
    candidates = select_candidates(state, formats, markets)
    reviews, errors = read_reviews(root)
    report = assemble_report(candidates, reviews, markets, source_errors=ferrors + merrors + errors)
    return candidates, report
