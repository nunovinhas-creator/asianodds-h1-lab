"""One bounded old-fixture ID turn; locators never authorize certification."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from .lab_results import utc, retry_wait, DELAY, RETRY, HORIZON
from .lab_identity import EXACT, pair_level
from .lab_ft_crosswalk import providers_from_final, event_id


def due(row, now):
    ko = utc(row.get('kickoff_utc'))
    last, visit = utc(row.get('evidence_checked_at')), utc(row.get('queue_visited_at'))
    return (row.get('status') in ('PENDING', 'PROVIDER_ERROR') and ko is not None
            and ko + max(DELAY, timedelta(hours=24)) <= now <= ko + HORIZON
            and not (last and now < last + retry_wait(row))
            and not (visit and now < visit + RETRY))


def plan_exact_goal_ids(matches, review, now, *, reserved_keys=()):
    """Known EXACT locators with no prior effective FT check may get one turn.

    No CORE expansion. Ambiguous/colliding/reversed evidence is not bypassed.
    The normal current GOAL regulation FT verifier still decides the result.
    """
    games = review.get('games', []) if isinstance(review, dict) else []
    claims = Counter()
    for g in games:
        claims.update(set(str(c.get('provider_event_id')) for c in g.get('candidates', [])
                          if c.get('provider') == 'goal'))
    finals = {event_id('goal', providers_from_final(r).get('goal'))
              for r in matches.values() if r.get('status') == 'FINAL'}
    out = {}
    for g in games:
        key = g.get('match_key'); row = matches.get(key, {})
        if (key in reserved_keys or not due(row, now) or g.get('possible_duplicates')
                or any(g.get(f) != row.get(f) for f in ('home', 'away', 'kickoff_utc'))):
            continue
        reasons = [row.get('provider_reasons', {}).get('goal', ''),
                   row.get('last_provider_visit', {}).get('reasons', {}).get('goal', '')]
        if any(any(token in reason for token in ('collision', 'ambiguous', 'reversed', 'conflict'))
               for reason in reasons):
            continue
        last = utc(row.get('goal_id_last_attempt_at'))
        if last and now < last + timedelta(hours=24):
            continue
        cs = [c for c in g.get('candidates', []) if c.get('provider') == 'goal']
        if len(cs) != 1:
            continue
        c = cs[0]; ident = str(c.get('provider_event_id', ''))
        ko, seen = utc(c.get('provider_kickoff_utc')), utc(c.get('last_seen_at'))
        if (not ident.isascii() or not ident.isdigit() or not 3 <= len(ident) <= 12
                or claims[ident] != 1 or ident in finals
                or c.get('match_strength') != 'STRONG' or c.get('orientation') != 'SAME_ORDER'
                or c.get('review_only') is not True
                or c.get('reference_url') != 'https://api.goal-api.com/v1/fixtures/' + ident
                or not isinstance(c.get('provider_competition'), str) or not c['provider_competition'].strip()
                or ko is None or abs(ko - utc(row['kickoff_utc'])) > timedelta(minutes=5)
                or seen is None or not timedelta(0) <= now - seen <= timedelta(days=30)
                or pair_level(row['home'], row['away'], c.get('provider_home'), c.get('provider_away')) != EXACT):
            continue
        # A known observed team cannot simultaneously belong to another game.
        if any(other != key and utc(r.get('kickoff_utc')) is not None
               and abs(utc(r['kickoff_utc']) - ko) <= timedelta(minutes=90)
               and (pair_level(row['home'], row['away'], r.get('home'), r.get('away'))
                    or pair_level(row['home'], row['away'], r.get('away'), r.get('home')))
               for other, r in matches.items()):
            continue
        out[key] = {'provider_fixture_id': ident, 'home': row['home'], 'away': row['away'],
                    'kickoff_utc': row['kickoff_utc'],
                    **{f: c[f] for f in ('provider_home', 'provider_away',
                                        'provider_kickoff_utc', 'provider_competition')}}
    return out


def exact_goal_response_ok(signal, event, target):
    from .lab_goal import _name, _when
    league = event.get('league') or event.get('competition') or {}
    comp = league.get('name') if isinstance(league, dict) else league
    return (all(signal.get(f) == target.get(f) for f in ('home', 'away', 'kickoff_utc'))
            and str(event.get('apiId')) == target['provider_fixture_id']
            and _name(event, 'homeTeam') == target['provider_home']
            and _name(event, 'awayTeam') == target['provider_away']
            and _when(event) == utc(target['provider_kickoff_utc'])
            and comp == target['provider_competition']
            and pair_level(signal['home'], signal['away'], _name(event, 'homeTeam'),
                           _name(event, 'awayTeam')) == EXACT)


def recovery_turn(api_targets, goal_targets, matches):
    """Least recently attempted locator, then oldest kickoff; at most one slot."""
    choices = []
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    for provider, targets in (('api_football', api_targets), ('goal', goal_targets)):
        for key in targets:
            row = matches[key]
            last = (row.get('api_football_index_id_last_evidence', {}).get('checked_at_utc')
                    if provider == 'api_football' else row.get('goal_id_last_attempt_at'))
            choices.append((utc(last) or minimum, utc(row['kickoff_utc']), key))
    return {min(choices)[2]} if choices else set()


def goal_id_rotation(days, used):
    """Reserve one existing GOAL slot, including the last daily slot."""
    if type(used) is not int or not 0 <= used <= 80:
        raise ValueError('Invalid GOAL daily usage')
    return list(days)[:min(1, 79-used)] if used < 80 else None
