"""Append-only formal registration of the historic post-hoc V6 hypothesis.

Registration date is the *current execution time*; selection date is a
documented historic audit claim and never a synthetic prospective record.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

from .v6_shadow import canonical, utc, HYPOTHESIS

PATH = "data/lab/v6-hypotheses.jsonl"
DEFINITION = {"all": ["G_MULTI_ALERT"], "none": ["M_IMPLIED_GOALS_DOWN"], "op": "AND_NOT"}
RULE_VERSION = "V6-AUDIT-2026-10-28"
ORIGIN_SELECTED_AT = "2026-10-28T11:16:00+00:00"


def definition_digest():
    return hashlib.sha256(canonical({"definition": DEFINITION, "rule_version": RULE_VERSION}).encode()).hexdigest()


def record(now):
    if now.tzinfo is None:
        raise ValueError("registered_at requires timezone")
    row = {
        "schema_version": 1, "id": HYPOTHESIS, "definition": DEFINITION,
        "definition_sha256": definition_digest(), "rule_version": RULE_VERSION,
        "outcome": "OVER_2_5", "comparison": "market_model_residual",
        "origin": "POST_HOC_RANKING_SELECTION",
        "selected_at_claimed": ORIGIN_SELECTED_AT,
        "registered_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "discovery_snapshot": {"confirmed_ft": 11, "over_hits": 10, "nominal_p": 0.016,
                               "fdr_q": 1.0, "external_audit_date": "2026-10-28"},
        "confidence_label": "EXPLORATORY_NOT_VALIDATED",
        "prospective_rule": "only V6 journal snapshots with known_at earlier than kickoff",
        "method": "fixed mixture e-process vs quality-vetted Poisson market model",
        "not_same_as": "pattern_watch_strict_episodes",
    }
    row["sha256"] = hashlib.sha256(canonical(row).encode()).hexdigest()
    return row


def ensure_registered(root, now):
    path = Path(root) / PATH
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) != 1:
            raise ValueError("Unexpected hypothesis history: do not overwrite")
        entry = json.loads(lines[0])
        digest = entry.pop("sha256", None)
        if (digest != hashlib.sha256(canonical(entry).encode()).hexdigest()
                or entry.get("id") != HYPOTHESIS
                or entry.get("definition") != DEFINITION
                or entry.get("definition_sha256") != definition_digest()):
            raise ValueError("Frozen V6 hypothesis was modified")
        entry["sha256"] = digest
        return entry, False
    entry = record(now)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical(entry) + "\n")
    return entry, True
