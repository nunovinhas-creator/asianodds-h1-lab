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


def read_corroborations(root):
    """Read structured additional evidence, not eligible as an independent R2."""
    directory = root / "data" / "lab" / "golden" / "corroborations"
    rows, errors = [], []
    for path in sorted(directory.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("corroboration is not an object")
            rows.append((path.name, value))
        except (OSError, ValueError, UnicodeDecodeError):
            errors.append({"type": "corroboration_read_error", "file": path.name})
    return rows, errors


def validate_corroboration(row, candidate):
    """Schema-closed validation prevents source text, screenshots and private data leaks."""
    allowed = {"schema_version", "event_id", "family", "source_kind",
               "source_sha256", "source_custody", "transcribed_by",
               "independent_reviewer", "kickoff_utc", "trigger", "markets"}
    if not isinstance(row, dict) or set(row) != allowed or row.get("schema_version") != 1:
        raise ValueError("invalid_or_unsafe_corroboration_schema")
    if row.get("event_id") != candidate["event_id"] or row.get("family") != candidate["family"]:
        raise ValueError("corroboration_identity_mismatch")
    if (row.get("source_kind") != "user_pasted_telegram_text" or
        row.get("source_custody") != "pasted_in_conversation_not_authenticated_with_telegram" or
        row.get("transcribed_by") != "assistant" or
        row.get("independent_reviewer") is not False):
        raise ValueError("corroboration_must_be_nonindependent")
    if not isinstance(row.get("source_sha256"), str) or not SHA.fullmatch(row["source_sha256"]):
        raise ValueError("invalid_source_digest")
    if instant(row.get("kickoff_utc")) is None:
        raise ValueError("invalid_kickoff")
    markets = row.get("markets")
    if not isinstance(markets, dict) or set(markets) != set(candidate["expected_markets"]):
        raise ValueError("unexpected_or_missing_market")
    clean = {name: clean_market(markets[name], name) for name in candidate["expected_markets"]}
    trigger = row.get("trigger")
    if (not isinstance(trigger, dict) or
        set(trigger) != {"market", "selection", "before", "after", "displayed_pct", "window_minutes"} or
        trigger["market"] != "1x2" or trigger["selection"] not in ("1", "X", "2") or
        numeric(trigger["before"], "price") is None or
        numeric(trigger["after"], "price") is None or
        type(trigger["window_minutes"]) is not int or
        not 1 <= trigger["window_minutes"] <= 180 or
        type(trigger["displayed_pct"]) not in (int, float) or
        not -10000 < trigger["displayed_pct"] < 10000):
        raise ValueError("invalid_corroboration_trigger")
    return {"event_id": row["event_id"], "kickoff_utc": row["kickoff_utc"],
            "markets": clean, "source_sha256": row["source_sha256"],
            "source_kind": row["source_kind"],
            "trigger": trigger}


def append_corroboration_evidence(report, candidate_document, rows, observations, reviews):
    """Record independent-of-parser *source form* evidence, not an independent reviewer.

    R1 and a user text paste are different media; their file hashes need not match.
    Matching values may be reported, but R2 and Golden certification remain pending.
    """
    references = {x["event_id"]: x for x in candidate_document["candidates"]}
    observed = {x.get("event_id"): x for x in observations if isinstance(x, dict)}
    first_reviews = {}
    for _, review in reviews:
        if isinstance(review, dict) and review.get("reviewer_code") == "R1":
            eid = review.get("event_id")
            if eid in references:
                try:
                    first_reviews[eid] = validate_review(review, references[eid])
                except (TypeError, ValueError, OverflowError):
                    continue
    seen, entries = set(), []
    for filename, raw in rows:
        eid = raw.get("event_id") if isinstance(raw, dict) else None
        if eid not in references:
            report["issues"].append({"type": "unknown_corroboration_event", "file": filename})
            continue
        if eid in seen:
            report["issues"].append({"type": "duplicate_corroboration_event", "event_id": eid})
            continue
        seen.add(eid)
        try:
            record = validate_corroboration(raw, references[eid])
        except (TypeError, ValueError, OverflowError) as exc:
            report["issues"].append({"type": "invalid_corroboration", "event_id": eid,
                                      "reason": str(exc)})
            continue
        r1 = first_reviews.get(eid)
        diffs_v4 = compare_reference(record, observed.get(eid))
        diffs_r1 = compare_reference(record, r1) if r1 else None
        entry = {
            "event_id": eid, "source_kind": record["source_kind"],
            "source_sha256": record["source_sha256"],
            "independent_reviewer": False,
            "telegram_authenticity_verified": False,
            "v4_matching_fields": len(review_values(record)) - len(diffs_v4),
            "total_fields": len(review_values(record)),
            "r1_matching_fields": (len(review_values(record)) - len(diffs_r1))
                                  if diffs_r1 is not None else None,
            "status": ("MATCHES_R1_AND_V4_NOT_INDEPENDENT"
                       if diffs_r1 is not None and not diffs_r1 and not diffs_v4
                       else "DIFFERENCE_OR_R1_MISSING"),
            "v4_differences": diffs_v4,
            "r1_differences": diffs_r1,
            "trigger_displayed_pct": record["trigger"]["displayed_pct"],
            "trigger_pct_formula_verified": False,
        }
        entries.append(entry)
    report["supplemental_corroborations"] = entries
    report["supplemental_corroboration_count"] = len(entries)
    report["limitations"].append(
        "User-pasted text checked against screenshot R1 and V4 is not an independent R2 "
        "or proof of Telegram authenticity; quoted trigger % remains unvalidated")
    return report


def read_firsthand_attestations(root):
    """User declarations stored as metadata only; not artificial R2 reviews."""
    directory = root / "data" / "lab" / "golden" / "attestations"
    records, errors = [], []
    for path in sorted(directory.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(item, dict):
                raise ValueError("attestation must be an object")
            records.append((path.name, item))
        except (ValueError, OSError, UnicodeDecodeError):
            errors.append({"type": "attestation_read_error", "file": path.name})
    return records, errors


def append_user_attestations(report, candidates, attestations, reviews):
    """Recognise user's firsthand validation without claiming a second reviewer.

    This is strong per-event human source attestation, but NOT an external
    Telegram authenticity check or statistically certified parser accuracy.
    """
    by_id = {case["event_id"]: case for case in report["cases"]}
    candidate_ids = {c["event_id"] for c in candidates["candidates"]}
    first_review = {row.get("event_id"): row for _, row in reviews if
                    isinstance(row, dict) and row.get("reviewer_code") == "R1"}
    corroborations = {v["event_id"]: v for v in report.get("supplemental_corroborations", [])}
    verified = []
    seen = set()
    required = {"schema_version", "event_id", "attestation", "asserted_by",
                "attested_date_utc", "source_kind", "screenshot_sha256",
                "corroboration_sha256", "reviewed_fields", "independent_second_reviewer"}
    for filename, item in attestations:
        eid = item.get("event_id") if isinstance(item, dict) else None
        if eid in seen:
            report["issues"].append({"type": "duplicate_firsthand_attestation", "event_id": eid})
            continue
        seen.add(eid)
        try:
            if (not isinstance(item, dict) or set(item) != required or
                item.get("schema_version") != 1 or eid not in candidate_ids or
                item.get("attestation") !=
                  "I personally captured the original AsianOdds Telegram message and copied its text" or
                item.get("asserted_by") != "user_who_supplied_source" or
                not re.fullmatch(r"\d{4}-\d{2}-\d{2}", item.get("attested_date_utc") or "") or
                item.get("source_kind") != "telegram_screenshot_and_copied_text" or
                item.get("independent_second_reviewer") is not False or
                type(item.get("reviewed_fields")) is not int or item["reviewed_fields"] < 1 or
                not isinstance(item.get("screenshot_sha256"), str) or
                not SHA.fullmatch(item["screenshot_sha256"]) or
                not isinstance(item.get("corroboration_sha256"), str) or
                not SHA.fullmatch(item["corroboration_sha256"])):
                raise ValueError("invalid_firsthand_attestation")
            r1 = first_review.get(eid)
            supplement = corroborations.get(eid)
            if (not r1 or r1.get("source_kind") != "telegram_screenshot" or
                r1.get("source_sha256") != item["screenshot_sha256"] or
                not supplement or
                supplement.get("status") != "MATCHES_R1_AND_V4_NOT_INDEPENDENT" or
                supplement.get("source_sha256") != item["corroboration_sha256"] or
                supplement.get("total_fields") != item["reviewed_fields"] or
                supplement.get("v4_matching_fields") != item["reviewed_fields"] or
                supplement.get("r1_matching_fields") != item["reviewed_fields"]):
                raise ValueError("attestation_evidence_not_matched")
            case = by_id[eid]
            case["firsthand_user_validation"] = "CONFIRMED_BY_SOURCE_VIEWER"
            case["firsthand_verified_fields"] = item["reviewed_fields"]
            case["second_independent_review"] = "NOT_RECEIVED" if case["reviews_received"] < 2 else "RECEIVED"
            case["telegram_authenticated_externally"] = False
            if case["status"] == "AWAITING_REVIEWS":
                case["status"] = "USER_SOURCE_VALIDATED"
            verified.append(eid)
        except (ValueError, TypeError) as exc:
            report["issues"].append({"type": "invalid_firsthand_attestation",
                                      "event_id": eid, "file": filename, "reason": str(exc)})
    report["user_validated_case_count"] = len(verified)
    report["user_validated_event_ids"] = verified
    report["status_counts"] = dict(Counter(c["status"] for c in report["cases"]))
    report["limitations"].append(
        "A firsthand user confirmation validates a message transcription, "
        "not a second independent review or statistical 99% parser reliability")
    return report


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
    corroborations, corroboration_errors = read_corroborations(root)
    report = assemble_report(
        candidates, reviews, markets,
        source_errors=ferrors + merrors + errors + corroboration_errors)
    append_corroboration_evidence(report, candidates, corroborations, markets, reviews)
    attestations, attestation_errors = read_firsthand_attestations(root)
    report["issues"].extend(attestation_errors)
    append_user_attestations(report, candidates, attestations, reviews)
    return candidates, report
