"""Read-only, persistent candidate queue from ALREADY FETCHED FT provider date caches.

The queue is a diagnostic projection, not an alias registry, approved fixture
crosswalk, 90-minute score, or instruction to settle a result. No HTTP calls.
Never persist provider raw responses, keys, scores, or forecast data here.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import urlparse

from .bsd import ROOT as BSD_ROOT, event_kickoff, event_name
from .lab_api_football import _name as api_name, _time as api_time
from .lab_goal import _name as goal_name, _when as goal_time
from .lab_openfoot import names as openfoot_names, utc as openfoot_time
from .lab_sportscore import _dt as sportscore_time, _source_url
from .lab_identity import core_tokens
from .lab_results import DELAY, utc

SCHEMA = 1
STATUS = "FT_IDENTITY_REVIEW_ONLY_NO_AUTOMATIC_MATCH"
MAX_GAMES = 500
MAX_PER_PROVIDER = 3
MAX_CANDIDATES = 9
WINDOW_SECONDS = 90 * 60
AGE_RE = re.compile(r"^u(?:1[5-9]|2[0-3])$")
ALLOWED = frozenset({"api_football", "goal", "openfoot", "bsd", "sportscore"})


def _text(value, size=120):
    return value.strip()[:size] if isinstance(value, str) else ""


def _qualifiers(name):
    return frozenset(t for t in core_tokens(name)
                     if AGE_RE.fullmatch(t) or t in ("reserves", "women", "youth"))


def _similarity(left, right):
    if not left or not right or _qualifiers(left) != _qualifiers(right):
        return 0.0
    a, b = core_tokens(left), core_tokens(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, " ".join(sorted(a)), " ".join(sorted(b))).ratio()


def _extract(provider, event):
    """Only fields needed for human triage; never inspect or output goals."""
    if not isinstance(event, dict):
        return None
    name = ""
    reference = ""
    source = ""
    when = None
    team_ids = None
    competition_id = None
    if provider == "api_football":
        home, away = api_name(event, "home"), api_name(event, "away")
        when = api_time(event)
        fixture = event.get("fixture") or {}
        league = event.get("league") or {}
        reference = str(fixture.get("id")) if type(fixture.get("id")) is int and fixture["id"] > 0 else ""
        name = _text(league.get("name")) if isinstance(league, dict) else ""
        competition_id = league.get("id") if isinstance(league, dict) else None
        teams = event.get("teams") or {}
        if isinstance(teams, dict):
            h, a = teams.get("home"), teams.get("away")
            if isinstance(h, dict) and isinstance(a, dict):
                h_id, a_id = h.get("id"), a.get("id")
                if (type(h_id) is int and h_id > 0 and type(a_id) is int
                        and a_id > 0 and h_id != a_id):
                    team_ids = (h_id, a_id)
        if reference:
            source = "https://v3.football.api-sports.io/fixtures?id=" + reference
    elif provider == "goal":
        home, away = goal_name(event, "homeTeam"), goal_name(event, "awayTeam")
        when = goal_time(event)
        value = event.get("apiId")
        reference = value if isinstance(value, str) and re.fullmatch(r"[0-9]{3,12}", value) else ""
        league = event.get("league") or event.get("competition") or {}
        name = _text(league.get("name")) if isinstance(league, dict) else _text(league)
        if reference:
            source = "https://api.goal-api.com/v1/fixtures/" + reference
    elif provider == "openfoot":
        home, away = openfoot_names(event)
        when = openfoot_time(event.get("kickoffAt"))
        value = event.get("id")
        reference = value if isinstance(value, str) and re.fullmatch(r"match_[a-zA-Z0-9_-]{3,160}", value) else ""
        comp = event.get("competition") or {}
        name = _text(comp.get("name")) if isinstance(comp, dict) else ""
        if not name:
            name = _text(event.get("competitionId"))
    elif provider == "bsd":
        home, away = event_name(event, "home_team"), event_name(event, "away_team")
        when = event_kickoff(event)
        eid = event.get("id")
        reference = str(eid) if type(eid) is int and eid > 0 else ""
        competition = event.get("competition") or {}
        name = _text(competition.get("name")) if isinstance(competition, dict) else _text(competition)
        if reference:
            source = BSD_ROOT + reference + "/"
    elif provider == "sportscore":
        home, away = event.get("home"), event.get("away")
        when = sportscore_time(event.get("time"))
        name = _text(event.get("competition"))
        source = _source_url(event.get("url")) or ""
        reference = source.rsplit("/", 1)[-1] if source else ""
    else:
        return None
    if not all((isinstance(home, str), isinstance(away, str), when is not None)):
        return None
    if not home.strip() or not away.strip() or not when.tzinfo:
        return None
    return (_text(home), _text(away), when.astimezone(timezone.utc),
            _text(name), _text(reference, 180), source, team_ids,
            competition_id if type(competition_id) is int and competition_id > 0 else None)


def _cached(provider, day, caches):
    cache = caches.get(provider)
    if not isinstance(cache, dict):
        return None
    if provider == "sportscore":
        # Team-scoped caches may be incomplete; use both, never claim completeness.
        out = []
        for key, rows in cache.items():
            if isinstance(key, tuple) and len(key) == 2 and key[0] == day and isinstance(rows, list):
                out.extend(rows)
        return out if out else None
    rows = cache.get(day)
    if provider == "bsd":
        # An incomplete paginated BSD response cannot imply any identity claim.
        if not isinstance(rows, (tuple, list)) or len(rows) != 2 or rows[1] != "complete":
            return None
        rows = rows[0]
    return rows if isinstance(rows, list) else None


def _candidates(signal, provider, rows, now):
    ko = utc(signal.get("kickoff_utc"))
    if ko is None:
        return []
    found = []
    for event in rows:
        item = _extract(provider, event)
        if item is None:
            continue
        home, away, when, comp, identifier, source, team_ids, competition_id = item
        gap = abs((ko - when).total_seconds())
        if gap > WINDOW_SECONDS:
            continue
        straight = (_similarity(signal["home"], home),
                    _similarity(signal["away"], away))
        reverse = (_similarity(signal["home"], away),
                   _similarity(signal["away"], home))
        orient = "REVERSED_TO_REVIEW" if min(reverse) >= 0.73 and sum(reverse) > sum(straight) else "SAME_ORDER"
        scores = reverse if orient == "REVERSED_TO_REVIEW" else straight
        strong = min(scores) >= 0.70 and sum(scores) >= 1.53
        # Broaden DISCOVERY for human review ONLY. This is not an identity
        # match or permission to settle FT. Keep qualifiers and kickoff hard.
        weak = ((max(scores) >= 0.96 and min(scores) >= 0.33)
                or (min(scores) >= 0.48 and sum(scores) >= 1.02))
        if not (strong or weak):
            continue
        found.append({
            "provider": provider, "provider_event_id": identifier,
            "provider_home": home, "provider_away": away,
            "provider_kickoff_utc": when.isoformat(timespec="seconds"),
            "provider_competition": comp,
            "reference_url": source,
            **({"provider_home_team_id": team_ids[0],
                "provider_away_team_id": team_ids[1],
                "provider_competition_id": competition_id}
               if provider == "api_football" and team_ids and competition_id
               else {}),
            "orientation": orient,
            "name_similarity_diagnostic": round(sum(scores) / 2, 3),
            "match_strength": "STRONG" if strong else "WEAK_REVIEW_ONLY",
            "kickoff_delta_minutes": round(gap / 60, 1),
            "first_seen_at": now.isoformat(timespec="seconds"),
            "last_seen_at": now.isoformat(timespec="seconds"),
            "observed_this_run": True,
            "review_only": True,
        })
    # Unique fixture candidates. Repeated provider rows must not consume the budget.
    best = {}
    for c in found:
        key = (c["provider"], c["provider_event_id"], c["provider_home"],
               c["provider_away"], c["provider_kickoff_utc"])
        old = best.get(key)
        if old is None or c["name_similarity_diagnostic"] > old["name_similarity_diagnostic"]:
            best[key] = c
    return sorted(best.values(), key=lambda x: (
        x["orientation"] != "REVERSED_TO_REVIEW",
        -x["name_similarity_diagnostic"], x["kickoff_delta_minutes"],
        x["provider_event_id"]))[:MAX_PER_PROVIDER]


def _candidate_key(c):
    return (c.get("provider"), c.get("provider_event_id"),
            c.get("provider_home"), c.get("provider_away"),
            c.get("provider_kickoff_utc"))


def _duplicates(key, row, matches):
    ko = utc(row.get("kickoff_utc"))
    if ko is None:
        return []
    out = []
    for other_key, other in matches.items():
        if other_key == key or not isinstance(other, dict):
            continue
        stamp = utc(other.get("kickoff_utc"))
        if stamp is None or abs((stamp - ko).total_seconds()) > 5 * 60:
            continue
        home = _similarity(row.get("home"), other.get("home"))
        away = _similarity(row.get("away"), other.get("away"))
        # A side shared at the same kickoff is a review flag, NOT proof of a duplicate.
        if max(home, away) < 0.99:
            continue
        if not other.get("home") or not other.get("away"):
            continue
        out.append({"match_key": other_key,
                    "home": _text(other["home"]), "away": _text(other["away"]),
                    "status": _text(other.get("status")),
                    "reason": "SHARED_CLUB_SAME_KICKOFF_REVIEW_ONLY"})
    return sorted(out, key=lambda x: x["match_key"])[:4]


def build_queue(ledger, now, caches, previous=None):
    """Pure projection. Date caches supplied from active adapters; ZERO HTTP calls."""
    if now.tzinfo is None:
        raise ValueError("Aware UTC required")
    now = now.astimezone(timezone.utc)
    matches = ledger.get("matches")
    if not isinstance(matches, dict) or not isinstance(caches, dict):
        raise ValueError("Invalid FT sources")
    old = {}
    if isinstance(previous, dict) and previous.get("schema_version") == SCHEMA:
        old = {x["match_key"]: x for x in previous.get("games", [])
               if isinstance(x, dict) and isinstance(x.get("match_key"), str)}
    results = []
    coverage = Counter()
    for key, row in sorted(matches.items()):
        if not isinstance(row, dict) or row.get("status") == "FINAL":
            continue
        kickoff = utc(row.get("kickoff_utc"))
        if kickoff is None or now < kickoff + DELAY:
            continue
        if not row.get("home") or not row.get("away"):
            continue
        game = {"match_key": key, "home": row["home"], "away": row["away"],
                "kickoff_utc": row["kickoff_utc"],
                "ft_status": row.get("status"),
                "last_checked_at": row.get("checked_at"),
                "attempts": row.get("attempts", 0),
                "last_attempt_reasons": dict(sorted((row.get("provider_reasons") or {}).items()))}
        day = kickoff.date().isoformat()
        available = []
        fresh = []
        for provider in sorted(ALLOWED):
            rows = _cached(provider, day, caches)
            if rows is None:
                continue
            available.append(provider)
            fresh.extend(_candidates(game, provider, rows, now))
        before = old.get(key) or {}
        same_identity = all(before.get(field) == game[field]
                            for field in ("home", "away", "kickoff_utc"))
        prior = before.get("candidates", []) if same_identity else []
        combined = {}
        for c in prior:
            if isinstance(c, dict) and c.get("provider") in ALLOWED:
                carry = dict(c)
                carry["observed_this_run"] = False
                combined[_candidate_key(carry)] = carry
        for c in fresh:
            ident = _candidate_key(c)
            if ident in combined:
                c["first_seen_at"] = combined[ident].get("first_seen_at", c["first_seen_at"])
            combined[ident] = c
        candidates = sorted(combined.values(), key=lambda x: (
            not x.get("observed_this_run", False),
            x["orientation"] != "REVERSED_TO_REVIEW",
            -x["name_similarity_diagnostic"],
            x["provider"], x["provider_event_id"]))[:MAX_CANDIDATES]
        dupes = _duplicates(key, row, matches)
        reasons = set(game["last_attempt_reasons"].values())
        flags = []
        if dupes:
            flags.append("POSSIBLE_DUPLICATE_OBSERVATION")
        if any(c["orientation"] == "REVERSED_TO_REVIEW" for c in candidates):
            flags.append("HOME_AWAY_ORIENTATION_REVIEW")
        if any("regulation" in r for r in reasons):
            flags.append("REGULATION_90M_UNVERIFIED")
        if row.get("status") in ("SCORE_CONFLICT", "SOURCE_ORDER_CONFLICT", "IDENTITY_CONFLICT"):
            flags.append("PROVIDER_OR_IDENTITY_CONFLICT")
        if candidates:
            flags.append("PROVIDER_IDENTITY_CANDIDATES_TO_REVIEW")
        if any(c.get("match_strength") == "WEAK_REVIEW_ONLY" for c in candidates):
            flags.append("WEAK_IDENTITY_CANDIDATE")
        if not flags:
            flags.append("NO_MATCH_FOUND_IN_AVAILABLE_CACHES")
        game.update({
            "review_flags": flags, "cached_provider_days": available,
            "possible_duplicates": dupes, "candidates": candidates,
            "review_state": "HUMAN_REVIEW_REQUIRED_NO_SCORE",
        })
        for flag in flags:
            coverage[flag] += 1
        results.append(game)
    results.sort(key=lambda x: (
        not (x["possible_duplicates"] or x["candidates"]),
        x["kickoff_utc"], x["match_key"]))
    return {
        "schema_version": SCHEMA, "status": STATUS,
        "generated_at": now.isoformat(timespec="seconds"),
        "scope": "past kickoff + 3h without confirmed FT; all observed LAB matches",
        "total_eligible": len(results), "displayed": min(len(results), MAX_GAMES),
        "omitted": max(0, len(results) - MAX_GAMES),
        "counts_by_review_flag": dict(sorted(coverage.items())),
        "games": results[:MAX_GAMES],
        "limitations": [
            "Only previously fetched provider day caches are inspected; zero new HTTP requests.",
            "Provider candidate names are fuzzy DIAGNOSTICS for human review, never authorized aliases.",
            "A candidate, source URL or shared team does NOT prove one fixture or its 90-minute result.",
            "A carried candidate may be stale and is marked observed_this_run=false.",
            "No scores, provider raw payloads, API credentials, H1 bets or forecast changes are stored.",
            "Finite provider catalogue, incomplete indexes and 4h retry can leave candidate lists empty.",
        ],
    }
