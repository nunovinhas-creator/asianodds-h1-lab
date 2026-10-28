"""V4 Telegram revision evidence, separate from H1 and the current V4 projection.

Append-only UTC-month journals; chain covers all observed versions across months.
The pre-existing markets-YYYY-MM.jsonl remains a *latest view* for consumers.
An imported old row is explicitly a baseline noticed at migration time, not
proof of the original receipt date or proof that it was never previously edited.
"""
from __future__ import annotations
from .lab_archive import monthly_paths, append_monthly

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1
ZERO = "0" * 64
JOURNAL = "v4-revisions-????-??.jsonl"
STATUS = "V4_EDIT_AUDIT_SHADOW_NOT_CONTINUOUS_TELEGRAM_MONITOR"


def canonical(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(v):
    return hashlib.sha256(canonical(v).encode("utf-8")).hexdigest()


def instant(value):
    if not isinstance(value, str):
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except ValueError:
        return None


def fingerprint(row):
    """Stable semantic fields, excluding changing collector/parser checkout SHA."""
    return digest({k: v for k, v in row.items()
                   if k not in ("parser_commit", "parser_source_sha256")})


def read_events(root):
    events, previous, ids, per_message = [], ZERO, set(), {}
    for p in monthly_paths(root, "v4-revisions"):
        for raw in p.read_text(encoding="utf-8").splitlines():
            if not raw:
                raise ValueError("Blank V4 revision event")
            e = json.loads(raw)
            key = e.get("event_id")
            if (e.get("schema_version") != SCHEMA or not isinstance(key, str) or
                    not key or e.get("revision_id") in ids or
                    e.get("previous_sha256") != previous or
                    e.get("previous_event_revision_id") != per_message.get(key) or
                    e.get("sha256") != digest({k:v for k,v in e.items() if k != "sha256"}) or
                    instant(e.get("known_at")) is None or
                    e.get("snapshot_sha256") != fingerprint(e.get("snapshot") or {})):
                raise ValueError("V4 revision chain altered")
            ids.add(e["revision_id"])
            previous = e["sha256"]
            per_message[key] = e["revision_id"]
            events.append(e)
    return events


def current_versions(events):
    return {e["event_id"]: e for e in events}


def revision_type(previous, row, imported=False):
    if previous is None:
        return "HISTORICAL_BASELINE_IMPORT" if imported else "FIRST_SEEN_BY_COLLECTOR"
    old = previous["snapshot"]
    old_edit = old.get("telegram_edit_at")
    new_edit = row.get("telegram_edit_at")
    if new_edit and new_edit != old_edit:
        return "EDIT_DATE_CHANGED"
    if fingerprint(old) != fingerprint(row):
        return "CONTENT_CHANGED_EDIT_UNPROVEN"
    return "UNCHANGED"


def append(root, old_rows, incoming_rows, *, now):
    """Record old legacy baselines first, then truly observed new revisions.

    This is fail-closed: never append a second event for an identical
    reobservation (including changing parser_commit). A reversion A->B->A
    is still retained because it differs from the immediately preceding B.
    """
    if now.tzinfo is None:
        raise ValueError("Processing clock must be timezone-aware")
    root = Path(root)
    events = read_events(root)
    latest = current_versions(events)
    before = len(events)
    previous_sha = events[-1]["sha256"] if events else ZERO
    additions = []

    def record(row, *, imported):
        nonlocal previous_sha
        if not isinstance(row, dict) or not isinstance(row.get("event_id"), str):
            raise ValueError("Invalid V4 revision observation")
        if row.get("schema_version") != 4 or not instant(row.get("observed_at")):
            raise ValueError("V4 revision must carry an authentic observation")
        edited = row.get("telegram_edit_at")
        if edited is not None and instant(edited) is None:
            raise ValueError("Invalid Telegram edit_date")
        key = row["event_id"]
        previous = latest.get(key)
        kind = revision_type(previous, row, imported=imported)
        if kind == "UNCHANGED":
            return
        if previous is not None and kind == "CONTENT_CHANGED_EDIT_UNPROVEN":
            # A changed parser, an unrecorded edit or a correction is
            # indistinguishable without Telegram edit metadata.
            pass
        payload = {
            "schema_version": SCHEMA, "event_id": key,
            "kind": kind,
            "known_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "telegram_original_at": row["observed_at"],
            "telegram_edit_at": edited,
            "edit_date_verified_from_telegram": edited is not None and not imported,
            "snapshot": row,
            "snapshot_sha256": fingerprint(row),
            "previous_event_revision_id": previous["revision_id"] if previous else None,
            "previous_sha256": previous_sha,
        }
        payload["revision_id"] = "V4R:" + digest({"key": key,
                         "prev":payload["previous_event_revision_id"],
                         "snapshot":payload["snapshot_sha256"]})[:28]
        payload["sha256"] = digest(payload)
        additions.append(payload)
        latest[key] = payload
        previous_sha = payload["sha256"]

    for key in sorted(old_rows):
        if key not in latest:
            record(old_rows[key], imported=True)
    # Processing order as supplied by collector, never guessed by original
    # Telegram timestamp. Latest re-observation wins, with every step retained.
    for row in incoming_rows:
        record(row, imported=False)

    if additions:
        append_monthly(root, "v4-revisions", now.astimezone(timezone.utc).strftime("%Y-%m"),
                       [canonical(e) + "\n" for e in additions])
    verified = read_events(root)
    if len(verified) != before + len(additions):
        raise ValueError("V4 revision write interrupted")
    return additions


def read_latest_projection(root):
    rows = {}
    for p in monthly_paths(root, "markets"):
        for line in p.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            key = row["event_id"]
            if key in rows:
                raise ValueError("Duplicate V4 projection event_id")
            rows[key] = row
    return rows


def verify_projection(root):
    rows = read_latest_projection(root)
    latest = current_versions(read_events(root))
    if set(rows) != set(latest):
        raise ValueError("V4 latest view not fully indexed in revision journal")
    for key, value in rows.items():
        if fingerprint(value) != latest[key]["snapshot_sha256"]:
            raise ValueError("V4 current projection diverged: " + key)
    return True


def report(root):
    events = read_events(root)
    latest = current_versions(events)
    kinds = Counter(e["kind"] for e in events)
    edited_ids = sorted({e["event_id"] for e in events if e["kind"] == "EDIT_DATE_CHANGED"})
    uncertain = sorted({e["event_id"] for e in events if e["kind"] == "CONTENT_CHANGED_EDIT_UNPROVEN"})
    return {
        "schema_version": SCHEMA, "status": STATUS,
        "messages": len(latest), "revision_events": len(events),
        "kinds": dict(sorted(kinds.items())),
        "telegram_edited_messages": len(edited_ids),
        "changed_without_edit_proof": len(uncertain),
        "telegram_edited_event_ids": edited_ids[:40],
        "unproven_changed_event_ids": uncertain[:40],
        "last_chain_sha256": events[-1]["sha256"] if events else ZERO,
        "notes": [
            "V4 markets JSONL is a mutable latest projection; historical revisions remain append-only.",
            "Previously stored records are imported only as migration baselines, never backdated.",
            "Telegram edit_date is source-reported; absence does not prove never edited.",
            "Only edits encountered during future polls are detectable; not a full Telegram edit history.",
            "An unchanged message with a changing parser Git commit does not create a revision.",
            "Historical V6 frozen forecasts are never changed by a later V4 edit.",
            "No raw Telegram message text, credentials, or added betting signals are stored.",
        ],
    }
