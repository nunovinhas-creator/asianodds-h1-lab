"""BSD date-indexed fallback for LAB only.

A fuzzy team_name search can miss a fixture even when BSD has it. We search a
strictly bounded complete date slice and validate the candidate against the
original observed home/away names and kickoff. Incomplete pagination never
produces a verified match.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlencode

from .bsd import (ROOT, BSDProviderError, event_kickoff, find_result,
                  matches_identity, regulation_result, request_json)

PAGE_SIZE = 200
MAX_DAYS = 4
MAX_PAGES = 4
FALLBACK_REASONS = frozenset({"bsd_no_exact_match", "bsd_paginated_requires_review"})


class BSDDateFallback:
    """One-run cache, bounded by days and per-day pages. No persistent API key."""

    def __init__(self, *, token, fetch=request_json, primary=find_result,
                 max_days=3, max_pages=3):
        if not 0 <= max_days <= MAX_DAYS or not 1 <= max_pages <= MAX_PAGES:
            raise ValueError("BSD date search budget out of bounds")
        self.token = (token or "").strip()
        self.fetch = fetch
        self.primary = primary
        self.max_days = max_days
        self.max_pages = max_pages
        self.days = {}  # day -> (list of events, diagnostic); never persisted
        self.date_requests = 0
        self.details_requested = 0
        self.diagnostics = Counter()

    @staticmethod
    def _kickoff(signal):
        raw = signal.get("kickoff_utc")
        if not isinstance(raw, str):
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt.astimezone(timezone.utc) if dt.tzinfo else None

    def _date_index(self, day):
        if day in self.days:
            return self.days[day]
        if len(self.days) >= self.max_days:
            return [], "bsd_date_budget_deferred"

        # Reserve day before first request so outages do not cause repeated
        # requests for each different fixture on the same matchday.
        self.days[day] = ([], "bsd_date_unavailable")
        rows = []
        seen_pages = set()
        for page in range(self.max_pages):
            offset = PAGE_SIZE * page
            if offset in seen_pages:
                break
            seen_pages.add(offset)
            url = ROOT + "?" + urlencode({
                "date_from": day, "date_to": day, "status": "finished",
                "limit": PAGE_SIZE, "offset": offset,
            })
            self.date_requests += 1
            try:
                data = self.fetch(url, self.token)
            except BSDProviderError:
                self.days[day] = ([], "bsd_date_unavailable")
                return self.days[day]
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                self.days[day] = ([], "bsd_date_invalid_shape")
                return self.days[day]
            items = data["results"]
            if not all(isinstance(item, dict) for item in items):
                self.days[day] = ([], "bsd_date_invalid_rows")
                return self.days[day]
            rows.extend(items)
            if data.get("next") is None or data.get("next") is False:
                self.days[day] = (rows, "complete")
                return self.days[day]
            # Any incomplete page list cannot certify uniqueness.
            if not isinstance(data["next"], str) or not data["next"]:
                self.days[day] = ([], "bsd_date_ambiguous_pagination")
                return self.days[day]
        self.days[day] = ([], "bsd_date_incomplete_pagination")
        return self.days[day]

    def lookup(self, signal):
        """Lookup one game and record the diagnostic for coverage reporting."""
        result, reason = self._lookup(signal)
        self.diagnostics[reason] += 1
        return result, reason

    def _lookup(self, signal):
        """Prefer established strict team-name lookup, then date fallback."""
        if not self.token:
            return None, "bsd_not_configured"
        kickoff = self._kickoff(signal)
        if kickoff is None:
            return None, "bsd_invalid_kickoff"
        try:
            result, reason = self.primary(signal, fetch=self.fetch, token=self.token)
        except BSDProviderError:
            return None, "bsd_primary_unavailable"
        if result is not None or reason not in FALLBACK_REASONS:
            return result, reason

        day = kickoff.date().isoformat()
        events, diagnostic = self._date_index(day)
        if diagnostic != "complete":
            return None, diagnostic

        matches = [event for event in events if matches_identity(signal, event)]
        # Distinct IDs only; duplicate pages or reused IDs with inconsistent
        # source data never justify accepting a unique match.
        ids = [e.get("id") for e in matches]
        if len(matches) == 0:
            return None, "bsd_no_exact_match_in_date"
        if len(matches) != 1 or type(ids[0]) is not int or ids[0] <= 0:
            return None, "bsd_date_ambiguous_match"

        self.details_requested += 1
        try:
            detail = self.fetch(ROOT + str(ids[0]) + "/", self.token)
        except BSDProviderError:
            return None, "bsd_detail_unavailable"
        if not isinstance(detail, dict) or detail.get("id") != ids[0]:
            return None, "bsd_detail_mismatch"
        result, verification = regulation_result(signal, detail)
        if result is None:
            return None, "bsd_date_" + verification
        return result, "verified_bsd_ft_via_date"


def summary(search: BSDDateFallback):
    return {"date_days_examined": len(search.days),
            "date_list_requests": search.date_requests,
            "date_detail_requests": search.details_requested,
            "date_complete_days": sum(s == "complete" for _, s in search.days.values()),
            "date_incomplete_days": sum(s != "complete" for _, s in search.days.values()),
            "lookup_reason_counts": dict(sorted(search.diagnostics.items())),
            "fallback_results_recovered": search.diagnostics["verified_bsd_ft_via_date"]}
