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
    with urlopen(request, timeout=12) as response:
        if response.status != 200:
            raise OSError("Provider returned HTTP " + str(response.status))
        payload = json.loads(response.read(750000))
    if not isinstance(payload, dict) or not isinstance(payload.get("event"), (list, type(None))):
        raise ValueError("Unexpected provider response")
    return payload.get("event") or []


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
    for signal in state["signals"]:
        key = signal["match_key"]
        if key in resolved:
            continue
        kickoff = datetime.fromisoformat(signal["kickoff_utc"]).astimezone(UTC)
        # Strictly after the match; stop retrying ancient fixtures automatically.
        if now < kickoff + timedelta(hours=3) or now > kickoff + timedelta(days=30):
            continue
        previous = audit.get(key, {})
        if previous.get("checked_at"):
            try:
                checked = datetime.fromisoformat(previous["checked_at"])
                if now < checked + timedelta(hours=4):
                    continue
            except (ValueError, TypeError):
                pass
        if scanned >= 20:  # bounded workload and free API usage
            break
        scanned += 1
        try:
            result, reason = choose_result(signal, search(signal))
        except (OSError, ValueError, TimeoutError, json.JSONDecodeError) as exc:
            # Never echo untrusted payloads, request URLs or secrets.
            reason = "provider_unavailable"
            result = None
            errors += 1
        audit[key] = {
            "checked_at": now.isoformat(timespec="seconds"),
            "status": "settled" if result else "pending",
            "reason": reason,
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


if __name__ == "__main__":
    sync()
