"""Strict, score-free locators from complete persisted API-Football identities.

Never creates human approvals, guesses aliases or changes FT validators.
The ID batch replaces one date slot; queue/visit cooldowns remain mandatory.
"""
from datetime import timedelta
from .lab_results import utc, retry_wait, RETRY, DELAY, HORIZON
from .lab_identity import select_event, pair_level
from .lab_ft_day_identity import fixture_index, check_day_identity, _read_event
from .lab_ft_crosswalk import providers_from_final, event_id


def plan_index_ids(selected, matches, index, now, *, reserved=(), max_batch=20):
    if max_batch <= 0:
        return {}
    reserved = set(reserved)
    claimed = {event_id('api_football', providers_from_final(row).get('api_football'))
               for row in matches.values() if row.get('status') == 'FINAL'}
    result = {}
    for key in selected:
        row = matches.get(key, {})
        ko = utc(row.get('kickoff_utc'))
        last, visit = utc(row.get('evidence_checked_at')), utc(row.get('queue_visited_at'))
        if (row.get('status') not in ('PENDING', 'PROVIDER_ERROR') or ko is None
                or not ko + DELAY <= now <= ko + HORIZON
                or (last and now < last + retry_wait(row))
                or (visit and now < visit + RETRY)):
            continue
        day = ko.date().isoformat()
        observed = utc((index.get('days',{}).get(day) or {}).get('fetched_at'))
        if observed is None or not timedelta(0) <= now-observed <= timedelta(days=45):
            continue
        rows = fixture_index(index, day)
        if rows is None:
            continue
        source, level, _ = select_event(row, rows,
            lambda x:(x['home'],x['away']), lambda x:x['kickoff_utc'], window_seconds=5400)
        if (source is None or abs(utc(source['kickoff_utc'])-ko)>timedelta(minutes=5)
                or source['fixture_id'] in reserved or str(source['fixture_id']) in claimed):
            continue
        # A source fixture can never be assigned to two observed identities.
        duplicate = any(other != key and utc(g.get('kickoff_utc')) is not None
            and abs(utc(g['kickoff_utc']) - ko) <= timedelta(minutes=90)
            and pair_level(g.get('home'),g.get('away'),source['home'],source['away'])
            for other,g in matches.items())
        if duplicate:
            continue
        target = {'match_key':key, 'home':row['home'], 'away':row['away'],
            'kickoff_utc':row['kickoff_utc'], 'source_identity':dict(source),
            'provider_fixture_id':source['fixture_id'],
            'provider_home_team_id':source['home_team_id'],
            'provider_away_team_id':source['away_team_id'],
            'provider_competition_id':source['competition_id'],
            'provider_kickoff_utc':source['kickoff_utc'], 'identity_level':level,
            'locator_source':'COMPLETE_DAY_STRICT_IDENTITY_NOT_AN_APPROVAL'}
        if check_day_identity(index,target) is not None:
            continue
        result[key] = target
        reserved.add(source['fixture_id'])
        if len(result) >= max_batch:
            break
    return result if max_batch > 0 else {}


class IndexProbe:
    """Share the adapter's single ID batch and three-request total ceiling."""
    def __init__(self, adapter, targets):
        self.adapter, self.targets = adapter, targets
        self.outcomes = {}
        self.days = adapter.days  # complete date evidence remains visible to V7
        adapter.extra_fixture_ids = [t['provider_fixture_id'] for t in targets.values()]

    def lookup(self, signal):
        from .lab_api_football import _score, MAX_DAYS
        from .lab_api_football_errors import failure_from
        a = self.adapter
        key = signal.get('match_key')
        target = self.targets.get(key)
        if target is None:
            return a.lookup(signal)
        def finish(result, reason):
            self.outcomes[key] = reason
            a.reasons[reason] += 1
            return result, reason
        if not a.key or a.max_days == 0:
            return finish(None,'api_football_index_id_disabled')
        if any(signal.get(f) != target.get(f) for f in ('match_key','home','away','kickoff_utc')):
            return finish(None,'api_football_index_signal_changed')
        if a.id_cache is None:
            if a.requests + a.id_requests >= MAX_DAYS:
                return finish(None,'api_football_index_id_budget_deferred')
            ids = sorted(set(a.extra_fixture_ids +
                [t['provider_fixture_id'] for t in a.reviewed_targets.values()]))
            if len(ids) > 20:
                return finish(None,'api_football_index_id_batch_too_large')
            a.id_requests += 1
            try:
                a.id_cache = a.id_fetch(ids,a.key)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                a.id_cache = {}
                a.reviewed_error_details[key] = failure_from(exc)
                return finish(None,'api_football_index_id_unavailable')
        event = a.id_cache.get(target['provider_fixture_id'])
        if event is None:
            return finish(None,'api_football_index_id_missing')
        identity = _read_event(event,target['provider_kickoff_utc'][:10])
        if identity != target['source_identity']:
            return finish(None,'api_football_index_identity_changed')
        # Exact same regulation-time, score, status and team gates as date lookup.
        result, reason = _score(signal,event,target['identity_level'])
        return finish(result,reason)
