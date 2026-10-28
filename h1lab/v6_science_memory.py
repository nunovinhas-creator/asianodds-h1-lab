"""MASTER BRAIN V6 experimental scientific memory, SHADOW only.

Five independent append-only, hash-linked event streams:
observations, patterns, hypotheses, evidence, decisions.

The existing prospective forecast journal and hypothesis registration are the
sources of truth. This module indexes them without backdating its own events.
FT corrections/suspensions create new evidence events and do not overwrite
previous observations. Every output view is deterministically reconstructible.

NOT a new betting model, V5 promotion, proof of realtime intake, or FT authority.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .pattern_engine import outcomes_from
from .v6_hypotheses import ensure_registered
from .v6_shadow import HYPOTHESIS, canonical, read_journal, utc

VERSION = 1
KINDS = ("observations", "patterns", "hypotheses", "evidence", "decisions")
ZERO = "0" * 64
STATUS = "V6_SCIENCE_MEMORY_SHADOW_WARMUP_NOT_VALIDATED"


def digest(obj):
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def event_hash(row):
    return digest({k: v for k, v in row.items() if k != "sha256"})


def journal_paths(root, kind):
    if kind not in KINDS:
        raise ValueError("unknown V6 memory stream")
    return sorted((Path(root) / "data/lab").glob("v6-memory-" + kind + "-????-??.jsonl"))


def read_stream(root, kind):
    """Validate full link chain, deterministic IDs, schema and stream ownership."""
    rows, seen, previous = [], set(), ZERO
    for path in journal_paths(root, kind):
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                raise ValueError("blank line in V6 " + kind + " journal")
            row = json.loads(raw)
            eid = row.get("id")
            if (row.get("schema_version") != VERSION or row.get("stream") != kind
                    or not isinstance(eid, str) or not eid or eid in seen
                    or row.get("previous_sha256") != previous
                    or row.get("sha256") != event_hash(row)):
                raise ValueError("V6 scientific memory corrupt: " + kind)
            seen.add(eid)
            previous = row["sha256"]
            rows.append(row)
    return rows


def append_events(root, kind, now, rows):
    """Append idempotently; source and historical timestamps never altered."""
    existing = read_stream(root, kind)
    seen = {r["id"] for r in existing}
    previous = existing[-1]["sha256"] if existing else ZERO
    path = Path(root) / "data/lab" / ("v6-memory-" + kind + "-"
                                  + now.astimezone(timezone.utc).strftime("%Y-%m") + ".jsonl")
    new = []
    for candidate in rows:
        if candidate["id"] in seen:
            prior = next(r for r in existing if r["id"] == candidate["id"])
            # Content may contain ingest/process time in a newly generated
            # candidate; never update or silently replace the existing row.
            if prior["source_digest"] != candidate["source_digest"]:
                raise ValueError("V6 deterministic event id collision")
            continue
        item = dict(candidate)
        item.update({"schema_version": VERSION, "stream": kind,
                     "written_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
                     "previous_sha256": previous})
        item["sha256"] = event_hash(item)
        previous = item["sha256"]
        seen.add(item["id"])
        new.append(item)
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            for item in new:
                stream.write(canonical(item) + "\n")
    read_stream(root, kind)  # fail closed if write/replay is inconsistent
    return len(new)


def fact(kind, event_id, payload):
    return {"id": event_id, "source_digest": digest(payload), "event": payload}


def _ft_sources(root):
    p = Path(root) / "data/lab/ft-ledger.json"
    ledger = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"matches": {}}
    csv_path = Path(root) / "data/results.csv"
    if csv_path.exists():
        with csv_path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    else:
        rows = []
    outcome_rows, provenance, conflicts = outcomes_from(ledger, rows)
    return outcome_rows, provenance, set(conflicts), ledger


def _evidence_proposal(frozen, results, provenance, conflicts, ledger, prior_evidence):
    """FT is attached only to one frozen pre-KO match; revisions are events."""
    latest = {}
    for row in frozen:
        latest[row["match_key"]] = row
    proposals = []
    for key in sorted(latest):
        row = latest[key]
        previous = prior_evidence.get(key)
        outcome = results.get(key)
        state = "CONFIRMED" if outcome is not None else "UNKNOWN"
        if previous is None and state == "UNKNOWN":
            continue  # no fictitious event when a result is not yet known
        if previous and state == "UNKNOWN":
            if previous["state"] == "QUARANTINED":
                continue
            state = "QUARANTINED"
        result = ({"home_goals": outcome["home_goals"],
                   "away_goals": outcome["away_goals"],
                   "over_2_5": bool(outcome["OVER_2_5"]),
                   "btts_yes": bool(outcome["BTTS_YES"])}
                  if outcome is not None else None)
        base = (ledger.get("matches") or {}).get(key) or {}
        payload = {
            "hypothesis_id": HYPOTHESIS, "match_key": key,
            "frozen_source_sha256": row["sha256"],
            "frozen_known_at": row["known_at"],
            "kickoff_utc": row["kickoff_utc"],
            "market_probability_over_2_5": row.get("market_probability_over_2_5"),
            "pattern_original_posthoc": bool(row.get("pattern_original_posthoc")),
            "state": state, "ft": result,
            "ft_source": provenance.get(key, "FT_MISSING_OR_CONFLICT"),
            "ft_checked_at": base.get("checked_at") if base.get("status") == "FINAL" else None,
            "ft_source_url": ((base.get("result") or {}).get("source")
                              if base.get("status") == "FINAL" else None),
            "ft_evidence_level": ((base.get("result") or {}).get("evidence")
                                  if base.get("status") == "FINAL" else None),
            "source_conflict": key in conflicts,
            "previous_evidence_event_id": previous["event_id"] if previous else None,
        }
        signature = digest({"state": state, "ft": result,
                            "frozen_source_sha256": row["sha256"],
                            "source": payload["ft_source"], "ft_evidence_level": payload["ft_evidence_level"]})
        # Existing evidence with same result/status stays canonical, even if
        # ledger checked_at or provider URL later changes.
        if previous and previous["signature"] == signature:
            continue
        payload["signature"] = signature
        payload["event_id"] = "FT:" + digest({"match_key": key, "signature": signature})[:24]
        proposals.append(fact("evidence", payload["event_id"], payload))
    return proposals


def rebuild(root, *, frozen=None, registration=None):
    """Validate all five streams and rebuild the same view from their facts.

    The current mutable FT ledger is NOT read here: replay is independent of
    current results, source APIs, the current calendar time, and dashboards.
    """
    if frozen is None:
        frozen = read_journal(root)
    if registration is None:
        p = Path(root) / "data/lab/v6-hypotheses.jsonl"
        entries = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
        registration = json.loads(entries[0]) if len(entries) == 1 else None
    streams = {kind: read_stream(root, kind) for kind in KINDS}
    forecast_by_hash = {r["sha256"]: r for r in frozen}
    observed = set()
    patterns = set()
    hypothesis_ids = set()
    evidence = {}
    decisions = []
    for row in streams["observations"]:
        e = row["event"]
        original = forecast_by_hash.get(e["forecast_sha256"])
        if (original is None or original["match_key"] != e["match_key"]
                or original["event_id"] != e["event_id"]
                or original["known_at"] != e["known_at"]
                or utc(e["known_at"]) is None
                or utc(e["kickoff_utc"]) is None
                or utc(e["known_at"]) >= utc(e["kickoff_utc"])):
            raise ValueError("V6 observation cannot be traced to frozen forecast")
        observed.add(e["forecast_sha256"])
    for row in streams["patterns"]:
        e = row["event"]
        src = forecast_by_hash.get(e["forecast_sha256"])
        if (not src or e["forecast_sha256"] not in observed or
                e["pattern_original_posthoc"] != bool(src["pattern_original_posthoc"]) or
                e["pattern_strict_posthoc"] != bool(src["pattern_strict_posthoc"])):
            raise ValueError("V6 pattern snapshot mismatches frozen observation")
        patterns.add(e["forecast_sha256"])
    for row in streams["hypotheses"]:
        e = row["event"]
        if (not registration or e["hypothesis_id"] != registration["id"] or
                e["definition_sha256"] != registration["definition_sha256"] or
                e["registered_at"] != registration["registered_at"]):
            raise ValueError("V6 hypothesis registration mismatch")
        hypothesis_ids.add(e["hypothesis_id"])
    for row in streams["evidence"]:
        e = row["event"]
        key = e["match_key"]
        if e["frozen_source_sha256"] not in observed or e["hypothesis_id"] not in hypothesis_ids:
            raise ValueError("V6 outcome lacks frozen source or hypothesis")
        if e["state"] not in ("CONFIRMED", "QUARANTINED"):
            raise ValueError("Invalid FT evidence state")
        last = evidence.get(key)
        if e["previous_evidence_event_id"] != (last["event_id"] if last else None):
            raise ValueError("FT evidence revision chain broken")
        evidence[key] = e
    for row in streams["decisions"]:
        e = row["event"]
        if e["hypothesis_id"] not in hypothesis_ids:
            raise ValueError("V6 decision without hypothesis")
        if e["state"] not in ("INCONCLUSIVO", "VALIDADO"):
            raise ValueError("Unknown science decision state")
        decisions.append(e)
    # No missing observation/pattern may be silently treated as complete.
    missing = sorted(set(forecast_by_hash) - observed)
    missing_patterns = sorted(set(forecast_by_hash) - patterns)
    if missing or missing_patterns:
        raise ValueError("V6 memory incomplete vs source forecasts")
    if registration and registration["id"] not in hypothesis_ids:
        raise ValueError("V6 registered hypothesis absent from memory")
    status_counts = Counter(x["state"] for x in evidence.values())
    scored = sum(1 for x in evidence.values()
                 if x["state"] == "CONFIRMED"
                 and x["market_probability_over_2_5"] is not None)
    selected = sum(1 for x in evidence.values()
                   if x["state"] == "CONFIRMED"
                   and x["market_probability_over_2_5"] is not None
                   and x["pattern_original_posthoc"])
    return {
        "schema_version": VERSION, "status": STATUS,
        "stream_records": {k: len(v) for k, v in streams.items()},
        "source_forecasts": len(frozen),
        "unique_forecast_matches": len({x["match_key"] for x in frozen}),
        "hypotheses": sorted(hypothesis_ids),
        "ft_evidence_state_counts": dict(status_counts),
        "ft_scored_with_model_reference": scored,
        "ft_scored_pattern_original": selected,
        "decisions": decisions[-10:],
        "memory_chain_tails": {k: (v[-1]["sha256"] if v else ZERO) for k, v in streams.items()},
        "limitations": [
            "Memory streams are indexed from already frozen forecasts; initial migration is not backdated.",
            "Only the registered Pattern Watch definition is indexed as a hypothesis here.",
            "FT events are evidence copies, not an authority over results; missing FT means quarantine.",
            "Retrospective pattern scans and the other 800 exploratory hypotheses remain outside this memory.",
            "Rebuild detects accidental changes, while Git history is needed to detect whole-chain replacement.",
            "No profitability, successful OOS validation or trading decision is implied.",
        ],
    }


def synchronize(root, now, *, report=None):
    if now.tzinfo is None:
        raise ValueError("aware now required")
    root = Path(root)
    frozen = read_journal(root)
    reg, _ = ensure_registered(root, now)
    change = {}
    observations = []
    patterns = []
    for row in frozen:
        source = row["sha256"]
        e = {
            "match_key": row["match_key"], "event_id": row["event_id"],
            "known_at": row["known_at"], "observed_at": row["observed_at"],
            "kickoff_utc": row["kickoff_utc"], "forecast_sha256": source,
            "price_quality_status": row["price_quality"]["status"],
            "origin": "MIGRATED_FROM_FROZEN_SOURCE_JOURNAL",
        }
        observations.append(fact("observations", "OBS:" + source, e))
        p = {"match_key": row["match_key"], "forecast_sha256": source,
             "feature_version": "V6-PATTERN-WATCH-2026-10-28",
             "pattern_original_posthoc": bool(row["pattern_original_posthoc"]),
             "pattern_strict_posthoc": bool(row["pattern_strict_posthoc"]),
             "total_origin": row.get("total_origin"),
             "event_id": row["event_id"],
             "derived_from": "frozen_pattern_flags_at_actual_known_at"}
        patterns.append(fact("patterns", "PAT:" + source, p))
    change["observations"] = append_events(root, "observations", now, observations)
    change["patterns"] = append_events(root, "patterns", now, patterns)
    source = {"hypothesis_id": reg["id"], "definition_sha256": reg["definition_sha256"],
              "registered_at": reg["registered_at"], "origin": reg["origin"],
              "source_registration_sha256": reg["sha256"]}
    change["hypotheses"] = append_events(root, "hypotheses", now, [
        fact("hypotheses", "HYP:" + reg["id"] + ":" + reg["definition_sha256"], source)])
    prior = {}
    for entry in read_stream(root, "evidence"):
        e = entry["event"]
        prior[e["match_key"]] = e
    outcomes, provenance, conflicts, ledger = _ft_sources(root)
    change["evidence"] = append_events(root, "evidence", now,
        _evidence_proposal(frozen, outcomes, provenance, conflicts, ledger, prior))
    previous_decisions = read_stream(root, "decisions")
    state = ((report or {}).get("hypothesis") or {}).get("state") or "INCONCLUSIVO"
    if state not in ("INCONCLUSIVO", "VALIDADO"):
        raise ValueError("unknown V6 state")
    last_state = previous_decisions[-1]["event"]["state"] if previous_decisions else None
    decision_rows = []
    if last_state != state:
        event = {
            "hypothesis_id": HYPOTHESIS, "state": state,
            "reason": ("INCONCLUSIVE_LOW_POWER" if state == "INCONCLUSIVO"
                       else "CONFIRMATORY_EVIDENCE_CONSTRAINTS_PASSED"),
            "observed_oos_ft": (((report or {}).get("comparisons") or {})
                                .get("pattern_posthoc_original") or {}).get("n", 0),
            "e_value": ((report or {}).get("hypothesis") or {}).get("e_value", 1.0),
            "previous_decision_event_id": (previous_decisions[-1]["event"]["event_id"]
                                           if previous_decisions else None),
            "event_id": "DEC:" + HYPOTHESIS + ":" + state + ":" + str(len(previous_decisions)),
        }
        decision_rows.append(fact("decisions", event["event_id"], event))
    change["decisions"] = append_events(root, "decisions", now, decision_rows)
    view = rebuild(root, frozen=frozen, registration=reg)
    if view["source_forecasts"] != len(frozen) or view["stream_records"]["observations"] != len(frozen):
        raise ValueError("V6 memory cross-check failed")
    return view, change
