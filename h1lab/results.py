"""Conservative final-score reconciler using TheSportsDB free V1 search.

Never infer a final score from a fixture's odds, kickoff or an unverified event.
Automatic settlement requires exact ordered team names, kickoff corroboration,
explicit FT status, no extra-time/penalties indicators and numeric scores.
"""
import csv
import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .cli import ROOT, read_state, save
from .core import load_results

UTC = timezone.utc
RESULTS = ROOT / "data/results.csv"
AUDIT = ROOT / "data/result_audit.json"
API = "https://www.thesportsdb.com/api/v1/json/123/searchevents.php"
HEADERS = ("match_key", "status", "home_goals", "away_goals", "source")
BLOCKED_CONTEXT = re.compile(r"extra.time|after.extra.time|aet|penalt|shoot.out|spot.kick", re.I)


class TheSportsDBProviderError(OSError):
    """Safe, classified supplier failure; never includes URLs or response bodies."""

    def __init__(self, reason, *, stop_cycle=False):
        super().__init__(reason)
        self.reason = reason
        self.stop_cycle = stop_cycle


def parse_provider_events(payload):
    """An HTTP 200 containing an API error is NOT an empty event search."""
    if not isinstance(payload, dict):
        raise TheSportsDBProviderError("thesportsdb_invalid_payload")
    if payload.get("error") or payload.get("errors"):
        raise TheSportsDBProviderError("thesportsdb_semantic_rejection", stop_cycle=True)
    if payload.get("message") and payload.get("event") is None:
        raise TheSportsDBProviderError("thesportsdb_message_without_events", stop_cycle=True)
    events = payload.get("event")
    if events is None:
        return []
    if not isinstance(events, list):
        raise TheSportsDBProviderError("thesportsdb_invalid_events")
    return events


def norm_team(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.casefold().replace("&", "and")
    words = re.findall(r"[a-z0-9]+", value)
    # Only remove unambiguous club-designator tokens from either end.
    while words and words[0] in {"fc", "fk", "sv", "afc"}:
        words.pop(0)
    while words and words[-1] in {"fc", "fk", "sv"}:
        words.pop()
    return " ".join(words)


def verified_score(signal, event):
    """(score, rejection_reason). Fail closed on source ambiguities."""
    if not isinstance(event, dict):
        return None, "invalid_event"
    if (event.get("strSport") or "").casefold() != "soccer":
        return None, "not_soccer"
    if norm_team(event.get("strHomeTeam")) != norm_team(signal["home"]):
        return None, "home_team_mismatch"
    if norm_team(event.get("strAwayTeam")) != norm_team(signal["away"]):
        return None, "away_team_mismatch"
    kickoff = datetime.fromisoformat(signal["kickoff_utc"]).astimezone(UTC)
    timestamp = event.get("strTimestamp")
    if timestamp:
        try:
            moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            return None, "invalid_timestamp"
        if abs((moment.astimezone(UTC) - kickoff).total_seconds()) > 3 * 3600:
            return None, "kickoff_mismatch"
    elif event.get("dateEvent") != kickoff.date().isoformat():
        return None, "event_date_mismatch"
    status = (event.get("strStatus") or "").strip().upper()
    if status != "FT":
        return None, "not_confirmed_ft"
    if (event.get("strPostponed") or "no").casefold() != "no":
        return None, "postponed"
    if event.get("intHomeScoreExtra") is not None or event.get("intAwayScoreExtra") is not None:
        return None, "extra_time_score"
    if BLOCKED_CONTEXT.search(" ".join(str(event.get(k) or "") for k in
            ("strStatus", "strResult", "strDescriptionEN"))):
        return None, "extra_time_or_penalties_unverified"
    try:
        h, a = int(event["intHomeScore"]), int(event["intAwayScore"])
        if min(h, a) < 0:
            raise ValueError("negative score")
    except (KeyError, TypeError, ValueError):
        return None, "missing_ft_score"
    eid = str(event.get("idEvent") or "")
    if not eid.isdigit():
        return None, "missing_event_id"
    return {
        "match_key": signal["match_key"],
        "status": "final",
        "home_goals": h,
        "away_goals": a,
        "source": "https://www.thesportsdb.com/api/v1/json/123/lookupevent.php?id=" + eid,
    }, "verified_ft"


def api_events(signal):
    # Search by both team names and exact match date, not by approximate league.
    kickoff = datetime.fromisoformat(signal["kickoff_utc"]).astimezone(UTC)
    term = signal["home"] + "_vs_" + signal["away"]
    url = API + "?" + urlencode({"e": term, "d": kickoff.date().isoformat()})
    request = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "AsianOdds-H1-Lab/1.0 (open-source results research)",
    })
    try:
        with urlopen(request, timeout=12) as response:
            if response.status != 200:
                raise TheSportsDBProviderError("thesportsdb_http_unexpected")
            payload = json.loads(response.read(750000))
    except HTTPError as exc:
        # HTTP 401/403/429 are access/rate limits, not missing match evidence.
        status = exc.code
        reason = ("thesportsdb_http_" + str(status)
                  if status in (401, 403, 429) else "thesportsdb_http_error")
        raise TheSportsDBProviderError(
            reason, stop_cycle=status in (401, 403, 429)) from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise TheSportsDBProviderError("thesportsdb_invalid_json") from None
    return parse_provider_events(payload)


def choose_result(signal, events):
    candidates = []
    reasons = []
    for ev in events:
        found, reason = verified_score(signal, ev)
        reasons.append(reason)
        if found is not None:
            candidates.append(found)
    if len(candidates) == 1:
        return candidates[0], "verified_ft"
    if len(candidates) > 1:
        return None, "ambiguous_event"
    return None, "no_event" if not events else ",".join(sorted(set(reasons)))


def read_audit():
    if not AUDIT.exists():
        return {}
    obj = json.loads(AUDIT.read_text(encoding="utf-8"))
    return obj if isinstance(obj, dict) else {}


TSDB_ACCESS_DENIALS = frozenset({
    "thesportsdb_http_401", "thesportsdb_http_403", "thesportsdb_http_429",
})
TSDB_ACCESS_COOLDOWN = timedelta(hours=4)


def recent_tsdb_access_denial(audit, now):
    """Only a previously recorded REAL HTTP refusal may defer new calls.

    A skipped call never refreshes a refusal. Ignore malformed/naive/future
    timestamps and other provider failures. Preserve all H1 fixture rules.
    """
    if now.tzinfo is None or not isinstance(audit, dict):
        raise ValueError("Invalid TheSportsDB access evidence")
    latest = None
    reason = None
    now = now.astimezone(UTC)
    for item in audit.values():
        if not isinstance(item, dict):
            continue
        evidence = item.get("thesportsdb_reason")
        # Earlier H1 audits store the HTTP denial inside the combined reason.
        if evidence is None:
            combined = item.get("reason")
            if isinstance(combined, str) and ";thesportsdb:" in combined:
                evidence = combined.rsplit(";thesportsdb:", 1)[1]
        if evidence not in TSDB_ACCESS_DENIALS:
            continue
        raw = item.get("checked_at")
        if not isinstance(raw, str):
            continue
        try:
            attempted = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if attempted.tzinfo is None:
            continue
        attempted = attempted.astimezone(UTC)
        if not timedelta(0) <= now - attempted < TSDB_ACCESS_COOLDOWN:
            continue
        if latest is None or attempted > latest:
            latest, reason = attempted, evidence
    if latest is None:
        return None
    return {
        "reason": reason,
        "observed_at_utc": latest.isoformat(timespec="seconds"),
        "retry_not_before_utc": (latest + TSDB_ACCESS_COOLDOWN).isoformat(timespec="seconds"),
    }


def read_rows():
    if not RESULTS.exists():
        return []
    with RESULTS.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_rows(rows):
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="results-", suffix=".csv", dir=RESULTS.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=HEADERS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, RESULTS)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)



def plan_due_signals(signals, resolved, audit, now, limit=20):
    """Prioritise unqueried eligible fixtures before retries, without extra API calls.

    Preserve the historical 3-hour grace, 30-day horizon, and 4-hour retry
    cooldown.  Oldest kickoff first within each priority group means that
    continuous collector growth cannot starve an older first check.
    """
    if limit < 1 or now.tzinfo is None:
        raise ValueError("Invalid H1 reconciliation planning bounds")
    due = []
    for index, signal in enumerate(signals):
        key = signal["match_key"]
        if key in resolved:
            continue
        kickoff = datetime.fromisoformat(signal["kickoff_utc"]).astimezone(UTC)
        if now < kickoff + timedelta(hours=3) or now > kickoff + timedelta(days=30):
            continue
        previous = audit.get(key, {})
        checked_at = previous.get("checked_at") if isinstance(previous, dict) else None
        checked = None
        if checked_at:
            try:
                checked = datetime.fromisoformat(checked_at)
                if checked.tzinfo is None:
                    checked = None
                elif now < checked.astimezone(UTC) + timedelta(hours=4):
                    continue
            except (ValueError, TypeError):
                checked = None
        due.append((checked is not None, kickoff, index, signal))
    due.sort(key=lambda item: (item[0], item[1], item[2]))
    chosen = [item[3] for item in due[:limit]]
    diagnostics = {
        "eligible": len(due),
        "first_checks_due": sum(not item[0] for item in due),
        "retries_due": sum(item[0] for item in due),
        "deferred_by_limit": max(0, len(due) - limit),
    }
    return chosen, diagnostics


def sync(now=None, search=api_events):
    now = (now or datetime.now(UTC)).astimezone(UTC)
    state = read_state()
    rows = read_rows()
    resolved = set(load_results(RESULTS))
    audit = read_audit()
    scanned = 0
    newly_final = 0
    errors = 0
    updates = 0
    prior_denial = recent_tsdb_access_denial(audit, now)
    tsdb_circuit_reason = prior_denial["reason"] if prior_denial else None
    tsdb_skipped = 0
    bsd_enabled = bool(os.environ.get("BSD_API_KEY", "").strip())
    due_signals, plan = plan_due_signals(state["signals"], resolved, audit, now, limit=20)
    print("H1_RESULTS_PLAN", json.dumps(plan, sort_keys=True))
    for signal in due_signals:
        # With no BSD credential and a blocked TSDB, no HTTP check can occur:
        # leave the audit untouched so this fixture does not gain fake cooldown.
        if tsdb_circuit_reason and not bsd_enabled:
            tsdb_skipped += 1
            continue
        key = signal["match_key"]
        scanned += 1
        bsd_result = None
        bsd_reason = "bsd_not_configured"
        if bsd_enabled:
            from .bsd import BSDProviderError, find_result
            try:
                bsd_result, bsd_reason = find_result(signal)
            except BSDProviderError:
                bsd_reason = "bsd_provider_unavailable"
                errors += 1

        fallback = None
        fallback_reason = "not_checked"
        if tsdb_circuit_reason:
            fallback_reason = "thesportsdb_circuit_open"
            tsdb_skipped += 1
        else:
            try:
                fallback, fallback_reason = choose_result(signal, search(signal))
            except TheSportsDBProviderError as exc:
                fallback_reason = exc.reason
                errors += 1
                if exc.stop_cycle:
                    tsdb_circuit_reason = exc.reason
            except (OSError, ValueError, TimeoutError, json.JSONDecodeError):
                # Never echo untrusted payloads, request URLs or secrets.
                fallback_reason = "thesportsdb_unavailable"
                errors += 1

        if bsd_result is not None and fallback is not None:
            same_score=(bsd_result["home_goals"], bsd_result["away_goals"]) == (
                fallback["home_goals"], fallback["away_goals"])
            if same_score:
                result=bsd_result
                reason="confirmed_bsd_and_thesportsdb"
            else:
                result=None
                reason="score_conflict_requires_manual_review"
        elif bsd_result is not None:
            result=bsd_result
            reason="confirmed_bsd_only"
        elif fallback is not None:
            result=fallback
            reason="confirmed_thesportsdb_only"
        else:
            result=None
            reason="bsd:" + bsd_reason + ";thesportsdb:" + fallback_reason
        audit[key] = {
            "checked_at": now.isoformat(timespec="seconds"),
            "status": "settled" if result else "pending",
            "reason": reason,
            # Keep independent supplier evidence even when BSD alone verifies
            # the final, so a real 429 cannot disappear under 'confirmed_bsd_only'.
            "thesportsdb_reason": fallback_reason,
        }
        updates += 1
        if result is not None:
            rows.append(result)
            resolved.add(key)
            newly_final += 1
    if newly_final:
        write_rows(rows)
    if updates:
        from .core import dump_json
        dump_json(AUDIT, audit)
    save(state)  # update ROI, even if no scores can yet be verified
    print("RESULTS_SYNC checked:", scanned, "new finals:", newly_final,
          "provider errors:", errors, "unresolved:", len(state["signals"])-len(resolved))
    print("H1_PROVIDER_HEALTH", json.dumps({
        "thesportsdb_circuit": tsdb_circuit_reason or "closed",
        "thesportsdb_prior_denial": prior_denial,
        "thesportsdb_skipped_calls": tsdb_skipped,
        "selected": len(due_signals), "processed": scanned,
    }, sort_keys=True))


if __name__ == "__main__":
    sync()
