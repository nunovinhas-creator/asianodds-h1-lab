"""Scheduled LAB-only result collector. No H1 mutations, no channel text."""
from __future__ import annotations

import json
import os
import time
from collections import Counter
from urllib.error import HTTPError, URLError
from datetime import datetime, timezone
from pathlib import Path

from h1lab.lab_results import reconcile
from h1lab.lab_espn import ESPNResults
from h1lab.lab_bsd_search import BSDDateFallback, summary as bsd_date_summary

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


class PacedTSDB:
    """Protect free-tier throughput (<30 requests/minute) and record 429s."""
    def __init__(self, interval=2.3):
        self.interval = interval
        self.last = None
        self.rate_limited = False
        self.counts = Counter()

    def lookup(self, signal):
        if self.rate_limited:
            self.counts["suppressed_after_429"] += 1
            return None, "tsdb_limited_this_run"
        if self.last is not None:
            gap = time.monotonic() - self.last
            if gap < self.interval:
                time.sleep(self.interval - gap)
        self.last = time.monotonic()
        self.counts["requested"] += 1
        from h1lab.results import api_events, choose_result
        try:
            found, reason = choose_result(signal, api_events(signal))
        except HTTPError as exc:
            if exc.code == 429:
                self.rate_limited = True
                self.counts["http_429"] += 1
                return None, "tsdb_http_429"
            self.counts["http_error"] += 1
            return None, "tsdb_http_error"
        except (OSError, ValueError, TimeoutError, URLError):
            self.counts["unavailable"] += 1
            return None, "tsdb_unavailable"
        self.counts[reason] += 1
        return found, reason


def competitions_by_key(alerts):
    observed = {}
    conflicted = set()
    for item in alerts:
        if not isinstance(item, dict):
            continue
        key, comp = item.get("match_key"), item.get("competition")
        if not isinstance(key, str) or not isinstance(comp, str) or not comp:
            continue
        if key in observed and observed[key] != comp:
            conflicted.add(key)
        observed[key] = comp
    return {key:comp for key,comp in observed.items() if key not in conflicted}


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
    checks = int(os.environ.get("LAB_RESULTS_MAX_CHECKS", "30"))
    bsd_finder = BSDDateFallback(
        token=os.environ.get("BSD_API_KEY", ""),
        max_days=int(os.environ.get("LAB_BSD_DATE_MAX_DAYS", "3")),
        max_pages=int(os.environ.get("LAB_BSD_DATE_MAX_PAGES", "3")),
    )
    tsdb = PacedTSDB()
    espn = ESPNResults(competitions_by_key(state.get("alerts", [])), max_scoreboards=12)
    next_ledger, report, queried = reconcile(
        state, read_v4(), existing, now=datetime.now(timezone.utc),
        bsd_lookup=bsd_finder.lookup, tsdb_lookup=tsdb.lookup,
        espn_lookup=espn.lookup, max_checks=checks)
    report["bsd_date_search"] = bsd_date_summary(bsd_finder)
    report["thesportsdb_search"] = dict(sorted(tsdb.counts.items()))
    report["espn_scoreboards"] = espn.summary()
    changed_ledger = write_if_changed(LEDGER, next_ledger)
    changed_report = write_if_changed(REPORT, report)
    print("LAB_FT_RESULT_SYNC", "catalog", report["matches"],
          "final", report["final_recorded"], "unverified", report["unverified"],
          "queried", queried, "bsd_date_pages", report["bsd_date_search"]["date_list_requests"],
          "espn_confirmed", report["espn_scoreboards"]["confirmed_in_run"],
          "espn_requests", report["espn_scoreboards"]["requests"],
          "tsdb_requests", report["thesportsdb_search"].get("requested", 0),
          "pending_due", report["pending_due_checks"],
          "ledger_written", changed_ledger, "report_written", changed_report)
    return report


if __name__ == "__main__":
    main()
