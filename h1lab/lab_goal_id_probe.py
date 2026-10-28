"""One quota-neutral GOAL fixture-ID probe, selected from existing review evidence.

Candidates are locators only. The normal strict GOAL identity, kickoff,
orientation and regulation-time validators still decide FT acceptance.
"""
from __future__ import annotations
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from .lab_ft_crosswalk import event_id as verified_event_id, providers_from_final
from .lab_identity import pair_level
from .lab_results import utc, GOAL_ID_RECHECK_EVIDENCE

GOOD_REASONS = GOAL_ID_RECHECK_EVIDENCE
ID_RECHECK_GAP = timedelta(hours=24)
IDENTIFIER = re.compile(r"[0-9]{3,12}")


def plan_goal_id(selected_keys, matches, review, now):
    """Return at most one (match_key -> GOAL event ID). No API calls."""
    if now.tzinfo is None:
        raise ValueError("UTC required")
    if not isinstance(review, dict) or review.get("schema_version") != 1:
        return {}
    games = review.get("games")
    if not isinstance(games, list):
        return {}
    # A candidate provider ID cannot be shared by two observed fixtures.
    usage = Counter()
    for g in games:
        if isinstance(g, dict):
            usage.update(set(c.get("provider_event_id") for c in g.get("candidates", [])
                             if isinstance(c, dict) and c.get("provider") == "goal"
                             and IDENTIFIER.fullmatch(str(c.get("provider_event_id", "")))))
    # Do not consume a paid/free-tier slot on a GOAL event already attached
    # to a different, independently verified FINAL match.
    confirmed_goal_ids = set()
    for key, row in matches.items():
        if isinstance(row, dict) and row.get("status") == "FINAL":
            for provider, url in providers_from_final(row).items():
                if provider == "goal":
                    confirmed_goal_ids.add(verified_event_id(provider, url))
    allowed = set(selected_keys)
    choices = []
    for g in games:
        if not isinstance(g, dict) or g.get("match_key") not in allowed:
            continue
        key = g["match_key"]
        current = matches.get(key)
        if not isinstance(current, dict) or current.get("status") not in ("PENDING", "PROVIDER_ERROR"):
            continue
        if any(g.get(f) != current.get(f) for f in ("home", "away", "kickoff_utc")):
            continue
        if g.get("possible_duplicates"):
            continue
        # Last-attempt reason can be a quota/rotation deferral, which must
        # never erase the last actual GOAL fixture evidence.
        saved = current.get("goal_ft_last_evidence") or {}
        reason = (saved.get("reason") if isinstance(saved, dict) else None)
        if reason not in GOOD_REASONS:
            reason = (current.get("provider_reasons") or {}).get("goal")
        if reason not in GOOD_REASONS:
            continue
        last_id_request = utc(current.get("goal_id_last_attempt_at"))
        if last_id_request is not None and now - last_id_request < ID_RECHECK_GAP:
            continue
        cand = [c for c in g.get("candidates", [])
                if isinstance(c, dict) and c.get("provider") == "goal"]
        if len(cand) != 1:
            continue
        c = cand[0]
        event_id = str(c.get("provider_event_id", ""))
        if (not IDENTIFIER.fullmatch(event_id) or usage[event_id] != 1
                or event_id in confirmed_goal_ids):
            continue
        if c.get("orientation") != "SAME_ORDER" or c.get("review_only") is not True:
            continue
        ko, provider_ko = utc(current.get("kickoff_utc")), utc(c.get("provider_kickoff_utc"))
        if ko is None or provider_ko is None or abs((provider_ko-ko).total_seconds()) > 300:
            continue
        if pair_level(current["home"], current["away"], c.get("provider_home"), c.get("provider_away")) is None:
            continue
        last = utc(current.get("checked_at"))
        if last is None or last > now or (now - last).total_seconds() < 4 * 3600:
            continue
        choices.append((last, ko, key, event_id))
    choices.sort()
    return {choices[0][2]: choices[0][3]} if choices else {}
