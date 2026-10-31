"""Bounded old-fixture priority for existing API-Football ID verification.

GOAL strict historical candidates remain audit-only without an independently
verified binding to the observed competition; names/times/provider IDs alone
cannot authorize cross-provider result certification.
"""
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
    """Diagnostic-only GOAL locators; NEVER schedule or certify from this list.

    This information is useful for the old-cohort offline audit, but no
    independent observed competition identity has been proven.
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


def recovery_turn(api_targets, goal_targets, matches):
    """At most one strict, already-valid API-Football ID locator may get priority.

    Explicitly refuse a GOAL candidate rather than accidentally treating
    its historical league name as proof of the observed competition.
    """
    if goal_targets:
        raise ValueError('GOAL old-ID certification disabled: competition unproven')
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    choices = []
    for key in api_targets:
        row = matches[key]
        last = row.get('api_football_index_id_last_evidence', {}).get('checked_at_utc')
        choices.append((utc(last) or minimum, utc(row['kickoff_utc']), key))
    return {min(choices)[2]} if choices else set()


