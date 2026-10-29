"""Reviewed GOAL fixture-ID bridge; never settle a disputed score automatically.

No network calls. A per-match approval is a locator, NOT a certified FT.
Only strong reviewed same-order fixture candidates, confirmed API-Football
identity anchors, and exact provider-event identities can be considered.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import timedelta
from .lab_ft_crosswalk import providers_from_final, event_id
from .lab_identity import core_tokens, CORE
from .lab_identity_review import _qualifiers
from .lab_results import utc
from .lab_goal import _name, _when, verify

SCHEMA = 1
ID_RECHECK_GAP = timedelta(hours=24)
NUMERIC_ID = re.compile(r"[0-9]{3,12}")


def plan_reviewed_goal_id(selected, matches, review, approved, api_approved, now,
                          *, decisions=None):
    """Return at most one match_key -> locked approval, no IO or fuzzy matching."""
    if now.tzinfo is None:
        raise ValueError("UTC required")
    if decisions is None:
        decisions = {}
    decisions.clear()
    if not all(isinstance(x, dict) and x.get("schema_version") == SCHEMA
               for x in (review, approved, api_approved)):
        return {}
    games, pairs, api_pairs = (review.get("games"), approved.get("pairs"),
                              api_approved.get("pairs"))
    if not isinstance(games, list) or not isinstance(pairs, dict) or not isinstance(api_pairs, dict):
        return {}
    lookup = {g.get("match_key"): g for g in games if isinstance(g, dict)}
    if len(lookup) != len(games):
        return {}
    strong = {}
    for g in games:
        for c in g.get("candidates", []):
            if (isinstance(c, dict) and c.get("provider") == "goal"
                    and c.get("match_strength") == "STRONG"):
                strong.setdefault(str(c.get("provider_event_id")), set()).add(g["match_key"])
    claims = Counter(str(row.get("provider_fixture_id")) for row in pairs.values()
                     if isinstance(row, dict) and row.get("status") == "APPROVED_IDENTITY_ONLY")
    confirmed = set()
    for row in matches.values():
        if isinstance(row, dict) and row.get("status") == "FINAL":
            for provider, url in providers_from_final(row).items():
                if provider == "goal":
                    confirmed.add(event_id(provider, url))
    options = []
    for key in sorted(pairs):
        row, game, g, api = pairs[key], matches.get(key), lookup.get(key), api_pairs.get(key)
        def deny(reason):
            decisions[key] = {"status": "DEFERRED", "reason": reason}
        if key not in selected:
            deny("NOT_SELECTED_IN_CURRENT_FT_QUEUE")
            continue
        if (not isinstance(row, dict) or row.get("status") != "APPROVED_IDENTITY_ONLY"
                or row.get("provider") != "goal" or row.get("match_key") != key
                or row.get("score_gate") != "HOLD_FOR_OFFICIAL"):
            deny("GOAL_REVIEW_APPROVAL_INVALID")
            continue
        if (not isinstance(game, dict) or game.get("status") not in ("PENDING", "PROVIDER_ERROR")
                or not isinstance(g, dict) or g.get("possible_duplicates")):
            deny("GOAL_OBSERVATION_NOT_UNIQUE_PENDING")
            continue
        identity = ("home", "away", "kickoff_utc")
        if any(row.get(f) != game.get(f) or g.get(f) != game.get(f) for f in identity):
            deny("GOAL_ORIGINAL_IDENTITY_CHANGED")
            continue
        reviewed_at, ko = utc(row.get("reviewed_at_utc")), utc(game.get("kickoff_utc"))
        if (not isinstance(row.get("reviewed_by"), str) or not row["reviewed_by"].strip()
                or reviewed_at is None or ko is None or reviewed_at < ko or reviewed_at > now):
            deny("GOAL_REVIEW_PROVENANCE_INVALID")
            continue
        # Anchor GOAL identity to the separately human-reviewed API-Football
        # same-match fixture. Neither score nor team mapping becomes global.
        if (not isinstance(api, dict) or api.get("status") != "APPROVED"
                or api.get("provider") != "api_football"
                or any(api.get(f) != game.get(f) for f in identity)
                or api.get("provider_fixture_id") != row.get("api_football_anchor_id")
                or type(api.get("competition_anchor_fixture_id")) is not int):
            deny("GOAL_INDEPENDENT_IDENTITY_ANCHOR_MISSING")
            continue
        eid = str(row.get("provider_fixture_id", ""))
        if (not NUMERIC_ID.fullmatch(eid) or claims[eid] != 1
                or eid in confirmed or strong.get(eid, set()) != {key}):
            deny("GOAL_ID_COLLISION_OR_OTHER_STRONG_CLAIM")
            continue
        provider_ko = utc(row.get("provider_kickoff_utc"))
        if provider_ko is None or abs(provider_ko-ko) > timedelta(minutes=5):
            deny("GOAL_REVIEW_KICKOFF_MISMATCH")
            continue
        if (not isinstance(row.get("provider_competition"), str)
                or not row["provider_competition"].strip()):
            deny("GOAL_REVIEW_COMPETITION_UNCONFIRMED")
            continue
        matches_c = [
            c for c in g.get("candidates", [])
            if isinstance(c, dict) and c.get("provider") == "goal"
            and c.get("match_strength") == "STRONG"
            and c.get("orientation") == "SAME_ORDER"
            and c.get("review_only") is True
            and str(c.get("provider_event_id")) == eid
            and all(c.get(f) == row.get(f) for f in
                    ("provider_home", "provider_away", "provider_competition",
                     "provider_kickoff_utc"))
        ]
        if len(matches_c) != 1:
            deny("GOAL_STRONG_CANDIDATE_NOT_UNIQUELY_LOCKED")
            continue
        if any(_qualifiers(game[side]) != _qualifiers(row["provider_" + side])
               for side in ("home", "away")):
            deny("GOAL_TEAM_CATEGORY_MISMATCH")
            continue
        if not all(core_tokens(row["provider_" + side]) for side in ("home", "away")):
            deny("GOAL_PROVIDER_TEAM_NAMES_INVALID")
            continue
        recent = utc(game.get("goal_id_last_attempt_at"))
        if recent is not None and now - recent < ID_RECHECK_GAP:
            deny("GOAL_ID_24H_COOLDOWN")
            continue
        decisions[key] = {"status": "ELIGIBLE_IDENTITY_ONLY",
                          "provider_fixture_id": eid,
                          "score_gate": "HOLD_FOR_OFFICIAL"}
        options.append((ko, key, dict(row, provider_fixture_id=eid)))
    options.sort()
    return {options[0][1]: options[0][2]} if options else {}


def verify_reviewed_goal(signal, event, approved):
    """Return (None, reason, normalized evidence). Never returns FINAL."""
    if not isinstance(event, dict) or not isinstance(approved, dict):
        return None, "goal_reviewed_invalid_event", None
    eid = str(approved.get("provider_fixture_id", ""))
    if str(event.get("apiId", "")) != eid:
        return None, "goal_reviewed_id_mismatch", None
    ko, expected, actual = (utc(signal.get("kickoff_utc")),
                           utc(approved.get("provider_kickoff_utc")), _when(event))
    if (ko is None or expected is None or actual is None
            or abs(ko-actual) > timedelta(minutes=5)
            or abs(expected-actual) > timedelta(minutes=5)):
        return None, "goal_reviewed_kickoff_mismatch", None
    for side in ("home", "away"):
        provider = _name(event, side + "Team")
        locked = approved.get("provider_" + side)
        if (not isinstance(locked, str) or not isinstance(provider, str)
                or not core_tokens(provider) or core_tokens(provider) != core_tokens(locked)
                or _qualifiers(provider) != _qualifiers(signal.get(side))):
            return None, "goal_reviewed_team_or_category_mismatch", None
    league = event.get("league") or event.get("competition")
    label = league.get("name") if isinstance(league, dict) else league
    if (not isinstance(label, str) or
            core_tokens(label) != core_tokens(approved.get("provider_competition"))):
        return None, "goal_reviewed_competition_mismatch", None
    # Call the existing goal regulation-time validator with provider-verified
    # side labels. A single reviewed locator cannot override FT status/score.
    verified, reason = verify(dict(signal,
        home=_name(event, "homeTeam"), away=_name(event, "awayTeam")), event, CORE)
    if verified is None:
        return None, "goal_reviewed_" + reason, None
    if approved.get("score_gate") != "HOLD_FOR_OFFICIAL":
        return None, "goal_reviewed_score_gate_invalid", None
    observation = {
        "provider_fixture_id": eid,
        "home_goals": verified["home_goals"],
        "away_goals": verified["away_goals"],
        "source": verified["source"],
        "identity_match": "REVIEWED_PAIR",
        "status": "PROVIDER_FT_AWAITING_OFFICIAL_CORROBORATION",
    }
    return None, "goal_reviewed_ft_held_for_official", observation
