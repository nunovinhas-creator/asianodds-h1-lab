"""Append-only LAB FT state/evidence audit. Shadow; never settles H1 bets.

One event on the first observation of each match and on every substantive
state, score or provenance revision. A pre-existing mutable ledger is treated
as a baseline seen NOW, never as historically reconstructible events.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .v6_shadow import canonical, read_journal, utc

SCHEMA = 1
ZERO = "0" * 64
GLOB = "v6-ft-events-????-??.jsonl"
STATUS = "V6_FT_EVIDENCE_SHADOW_NOT_CERTIFIED"
CONFLICT = {"SCORE_CONFLICT", "SOURCE_ORDER_CONFLICT", "IDENTITY_CONFLICT"}
VERIFIED = {"FINAL"}


def sha(obj):
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def quality(row):
    status = row.get("status")
    result = row.get("result") if status == "FINAL" else None
    if not isinstance(result, dict):
        return "QUARANTINED" if status in CONFLICT else "NOT_YET_VERIFIED"
    source = result.get("evidence")
    if not isinstance(source, str) or not source:
        return "EVIDENCE_UNSPECIFIED"
    if "reviewed_public" in source:
        reviewed = (row.get("reviewed_public_resolution") or
                    row.get("source_order_resolution") or {})
        urls = reviewed.get("corroboration_urls") or []
        return ("REVIEWED_PUBLIC_CORROBORATED" if len(set(urls)) >= 2
                else "REVIEWED_PUBLIC_UNCORROBORATED")
    sources = [part for part in source.split("_and_") if part]
    return ("MULTI_PROVIDER" if len(set(sources)) >= 2 else "SINGLE_PROVIDER")


def snapshot(row):
    """Only substantive FT truth/provenance fields; no attempt counters."""
    res = row.get("result") if row.get("status") == "FINAL" else None
    score = None
    if res is not None:
        h, a = res.get("home_goals"), res.get("away_goals")
        if (type(h) is not int or type(a) is not int or h < 0 or a < 0):
            raise ValueError("Invalid FINAL goals in FT journal")
        score = {"home": h, "away": a,
                 "evidence": res.get("evidence"),
                 "identity_match": res.get("identity_match"),
                 "source": res.get("source")}
    return {"status": row.get("status", "UNKNOWN"),
            "home": row.get("home"), "away": row.get("away"),
            "kickoff_utc": row.get("kickoff_utc"),
            "score": score,
            "evidence_level": quality(row),
            "reason": row.get("reason") if score is None else None,
            "source_order_resolution": row.get("source_order_resolution") if score else None,
            "reviewed_public_resolution": row.get("reviewed_public_resolution") if score else None}


def event_hash(event):
    return sha({k: v for k, v in event.items() if k != "sha256"})


def read_events(root):
    events, seen, last, prior_for = [], set(), ZERO, {}
    for path in sorted((Path(root) / "data/lab").glob(GLOB)):
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw:
                raise ValueError("Blank FT evidence event")
            event = json.loads(raw)
            key = event.get("match_key")
            if (event.get("schema_version") != SCHEMA or
                    not isinstance(key, str) or not key or
                    event.get("id") in seen or
                    event.get("previous_sha256") != last or
                    event.get("previous_match_event_id") != prior_for.get(key) or
                    event.get("sha256") != event_hash(event) or
                    utc(event.get("recorded_at")) is None or
                    event.get("snapshot_sha256") != sha(event.get("snapshot"))):
                raise ValueError("V6 FT event chain, lineage or hash is invalid")
            if (event["snapshot"].get("status") == "FINAL" and
                    not isinstance(event["snapshot"].get("score"), dict)):
                raise ValueError("Final FT event lacks score")
            last = event["sha256"]
            prior_for[key] = event["id"]
            seen.add(event["id"])
            events.append(event)
    return events


def latest_events(events):
    return {e["match_key"]: e for e in events}


def validate_against_ledger(events, ledger):
    latest = latest_events(events)
    actual = (ledger.get("matches") or {})
    if set(latest) != set(actual):
        raise ValueError("FT event ledger coverage mismatch")
    for k, row in actual.items():
        if latest[k]["snapshot_sha256"] != sha(snapshot(row)):
            raise ValueError("FT event record does not match authoritative ledger: " + k)
    return True


def synchronize(root, ledger, now, *, verify_only=False):
    """Journal current authoritative ledger snapshot (no API requests).

    Idempotent after publication; source ledger remains the authority. Tracks
    corrections and quarantine even if a FINAL later disappears.
    """
    root = Path(root)
    if now.tzinfo is None:
        raise ValueError("Expected aware UTC write timestamp")
    existing = read_events(root)
    prior = latest_events(existing)
    previous = existing[-1]["sha256"] if existing else ZERO
    rows = (ledger.get("matches") or {})
    additions = []
    for key in sorted(rows):
        observed = snapshot(rows[key])
        signature = sha(observed)
        last = prior.get(key)
        if last and signature == last["snapshot_sha256"]:
            continue
        kind = "INITIAL_LEDGER_OBSERVATION" if last is None else (
            "FINAL_REVISED" if observed["status"] == "FINAL" and
            last["snapshot"]["status"] == "FINAL" else
            "RESULT_QUARANTINED" if last["snapshot"]["status"] == "FINAL" and
            observed["status"] != "FINAL" else
            "NEW_FINAL" if observed["status"] == "FINAL" else "STATE_CHANGED")
        payload = {
            "schema_version": SCHEMA, "match_key": key,
            "recorded_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "event_type": kind, "snapshot": observed, "snapshot_sha256": signature,
            "source_last_checked_at": rows[key].get("checked_at"),
            "previous_match_event_id": last["id"] if last else None,
            "previous_sha256": previous,
        }
        payload["id"] = "FT6:" + sha({"match_key": key, "prior": payload["previous_match_event_id"],
                                      "snapshot": signature})[:28]
        payload["sha256"] = event_hash(payload)
        additions.append(payload)
        previous = payload["sha256"]
    if verify_only and additions:
        raise ValueError("FT evidence journal diverges from current ledger")
    if additions and not verify_only:
        path = root / "data/lab" / ("v6-ft-events-" +
                  now.astimezone(timezone.utc).strftime("%Y-%m") + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for item in additions:
                handle.write(canonical(item) + "\n")
    verified = read_events(root)
    if verify_only and len(verified) != len(existing):
        raise ValueError("FT verify mode changed record count")
    validate_against_ledger(verified, ledger)
    return report(verified, ledger), len(additions)


def report(events, ledger):
    actual = (ledger.get("matches") or {})
    latest = latest_events(events)
    counts = Counter(e["event_type"] for e in events)
    q = Counter(e["snapshot"]["evidence_level"] for e in latest.values())
    quarantine = sorted(k for k,e in latest.items() if e["snapshot"]["evidence_level"] == "QUARANTINED")
    return {
        "schema_version": SCHEMA, "status": STATUS,
        "scope": "All distinct LAB FT match keys, not only V6 forecasts",
        "matches": len(actual), "events_total": len(events),
        "event_types": dict(sorted(counts.items())),
        "current_evidence_levels": dict(sorted(q.items())),
        "confirmed_scores": sum(e["snapshot"]["status"] == "FINAL" for e in latest.values()),
        "quarantined_match_keys": quarantine[:40],
        "quarantined_count": len(quarantine),
        "chain_tail": events[-1]["sha256"] if events else ZERO,
        "limitations": [
            "The initial event reflects the mutable ledger as seen at journal installation, NOT historical FT transitions.",
            "Subsequent changes to goals, status and provenance become new immutable events.",
            "Repeated provider checks without substantive change do not create events.",
            "Evidence levels classify provenance, not mathematical proof of a correct FT.",
            "No extra API calls, betting, automated H1 liquidation or model promotion.",
            "Git history is needed to detect wholesale valid-chain replacement.",
        ]
    }


def priority_hints(root):
    """Research value from REAL frozen pre-kickoff observations only.

    The caller selects eligible, still-unverified fixtures; these hints never
    override eligibility, the 3-hour grace period, cooldown or per-run cap.
    """
    rows = read_journal(root)
    latest = {}
    for r in rows:
        latest[r["match_key"]] = r
    hints = {}
    for key, r in latest.items():
        if utc(r.get("known_at")) is None or utc(r.get("kickoff_utc")) is None:
            continue
        if utc(r["known_at"]) >= utc(r["kickoff_utc"]):
            continue
        if r.get("pattern_strict_posthoc"):
            hints[key] = 3
        elif r.get("pattern_original_posthoc"):
            hints[key] = 2
        elif (r.get("price_quality") or {}).get("status") == "USABLE":
            hints[key] = 1
    return hints
