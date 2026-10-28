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
from h1lab.lab_sportscore import SportScoreResults
from h1lab.lab_monte_bsd import MonteBSDCrosswalk
from h1lab.lab_bsd_search import BSDDateFallback, summary as bsd_date_summary
from h1lab.lab_ft_diagnostics import coverage_diagnostics
from h1lab.lab_fotmob import FotMobResults
from h1lab.lab_api_football import APIFootballResults

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
    now = datetime.now(timezone.utc)
    bsd_finder = BSDDateFallback(
        token=os.environ.get("BSD_API_KEY", ""),
        max_days=int(os.environ.get("LAB_BSD_DATE_MAX_DAYS", "3")),
        max_pages=int(os.environ.get("LAB_BSD_DATE_MAX_PAGES", "3")),
    )
    monte = MonteBSDCrosswalk(
        token=os.environ.get("BSD_API_KEY", ""), max_event_requests=12)
    def bsd_with_monte(signal):
        primary, reason = bsd_finder.lookup(signal)
        if primary is not None:
            return primary, reason
        # Do not re-query BSD on provider failures or throttling.
        if reason not in ("bsd_no_exact_match","bsd_no_exact_match_in_date",
                          "bsd_date_budget_deferred","bsd_paginated_requires_review"):
            return None, reason
        second, second_reason = monte.lookup(signal)
        return (second, second_reason) if second is not None else (None, second_reason)

    tsdb = PacedTSDB()
    fotmob_enabled = os.environ.get('LAB_FOTMOB_LICENSED', '0') == '1'
    fotmob = FotMobResults(max_days=3 if fotmob_enabled else 0)
    # Free API-Sports tier is 100 calls/day. Poll only scheduled runs
    # on even UTC hours before :30, at most 3 date calls per eligible run.
    # This prevents an automatic 48 * 3 = 144/day loop.
    api_key = os.environ.get("API_FOOTBALL_KEY", "")
    api_football_poll = (bool(api_key.strip())
                         and os.environ.get("LAB_API_FOOTBALL_SCHEDULED") == "true"
                         and now.hour % 2 == 0 and now.minute < 30)
    api_football = APIFootballResults(key=api_key,
                                      max_days=3 if api_football_poll else 0)
    mapped_competitions = competitions_by_key(state.get("alerts", []))
    espn = ESPNResults(mapped_competitions, max_scoreboards=12)
    sportscore = SportScoreResults(mapped_competitions, max_requests=45,max_team_searches=20)
    next_ledger, report, queried = reconcile(
        state, read_v4(), existing, now=now,
        bsd_lookup=bsd_with_monte, tsdb_lookup=tsdb.lookup,
        espn_lookup=espn.lookup, sportscore_lookup=sportscore.lookup,
        fotmob_lookup=fotmob.lookup if fotmob_enabled else None,
        api_football_lookup=api_football.lookup if api_football_poll else None,
        max_checks=checks)
    report["bsd_date_search"] = bsd_date_summary(bsd_finder)
    report["monte_carlos_bsd"] = monte.summary()
    report["thesportsdb_search"] = dict(sorted(tsdb.counts.items()))
    report["espn_scoreboards"] = espn.summary()
    report["sportscore_search"] = sportscore.summary()
    report["fotmob_search"] = fotmob.summary()
    report["fotmob_search"]["licensed_automation_enabled"] = fotmob_enabled
    report["api_football_search"] = api_football.summary()
    report["api_football_search"]["scheduled_poll_enabled"] = api_football_poll
    report["coverage_diagnostics"] = coverage_diagnostics(next_ledger, report)
    changed_ledger = write_if_changed(LEDGER, next_ledger)
    changed_report = write_if_changed(REPORT, report)
    print("LAB_FT_RESULT_SYNC", "catalog", report["matches"],
          "final", report["final_recorded"], "unverified", report["unverified"],
          "queried", queried, "bsd_date_pages", report["bsd_date_search"]["date_list_requests"],
          "monte_bsd_resolved", report["monte_carlos_bsd"]["verified_in_run"],
          "monte_bsd_archive", report["monte_carlos_bsd"]["archive_status"],
          "monte_core_candidates", report["monte_carlos_bsd"]["core_name_event_id_candidates"],
          "monte_core_verified", report["monte_carlos_bsd"]["verified_core_name_in_run"],
          "espn_confirmed", report["espn_scoreboards"]["confirmed_in_run"],
          "espn_requests", report["espn_scoreboards"]["requests"],
          "api_football_verified", report["api_football_search"]["verified_in_run"],
          "api_football_requests", report["api_football_search"]["requests"],
          "fotmob_verified", report["fotmob_search"]["verified_in_run"],
          "fotmob_requests", report["fotmob_search"]["requests"],
          "sportscore_ft", report["sportscore_search"]["confirmed_in_run"],
          "sportscore_requests", report["sportscore_search"]["requests"],
          "tsdb_requests", report["thesportsdb_search"].get("requested", 0),
          "pending_due", report["pending_due_checks"],
          "ledger_written", changed_ledger, "report_written", changed_report)
    return report


if __name__ == "__main__":
    main()
