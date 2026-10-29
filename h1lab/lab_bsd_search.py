"""BSD date-indexed fallback for LAB only.

A fuzzy team_name search can miss a fixture even when BSD has it. We search a
strictly bounded complete date slice and validate the candidate against the
original observed home/away names and kickoff. Incomplete pagination never
produces a verified match.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from .bsd import (ROOT, BSDProviderError, event_kickoff, event_name, find_result,
                  matches_identity, regulation_result, request_json)
from .lab_identity import CORE, EXACT, IDENTITY_VERSION, select_event
from .lab_bsd_payload import normalized_payload

PAGE_SIZE = 200
MAX_DAYS = 4
MAX_PAGES = 4
FALLBACK_REASONS = frozenset({"bsd_no_exact_match", "bsd_paginated_requires_review"})


def date_in_cooldown(probes, day, now):
    """Single policy used by planner and HTTP boundary, including future stamps."""
    raw = (probes.get(day) or {}).get("attempted_at_utc")
    try:
        attempted = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return False
    return attempted.tzinfo is not None and now < attempted + timedelta(hours=4)


class BSDDateFallback:
    """One-run cache, bounded by days and per-day pages. No persistent API key."""

    def __init__(self, *, token, fetch=request_json, primary=find_result,
                 max_days=3, max_pages=3, require_count=False, probes=None, now=None):
        if not 0 <= max_days <= MAX_DAYS or not 1 <= max_pages <= MAX_PAGES:
            raise ValueError("BSD date search budget out of bounds")
        self.token = (token or "").strip()
        # LAB-only translation of BSD envelopes, mirroring the owner's
        # working Monte-Carlos settlement parser. Exactly one HTTP fetch
        # per invocation, with no changes to the shared H1 bsd.py.
        self.fetch = lambda url, token: normalized_payload(fetch(url, token))
        self.primary = primary
        self.max_days = max_days
        self.max_pages = max_pages
        self.require_count = require_count
        self.probes = probes if probes is not None else {}
        self.now = now if now is not None else datetime.now(timezone.utc)
        if self.now.tzinfo is None:
            raise ValueError("BSD clock must be timezone aware")
        self.deferred_days = {}
        self.requests_by_path = Counter()
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

    def _date_index(self, day, *, path="fallback"):
        if day in self.days:
            return self.days[day]
        if date_in_cooldown(self.probes, day, self.now):
            self.deferred_days[day] = "bsd_date_cooldown_deferred"
            return [], "bsd_date_cooldown_deferred"
        if len(self.days) >= self.max_days:
            self.deferred_days[day] = "bsd_date_budget_deferred"
            return [], "bsd_date_budget_deferred"

        # Reserve day before first request so outages do not cause repeated
        # requests for each different fixture on the same matchday.
        self.days[day] = ([], "bsd_date_unavailable")
        rows = []
        seen_pages = set()
        expected_total = None
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
            self.requests_by_path[path] += 1
            try:
                data = self.fetch(url, self.token)
            except BSDProviderError:
                self.days[day] = ([], "bsd_date_unavailable")
                return self.days[day]
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                self.days[day] = ([], "bsd_date_invalid_shape")
                return self.days[day]
            items = data["results"]
            if (len(items)>PAGE_SIZE or
                    not all(isinstance(item, dict) for item in items)):
                self.days[day] = ([], "bsd_date_invalid_rows")
                return self.days[day]
            total=data.get("count")
            if ((self.require_count and (type(total) is not int or total<0))
                    or (total is not None and
                        (type(total) is not int or total<0))):
                self.days[day] = ([], "bsd_date_invalid_total")
                return self.days[day]
            if page and total != expected_total:
                self.days[day] = ([], "bsd_date_total_changed")
                return self.days[day]
            expected_total = total
            rows.extend(items)
            if data.get("next") is None or data.get("next") is False:
                # Official BSD pagination 'count' denotes TOTAL results,
                # not the current page. A partial response must NEVER
                # produce certified reusable event IDs.
                if total is not None and total!=len(rows):
                    self.days[day] = ([], "bsd_date_total_mismatch")
                    return self.days[day]
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
        level = EXACT
        if not matches:
            # Second pass on the SAME complete date list (no extra list request):
            # designator/exonym-only name differences, fail-closed on ambiguity.
            chosen, level, why = select_event(
                signal, events,
                lambda ev: (event_name(ev, "home_team"), event_name(ev, "away_team")),
                event_kickoff)
            if chosen is None:
                return None, ("bsd_no_exact_match_in_date" if why == "identity_no_core_match"
                              else "bsd_date_" + why)
            matches = [chosen]
        # Distinct IDs only; duplicate pages or reused IDs with inconsistent
        # source data never justify accepting a unique match.
        ids = [e.get("id") for e in matches]
        if len(matches) != 1 or type(ids[0]) is not int or ids[0] <= 0:
            return None, "bsd_date_ambiguous_match"

        self.details_requested += 1
        try:
            detail = self.fetch(ROOT + str(ids[0]) + "/", self.token)
        except BSDProviderError:
            return None, "bsd_detail_unavailable"
        if not isinstance(detail, dict) or detail.get("id") != ids[0]:
            return None, "bsd_detail_mismatch"
        probe = signal
        if level == CORE:
            # The detail must carry the same provider names that were matched.
            names = (event_name(matches[0], "home_team"), event_name(matches[0], "away_team"))
            if (event_name(detail, "home_team"), event_name(detail, "away_team")) != names:
                return None, "bsd_date_core_detail_name_changed"
            probe = dict(signal, home=names[0], away=names[1])
        result, verification = regulation_result(probe, detail)
        if result is None:
            return None, "bsd_date_" + verification
        if level == CORE:
            result["identity_match"] = CORE
            result["identity_version"] = IDENTITY_VERSION
            return result, "verified_bsd_ft_via_date_core_name"
        return result, "verified_bsd_ft_via_date"


def summary(search: BSDDateFallback):
    return {"date_days_examined": len(search.days),
            "date_list_requests": search.date_requests,
            "date_detail_requests": search.details_requested,
            "date_complete_days": sum(s == "complete" for _, s in search.days.values()),
            "date_incomplete_days": sum(s != "complete" for _, s in search.days.values()),
            "lookup_reason_counts": dict(sorted(search.diagnostics.items())),
            "fallback_results_recovered": (search.diagnostics["verified_bsd_ft_via_date"] +
                                           search.diagnostics["verified_bsd_ft_via_date_core_name"]),
            "core_name_results_recovered": search.diagnostics["verified_bsd_ft_via_date_core_name"]}
