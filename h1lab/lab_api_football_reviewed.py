"""Human-approved API-Football fixture crosswalk: NEVER fuzzy auto-settlement.

An approval is valid only if it repeats a real candidate from the persisted
identity review and explicitly locks the observed fixture and source team IDs.
This module only plans and verifies; it never creates approvals.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from urllib.parse import urlparse
from .lab_results import utc
from .lab_ft_day_identity import check_day_identity, fixture_index
from .lab_identity_review import _qualifiers
from .lab_ft_crosswalk import providers_from_final, event_id as confirmed_id

MAX_BATCH = 20
SCHEMA = 1


def _positive(value):
    return type(value) is int and value > 0


def plan_reviewed_ids(selected, matches, review, approved, now, *,
                      day_index=None, confirmed_registry=None):
    """Return safe match_key -> approved tuple, or empty when not human approved.

    A candidate with a similar name is NEVER sufficient for settlement.
    """
    if not isinstance(approved, dict) or approved.get("schema_version") != SCHEMA:
        raise ValueError("Invalid approved FT pair registry")
    pairs = approved.get("pairs")
    if not isinstance(pairs, dict):
        raise ValueError("Invalid approved pair table")
    if not isinstance(day_index, dict) or day_index.get("schema_version") != 1:
        return {}  # complete day identity proof is mandatory
    if not isinstance(confirmed_registry, dict) or confirmed_registry.get("schema_version") != 1:
        return {}
    registry = confirmed_registry.get("entries")
    if not isinstance(registry, dict):
        return {}
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
        linked = registry.get(f"api_football:{ids[0]}")
        if (collision[ids[0]] != 1 or str(ids[0]) in final_ids
                or (isinstance(linked, dict) and
                    linked.get("match_key") != key)):
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
        # The approved event and every other game in the 90-minute window
        # must come from an actually fetched, COMPLETE provider-day index.
        if check_day_identity(day_index, row) is not None:
            continue
        day_rows = fixture_index(day_index, provider_ko.date().isoformat())
        source = next((x for x in day_rows if x["fixture_id"] == ids[0]), None)
        if source is None:
            continue
        # A provider team labelled senior, U21 or women's is not a reserves
        # team. Ambiguous "JRS" is not silently rewritten as reserves.
        if (_qualifiers(game["home"]) != _qualifiers(source["home"])
                or _qualifiers(game["away"]) != _qualifiers(source["away"])):
            continue
        # Competition anchor: at least one independently settled sister
        # fixture, in the SAME fully indexed provider competition.
        anchor_id = row.get("competition_anchor_fixture_id")
        anchor = (registry.get(f"api_football:{anchor_id}") if
                  _positive(anchor_id) else None)
        if (not isinstance(anchor, dict) or
                anchor.get("status") != "CONFIRMED_FT_SOURCE_ID" or
                anchor.get("match_key") == key):
            continue
        anchored = any(
            f["fixture_id"] == anchor_id and
            f["competition_id"] == ids[3]
            for indexed_day in day_index.get("days", {}).values()
            if isinstance(indexed_day, dict) and
            indexed_day.get("status") == "COMPLETE"
            for f in indexed_day.get("fixtures", [])
        )
        if not anchored:
            continue
        # Express–Kataka requires an independently confirmed Kataka club ID
        # or an explicitly reviewed public 90-minute score source. This is
        # never granted by the similarity of "Express" and "Red Eagles".
        if key == "2026-10-27,33791,86126":
            opponent_id = row.get("opponent_anchor_fixture_id")
            opponent = (registry.get(f"api_football:{opponent_id}") if
                        _positive(opponent_id) else None)
            anchored_opponent = (isinstance(opponent, dict) and
                opponent.get("status") == "CONFIRMED_FT_SOURCE_ID" and
                opponent.get("match_key") != key and any(
                    f["fixture_id"] == opponent_id and ids[2] in
                    (f["home_team_id"], f["away_team_id"])
                    for indexed_day in day_index.get("days", {}).values()
                    if isinstance(indexed_day, dict) and
                    indexed_day.get("status") == "COMPLETE"
                    for f in indexed_day.get("fixtures", [])))
            public = row.get("independent_public_ft")
            if not anchored_opponent and not valid_public_corroboration(public):
                continue
        eligible[key] = dict(row)
        if len(eligible) == MAX_BATCH:
            break
    return eligible


def valid_public_corroboration(public):
    """Manually reviewed independent source, never a second API-Football URL."""
    if not isinstance(public, dict):
        return False
    url = public.get("url")
    if not isinstance(url, str) or len(url) > 512:
        return False
    uri = urlparse(url)
    if (uri.scheme != "https" or not uri.netloc or uri.username or uri.password
            or uri.hostname in ("v3.football.api-sports.io", "api-football.com")
            or uri.hostname in ("localhost", "127.0.0.1")):
        return False
    return all(type(public.get(k)) is int and 0 <= public[k] <= 99
               for k in ("home_goals", "away_goals"))


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
        # An independent reviewed public result must match the API's actual
        # regulation-time score when used instead of a confirmed Kataka ID.
        public = approved.get("independent_public_ft")
        if public is not None:
            if (not valid_public_corroboration(public) or
                    (result["home_goals"], result["away_goals"]) !=
                    (public["home_goals"], public["away_goals"])):
                return None, "api_football_reviewed_public_score_disagrees"
        result["identity_match"] = "REVIEWED_PAIR"
        return result, "verified_api_football_ft_reviewed_pair"
    return None, reason
