"""Publish one manually confirmed, validated LLM research draft to GitHub Pages.

The caller is a separate, short-lived GitHub Actions job with contents:write.
This module never calls an AI provider and does not touch scientific journals.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
import hashlib
import json
from math import comb
from pathlib import Path
import re

from h1lab.v6_llm_investigator import build_packet, strict_json, validate_proposals, provider_usage
from h1lab.v6_discovery_planner import plan, candidate_id

ROOT = Path(__file__).resolve().parents[1]
INDEX = Path("docs/lab/llm-investigator-index.json")
ARCHIVE = Path("docs/lab/llm-investigator-runs")
QUEUE = Path("docs/lab/llm-discovery-plan.json")
STATUS = "SHADOW_DRAFT_NOT_EMPIRICALLY_VALIDATED"


def _read(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 80000:
        raise ValueError("INVALID_LLM_REPORT_FILE")
    return strict_json(path.read_text(encoding="utf-8"))


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    path.write_text(rendered, encoding="utf-8")


def _frontier(features):
    """Exact combinatorial *potential*, NOT combinations tried by a model."""
    families = Counter(item["family"] for item in features)
    n = len(features)
    return {
        "features_in_catalogue": n,
        "possible_pairs_distinct_families": comb(n, 2) - sum(comb(v, 2) for v in families.values() if v >= 2),
        # The planner requires all 3 codes to have DIFFERENT families, not
        # merely two or more families represented in a triple.
        "possible_triples_distinct_families": sum(a * b * c for a, b, c in combinations(families.values(), 3)),
        "meaning": "SEARCH_SPACE_ONLY_NO_LLM_CALLS_OR_EMPIRICAL_TESTS",
    }


def publish(root, output, *, run_id, commit_sha, when):
    root = Path(root)
    if not isinstance(run_id, str) or not re.fullmatch(r"[1-9][0-9]{5,17}", run_id):
        raise ValueError("INVALID_RUN_ID")
    if not isinstance(commit_sha, str) or not re.fullmatch(r"[a-f0-9]{40}", commit_sha):
        raise ValueError("INVALID_SOURCE_COMMIT")
    dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("RUN_TIMESTAMP_NOT_UTC")
    when = dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    packet = build_packet(root)
    if not isinstance(output, dict) or set(output) - {"provider_usage", "autonomy"} != {"status", "source_sha256", "proposals", "notice"}:
        raise ValueError("UNEXPECTED_INVESTIGATION_FORMAT")
    if output["source_sha256"] != packet["source_sha256"]:
        raise ValueError("INVESTIGATION_SOURCE_HASH_MISMATCH")
    validated = validate_proposals(
        packet, {"schema_version": 1, "proposals": output["proposals"]}
    )
    if {k: v for k, v in output.items() if k not in ("provider_usage", "autonomy")} != validated:
        raise ValueError("INVESTIGATION_VALIDATION_MISMATCH")
    usage = output.get("provider_usage")
    if usage is not None:
        if not isinstance(usage, dict) or usage != provider_usage(
                {"usage": usage.get("tokens")}, "@cf/meta/llama-3.1-8b-instruct-fast"):
            raise ValueError("INVALID_PROVIDER_USAGE")
    proposal = validated["proposals"][0]
    autonomy = output.get("autonomy")
    if autonomy is not None:
        expected = {"schema_version", "trigger", "candidate_id",
                    "candidate_pool_ids", "selection_policy",
                    "daily_scheduled_call_slots", "account_neurons_verified", "status"}
        if (not isinstance(autonomy, dict) or set(autonomy) != expected
                or autonomy["schema_version"] != 1
                or autonomy["trigger"] not in ("schedule", "workflow_dispatch")
                or autonomy["status"] != "SHADOW_EXPLORATION_NOT_VALIDATION"
                or autonomy["account_neurons_verified"] is not False
                or autonomy["daily_scheduled_call_slots"] != 4
                or autonomy["selection_policy"] !=
                   "HASH_ORDER_OUTCOME_BLIND_PREFER_PAIRS_ONE_TRIPLE"
                or not isinstance(autonomy["candidate_pool_ids"], list)
                or not 1 <= len(autonomy["candidate_pool_ids"]) <= 3
                or any(not isinstance(cid, str) or not re.fullmatch(r"[0-9a-f]{64}", cid)
                       for cid in autonomy["candidate_pool_ids"])
                or len(set(autonomy["candidate_pool_ids"])) != len(autonomy["candidate_pool_ids"])
                or autonomy["candidate_id"] != candidate_id(proposal["feature_codes"])
                or autonomy["candidate_id"] not in autonomy["candidate_pool_ids"]):
            raise ValueError("INVALID_AUTONOMOUS_PROVENANCE")
    run = {
        "schema_version": 1,
        "state": STATUS,
        "run_id": int(run_id),
        "recorded_at_utc": when,
        "source_commit": commit_sha,
        "github_run_url": "https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/" + run_id,
        "model": "@cf/meta/llama-3.1-8b-instruct-fast",
        "llm_calls": 1,
        "neurons_consumed": None,
        "provider_usage": usage,
        "autonomy": autonomy,
        "scientific_acceptance": "INCONCLUSIVO",
        "source_sha256": packet["source_sha256"],
        "proposals": validated["proposals"],
        "summary": {
            "proposal_count": len(validated["proposals"]),
            "topic_id": proposal["topic_id"],
            "feature_codes": proposal["feature_codes"],
            "metric": proposal["metric"],
        },
        "limitations": "Manual AI draft, not a discovered edge, statistical test, ROI or recommendation.",
    }
    archive_path = root / ARCHIVE / (run_id + ".json")
    index_path = root / INDEX
    # Idempotent archive: no rewrite of a different version of an existing run.
    if archive_path.exists():
        if _read(archive_path) != run:
            raise ValueError("ARCHIVED_RUN_IMMUTABILITY_VIOLATION")
    else:
        _save(archive_path, run)
    if index_path.exists():
        current = _read(index_path)
        if current.get("schema_version") != 1 or current.get("state") != STATUS:
            raise ValueError("INVALID_LLM_INDEX")
        history = current.get("history")
        if not isinstance(history, list) or len(history) > 30:
            raise ValueError("INVALID_LLM_INDEX_HISTORY")
    else:
        history = []
    if any(x.get("run_id") == run["run_id"] and x.get("source_commit") != commit_sha for x in history):
        raise ValueError("RUN_ID_PROVENANCE_CONFLICT")
    entry = {
        "run_id": run["run_id"],
        "recorded_at_utc": when,
        "topic_id": proposal["topic_id"],
        "feature_codes": proposal["feature_codes"],
        "metric": proposal["metric"],
        "source_commit": commit_sha,
        "archive": "lab/llm-investigator-runs/" + run_id + ".json",
    }
    history = [x for x in history if x.get("run_id") != run["run_id"]] + [entry]
    history.sort(key=lambda x: x["run_id"], reverse=True)
    history = history[:20]
    latest = run if history[0]["run_id"] == run["run_id"] else _read(
        root / ARCHIVE / (str(history[0]["run_id"]) + ".json")
    )
    index = {
        "schema_version": 1,
        "state": STATUS,
        "latest": latest,
        "history": history,
        "search_space": _frontier(packet["feature_catalogue"]),
        "llm_executions_recorded": len(history),
        "empirically_validated_strategies": 0,
        "notice": "Only successful published runs (manual or bounded autonomous) appear here; failures remain in GitHub Actions. Scientific validation remains human gated.",
    }
    # Regenerate the offline queue against ALL immutable archives, including
    # this run, in the same commit. No model calls or extra network requests.
    queue = plan(root, limit=10)
    strict_space = index["search_space"]
    if (queue["distinct_family_space"]["2"] != strict_space["possible_pairs_distinct_families"]
            or queue["distinct_family_space"]["3"] != strict_space["possible_triples_distinct_families"]
            or queue["remaining"] + queue["previously_proposed_unique"] !=
                sum(queue["distinct_family_space"].values())):
        raise ValueError("LLM_QUEUE_SEARCH_SPACE_MISMATCH")
    _save(index_path, index)
    _save(root / QUEUE, queue)
    return index


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--source-commit", required=True)
    args = p.parse_args(argv)
    output = _read(args.input)
    now = datetime.now(timezone.utc).isoformat()
    result = publish(args.root, output, run_id=args.run_id,
                     commit_sha=args.source_commit, when=now)
    print("LLM_REPORT_PUBLISHED_DRAFT_ONLY", result["latest"]["run_id"],
          result["latest"]["summary"]["topic_id"])


if __name__ == "__main__":
    main()
