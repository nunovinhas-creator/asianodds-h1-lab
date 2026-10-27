"""BSD football v2 score verification, fail-closed on unclear 90-minute data.

Docs: https://sports.bzzoiro.com/docs/football/events/
Only the configured BSD_API_KEY is sent in Authorization: Token.
"""
import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .results import norm_team

ROOT = "https://sports.bzzoiro.com/api/v2/events/"
UTC = timezone.utc


class BSDProviderError(RuntimeError):
    pass


def request_json(url, token):
    if not url.startswith(ROOT):
        raise BSDProviderError("BSD rejected an unexpected results API URL")
    request = Request(url, headers={
        "Authorization": "Token " + token,
        "Accept": "application/json",
        "User-Agent": "AsianOdds-H1-Lab/1.0",
    })
    try:
        with urlopen(request, timeout=15) as response:
            if response.status != 200:
                raise BSDProviderError("BSD returned an unexpected HTTP status")
            return json.loads(response.read(1500000))
    except HTTPError as exc:
        # Never print the URL, response body or Authorization header.
        raise BSDProviderError("BSD HTTP " + str(exc.code)) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise BSDProviderError("BSD unavailable or response invalid") from None


def event_name(event, key):
    value = event.get(key)
    if isinstance(value, dict):
        return value.get("name") or ""
    if isinstance(value, str):
        return value
    return event.get(key + "_name") or ""


def event_kickoff(event):
    value = next((event.get(key) for key in
                  ("event_date", "start_time", "kickoff", "scheduled_at")
                  if event.get(key)), None)
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo is not None else None


def matches_identity(signal, event):
    if not isinstance(event, dict):
        return False
    if norm_team(event_name(event, "home_team")) != norm_team(signal["home"]):
        return False
    if norm_team(event_name(event, "away_team")) != norm_team(signal["away"]):
        return False
    moment = event_kickoff(event)
    if moment is None:
        return False
    kickoff = datetime.fromisoformat(signal["kickoff_utc"]).astimezone(UTC)
    return abs((moment - kickoff).total_seconds()) <= 90 * 60


def regulation_result(signal, event):
    """Return final regulation score or (None, diagnostic)."""
    if not matches_identity(signal, event):
        return None, "match_identity_mismatch"
    if event.get("status") != "finished":
        return None, "not_finished"
    # Fail closed if optional status fields contradict normal-time settlement.
    for field in ("postponed", "cancelled", "abandoned"):
        if event.get(field) is True:
            return None, "not_played"
    for field in ("extra_time_score", "penalty_shootout"):
        if event.get(field) is not None:
            return None, "extra_time_requires_review"
    try:
        h, a = event["home_score"], event["away_score"]
        if not all(type(n) is int and n >= 0 for n in (h, a)):
            raise ValueError("invalid score")
        event_id = event["id"]
        if type(event_id) is not int or event_id <= 0:
            raise ValueError("invalid event id")
    except (KeyError, ValueError, TypeError):
        return None, "invalid_regulation_score"
    return {
        "match_key": signal["match_key"],
        "status": "final",
        "home_goals": h,
        "away_goals": a,
        "source": ROOT + str(event_id) + "/",
    }, "verified_bsd_ft"


def find_result(signal, fetch=request_json, token=None):
    token = (token if token is not None else os.environ.get("BSD_API_KEY", "")).strip()
    if not token:
        return None, "bsd_not_configured"
    kickoff = datetime.fromisoformat(signal["kickoff_utc"]).astimezone(UTC)
    params = {
        "team_name": signal["home"],
        "date_from": kickoff.date().isoformat(),
        "date_to": kickoff.date().isoformat(),
        "status": "finished",
        "limit": 200,
    }
    payload = fetch(ROOT + "?" + urlencode(params), token)
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise BSDProviderError("BSD unexpected event list shape")
    results = payload["results"]
    # Never silently choose among incomplete paginated or ambiguous results.
    if payload.get("next"):
        return None, "bsd_paginated_requires_review"
    matches = [item for item in results if matches_identity(signal, item)]
    if not matches:
        return None, "bsd_no_exact_match"
    if len(matches) != 1:
        return None, "bsd_ambiguous_match"
    event = matches[0]
    eid = event.get("id")
    if type(eid) is not int or eid <= 0:
        return None, "bsd_no_event_id"
    detail = fetch(ROOT + str(eid) + "/", token)
    if not isinstance(detail, dict) or detail.get("id") != eid:
        return None, "bsd_detail_mismatch"
    return regulation_result(signal, detail)
