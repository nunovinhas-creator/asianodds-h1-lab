"""Human-approved API-Football fixture crosswalk: NEVER fuzzy auto-settlement.

An approval is valid only if it repeats a real candidate from the persisted
identity review and explicitly locks the observed fixture and source team IDs.
This module only plans and verifies; it never creates approvals.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from .lab_results import utc
from .lab_ft_crosswalk import providers_from_final, event_id as confirmed_id

MAX_BATCH = 20
SCHEMA = 1


def _positive(value):
    return type(value) is int and value > 0


def plan_reviewed_ids(selected, matches, review, approved, now):
    """Return safe match_key -> approved tuple, or empty when not human approved.

    A candidate with a similar name is NEVER sufficient for settlement.
    """
    if not isinstance(approved, dict) or approved.get("schema_version") != SCHEMA:
        raise ValueError("Invalid approved FT pair registry")
    pairs = approved.get("pairs")
    if not isinstance(pairs, dict):
        raise ValueError("Invalid approved pair table")
    if not isinstance(review, dict) or review.get("schema_version") != 1:
        return {}
    reviewed_games = review.get("games")
    if not isinstance(reviewed_games, list):
        return {}
    indexed = {g["match_key"]: g for g in reviewed_games
               if isinstance(g, dict) and isinstance(g.get("match_key"), str)}
    if len(indexed) != len(reviewed_games):
        return {}  # ambiguous review queue
    selected = set(selected)
    collision = Counter()
    for row in pairs.values():
        if isinstance(row, dict) and row.get("status") == "APPROVED":
            fixture_id = row.get("provider_fixture_id")
            if _positive(fixture_id):
                collision[fixture_id] += 1
    final_ids = set()
    for row in matches.values():
        if isinstance(row, dict) and row.get("status") == "FINAL":
            for provider, url in providers_from_final(row).items():
                if provider == "api_football":
                    final_ids.add(confirmed_id(provider, url))
    candidates = Counter()
    for g in reviewed_games:
        for c in g.get("candidates", []):
            if (isinstance(c, dict) and c.get("provider") == "api_football"
                    and _positive(c.get("provider_home_team_id"))
                    and _positive(c.get("provider_away_team_id"))):
                candidates[str(c.get("provider_event_id"))] += 1
    eligible = {}
    for key in sorted(selected & set(pairs)):
        row = pairs[key]
        game = matches.get(key)
        reviewed = indexed.get(key)
        if (not isinstance(row, dict) or row.get("status") != "APPROVED"
                or not isinstance(game, dict)
                or game.get("status") not in ("PENDING", "PROVIDER_ERROR")
                or not isinstance(reviewed, dict)
                or reviewed.get("possible_duplicates")):
            continue
        if any(row.get(field) != game.get(field) or
               reviewed.get(field) != game.get(field)
               for field in ("home", "away", "kickoff_utc")):
            continue
        reviewed_by = row.get("reviewed_by")
        reviewed_at = utc(row.get("reviewed_at_utc"))
        if (not isinstance(reviewed_by, str) or not reviewed_by.strip()
                or reviewed_at is None or reviewed_at > now
                or reviewed_at < utc(game["kickoff_utc"])):
            continue
        ids = [row.get(k) for k in ("provider_fixture_id",
                                   "provider_home_team_id", "provider_away_team_id",
                                   "provider_competition_id")]
        if not all(_positive(x) for x in ids) or ids[1] == ids[2]:
            continue
        if collision[ids[0]] != 1 or str(ids[0]) in final_ids:
            continue
        provider_ko = utc(row.get("provider_kickoff_utc"))
        observed_ko = utc(game["kickoff_utc"])
        if (provider_ko is None or observed_ko is None or
                abs(provider_ko - observed_ko) > timedelta(minutes=90)):
            continue
        last_id_check = utc(game.get("api_football_reviewed_id_last_attempt_at"))
        if last_id_check is not None and now - last_id_check < timedelta(hours=24):
            continue
        aligned = [c for c in reviewed.get("candidates", [])
                   if isinstance(c, dict) and c.get("provider") == "api_football"
                   and c.get("orientation") == "SAME_ORDER"
                   and c.get("review_only") is True
                   and str(c.get("provider_event_id")) == str(ids[0])
                   and c.get("provider_home_team_id") == ids[1]
                   and c.get("provider_away_team_id") == ids[2]
                   and c.get("provider_competition_id") == ids[3]
                   and utc(c.get("provider_kickoff_utc")) == provider_ko]
        if len(aligned) != 1 or candidates[str(ids[0])] != 1:
            continue
        eligible[key] = dict(row)
        if len(eligible) == MAX_BATCH:
            break
    return eligible


def validate_reviewed_result(signal, approved, ev):
    """Strict ID/side/competition and official 90-min validator.

    An ID is a locator. A human review is not proof of goals, nor does it
    license any automatic matching of another fixture or team.
    """
    from .lab_api_football import _name, _time, _score
    if not isinstance(ev, dict):
        return None, "api_football_reviewed_invalid_event"
    fixture = ev.get("fixture")
    teams = ev.get("teams")
    league = ev.get("league")
    if not all(isinstance(v, dict) for v in (fixture, teams, league)):
        return None, "api_football_reviewed_invalid_identity"
    h, a = teams.get("home"), teams.get("away")
    if not isinstance(h, dict) or not isinstance(a, dict):
        return None, "api_football_reviewed_invalid_teams"
    if (fixture.get("id") != approved.get("provider_fixture_id")
            or h.get("id") != approved.get("provider_home_team_id")
            or a.get("id") != approved.get("provider_away_team_id")
            or league.get("id") != approved.get("provider_competition_id")):
        return None, "api_football_reviewed_id_mismatch"
    ko = utc(signal.get("kickoff_utc"))
    approved_ko = utc(approved.get("provider_kickoff_utc"))
    got_ko = _time(ev)
    if (ko is None or approved_ko is None or got_ko is None
            or abs(ko - got_ko) > timedelta(minutes=90)
            or abs(approved_ko - got_ko) > timedelta(minutes=5)):
        return None, "api_football_reviewed_kickoff_mismatch"
    home, away = _name(ev, "home"), _name(ev, "away")
    if not isinstance(home, str) or not home.strip() or not isinstance(away, str) or not away.strip():
        return None, "api_football_reviewed_missing_names"
    # Reuse the original strict score validator using the exact provider
    # names ONLY AFTER the human-reviewed team IDs have been validated.
    result, reason = _score(dict(signal, home=home, away=away), ev, "REVIEWED_PAIR")
    if result is not None:
        result["identity_match"] = "REVIEWED_PAIR"
        return result, "verified_api_football_ft_reviewed_pair"
    return None, reason
