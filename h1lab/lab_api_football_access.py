"""Fail-closed, evidence-only gate for provider-confirmed history restrictions.

A transient 403, timeout, bad JSON, quota exhaustion or mere match age is
NEVER evidence of a historical date restriction. No HTTP requests here.
"""
from __future__ import annotations
import re
from datetime import datetime, timedelta, timezone

SCHEMA = 1
_PLAN = re.compile(r"\b(free|plan|tier|subscription|package)\b", re.I)
_DATE = re.compile(r"\b(date|dates|day|days|historical|history|archive|past|yesterday|tomorrow)\b", re.I)
_DENY = re.compile(r"\b(only|restrict(?:ed|ion)?|not available|unavailable|not allowed|no access|do not have access|does not have access|older than|out of range|outside (?:the )?range|limited to|cannot access|can't access|earliest)\b", re.I)
_QUOTA = re.compile(r"\b(quota|rate limit|requests? per|requests? remaining|too many requests|daily limit)\b", re.I)
_ISO = re.compile(r"20\d{2}-\d{2}-\d{2}")
_REL = re.compile(r"\byesterday\b", re.I)


def _explicit_provider_restriction(detail):
    if not isinstance(detail, dict) or detail.get("category") not in ("HTTP_ERROR", "PROVIDER_ERRORS"):
        return False
    if detail.get("category") == "HTTP_ERROR" and detail.get("http_status") not in (400, 401, 403, 422):
        return False
    message = detail.get("provider_errors", "")
    if not isinstance(message, str) or not message:
        return False
    # Quota/rate-limit 403s are NOT evidence of missing historical access.
    if _QUOTA.search(message):
        return False
    return bool(_PLAN.search(message) and _DATE.search(message) and _DENY.search(message))


def evolve_access(previous, date_errors, now):
    """Persist only historical restrictions actually confirmed by provider."""
    if now.tzinfo is None:
        raise ValueError("UTC clock required")
    now = now.astimezone(timezone.utc)
    if not isinstance(previous, dict) or previous.get("schema_version", SCHEMA) != SCHEMA:
        raise ValueError("Invalid provider-access policy")
    if not isinstance(date_errors, dict):
        raise ValueError("Invalid provider error table")
    out = {"schema_version": SCHEMA,
           "confirmed_restrictions": dict(previous.get("confirmed_restrictions", {}))}
    for day, detail in sorted(date_errors.items()):
        if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", day):
            continue
        try:
            rejected = datetime.fromisoformat(day).date()
        except ValueError:
            continue
        if rejected > now.date() or not _explicit_provider_restriction(detail):
            continue
        message = detail["provider_errors"]
        scope = "DAY_ONLY"
        max_past_days = None
        # Only explicit calendar-day expressions create moving cutoff rules.
        # Do NOT extrapolate a 24h/48h restriction from two failed calls.
        if _REL.search(message) and re.search(r"\b(today|tomorrow|current day)\b", message, re.I):
            scope, max_past_days = "CALENDAR_WINDOW", 1
        evidence = {"checked_day": day, "checked_at_utc": now.isoformat(timespec="seconds"),
                    "category": detail["category"],
                    "http_status": detail.get("http_status"),
                    "provider_errors": message[:200],
                    "scope": scope}
        if max_past_days is not None:
            evidence["max_past_calendar_days"] = max_past_days
        out["confirmed_restrictions"][day] = evidence
    # 45 days is consistent with the existing provider rotation history.
    out["confirmed_restrictions"] = dict(
        sorted(out["confirmed_restrictions"].items())[-45:])
    return out



def restore_access_from_audit(previous, audit, now):
    """Reuse provider denials already paid for, preserving observation times.

    Replays only score-free DATE endpoint errors from the bounded audit.
    It never infers a rolling window or disables fixture-ID requests.
    """
    if (not isinstance(audit, dict) or audit.get("schema_version") != 1
            or not isinstance(audit.get("runs"), list)):
        raise ValueError("Invalid FT API audit")
    out = evolve_access(previous, {}, now)
    observations = []
    for run in audit["runs"]:
        if not isinstance(run, dict):
            raise ValueError("Invalid FT API audit run")
        try:
            stamp = datetime.fromisoformat(run.get("utc", "").replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            continue  # no trustworthy observation time
        if stamp.tzinfo is None or not timedelta(0) <= now - stamp <= timedelta(days=45):
            continue
        provider = (run.get("providers") or {}).get("api_football") or {}
        errors = provider.get("date_errors") or {}
        if not isinstance(errors, dict):
            raise ValueError("Invalid historical date errors")
        observations.append((stamp, errors))
    for stamp, errors in sorted(observations, key=lambda x: x[0], reverse=True):
        unseen = {day: detail for day, detail in errors.items()
                  if day not in out["confirmed_restrictions"]}
        out = evolve_access(out, unseen, stamp)
    return out


def restriction_for_day(access, day, now):
    """Return a provider-confirmed date-list restriction reason or None."""
    if not isinstance(access, dict) or access.get("schema_version", SCHEMA) != SCHEMA:
        return None
    if now.tzinfo is None:
        raise ValueError("UTC clock required")
    if not isinstance(day, str) or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", day):
        return None
    notes = access.get("confirmed_restrictions", {})
    if not isinstance(notes, dict):
        return None
    for rejected, record in notes.items():
        if not isinstance(record, dict):
            continue
        if record.get("scope") == "CALENDAR_WINDOW" and record.get("max_past_calendar_days") == 1:
            min_day = (now.astimezone(timezone.utc).date() - timedelta(days=1)).isoformat()
            if day < min_day:
                return "PROVIDER_CONFIRMED_CALENDAR_HISTORY_LIMIT"
        elif day == rejected and record.get("scope") == "DAY_ONLY":
            return "PROVIDER_CONFIRMED_DAY_HISTORY_RESTRICTION"
    return None


def restriction_for_fixture_id(access, day, now):
    """Only ID-endpoint evidence may suspend reviewed individual fixture requests.

    The persisted history access ledger contains DATE-list response evidence.
    A failure from GET /fixtures?date=... never demonstrates that GET
    /fixtures?id=... is restricted by the same plan window. Until an explicitly
    scoped, independently validated ID policy exists, preserve ID eligibility.
    """
    return None
