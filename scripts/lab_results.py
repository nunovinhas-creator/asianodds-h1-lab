"""Scheduled LAB-only result collector. No H1 mutations, no channel text."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from h1lab.lab_results import reconcile

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "data/lab/ft-ledger.json"
REPORT = ROOT / "docs/lab/ft-results.json"


def read_v4():
    rows = []
    for path in sorted((ROOT / "data/lab").glob("markets-*.jsonl")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("Invalid V4 row")
                rows.append(item)
    return rows


def lookup_bsd(signal):
    if not os.environ.get("BSD_API_KEY", "").strip():
        return None, "bsd_not_configured"
    from h1lab.bsd import find_result
    return find_result(signal)


def lookup_thesportsdb(signal):
    from h1lab.results import api_events, choose_result
    return choose_result(signal, api_events(signal))


def write_if_changed(path, data):
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == payload:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)
    return True


def main():
    state = json.loads((ROOT / "data/state.json").read_text(encoding="utf-8"))
    existing = (json.loads(LEDGER.read_text(encoding="utf-8"))
                if LEDGER.exists() else {"schema_version": 1, "matches": {}})
    checks = int(os.environ.get("LAB_RESULTS_MAX_CHECKS", "20"))
    next_ledger, report, queried = reconcile(
        state, read_v4(), existing, now=datetime.now(timezone.utc),
        bsd_lookup=lookup_bsd, tsdb_lookup=lookup_thesportsdb, max_checks=checks)
    changed_ledger = write_if_changed(LEDGER, next_ledger)
    changed_report = write_if_changed(REPORT, report)
    print("LAB_FT_RESULT_SYNC", "catalog", report["matches"],
          "final", report["final_recorded"], "unverified", report["unverified"],
          "queried", queried, "pending_due", report["pending_due_checks"],
          "ledger_written", changed_ledger, "report_written", changed_report)
    return report


if __name__ == "__main__":
    main()
