"""Offline, individually auditable frozen FT cohort. No provider requests/writes."""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from h1lab.lab_identity import pair_level
from h1lab.lab_ft_index_probe import plan_index_ids
from h1lab.lab_ft_recovery_turn import plan_exact_goal_ids
from h1lab.lab_results import utc, retry_wait, RETRY

PROVIDERS = ('bsd', 'api_football', 'goal', 'openfoot', 'espn', 'sportscore', 'thesportsdb', 'fotmob', 'monte_carlos')


def audit(root, cohort, now):
    from scripts.lab_results import competitions_by_key
    def read(path): return json.loads((root / path).read_text())
    matches = read('data/lab/ft-ledger.json')['matches']
    report = read('docs/lab/ft-results.json')
    review = {r['match_key']: r for r in read('docs/lab/ft-identity-review.json')['games']}
    index = read('data/lab/ft-api-football-day-index.json')
    observed_competitions = competitions_by_key(read('data/state.json').get('alerts', []))
    keys = cohort['match_keys']
    if len(keys) != cohort['cohort_size'] or len(set(keys)) != len(keys) or any(k not in matches for k in keys):
        raise ValueError('Frozen cohort missing or duplicated')
    # Counterfactual eligibility only: no HTTP and no manufactured observation.
    later = now + timedelta(days=2)
    api_locators = plan_index_ids(keys, matches, index, later, max_batch=len(keys))
    goal_locators = plan_exact_goal_ids(matches, {'schema_version': 1, 'games': list(review.values())}, later)
    rows = []; causes = Counter(); competitions = defaultdict(Counter)
    for key in keys:
        row = matches[key]; game = review.get(key, {})
        reasons = row.get('last_provider_visit', {}).get('reasons', row.get('provider_reasons', {}))
        local = []
        for p in PROVIDERS:
            cs = [c for c in game.get('candidates', []) if c.get('provider') == p]
            local.append({'provider': p, 'last_reason': reasons.get(p),
                'candidate_count': len(cs),
                'strict_pair_candidates': sum(bool(pair_level(row['home'], row['away'],
                    c.get('provider_home'), c.get('provider_away'))) for c in cs),
                'known_ids': sorted(set(str(c['provider_event_id']) for c in cs if c.get('provider_event_id'))),
                'coverage': 'CANDIDATES_ONLY_NOT_PROVEN_FIXTURE_COVERAGE' if cs else 'NOT_DEMONSTRATED',
                'fixture_http_attribution': 'UNKNOWN_UNLESS_SEPARATELY_LOGGED'})
        evidence = bool(row.get('evidence_checked_at'))
        is_final = row.get('status') == 'FINAL'
        blocked = []
        last, visit = utc(row.get('evidence_checked_at')), utc(row.get('queue_visited_at'))
        if last and now < last + retry_wait(row): blocked.append('GAME_EVIDENCE_COOLDOWN')
        if visit and now < visit + RETRY: blocked.append('GAME_VISIT_COOLDOWN')
        if game.get('possible_duplicates'): blocked.append('POSSIBLE_DUPLICATE')
        if row.get('status') not in ('PENDING', 'PROVIDER_ERROR', 'FINAL'): blocked.append(row.get('status'))
        if is_final: cause = 'CERTIFIED'
        elif key in api_locators or key in goal_locators: cause = 'STRICT_LOCATOR_AWAITING_VALID_CURRENT_RESPONSE'
        elif any('regulation' in str(v) or 'score_conflict' in str(v) for v in reasons.values()): cause = 'INSUFFICIENT_OR_CONTRADICTORY_FT_EVIDENCE'
        elif not evidence: cause = 'NO_EFFECTIVE_CHECK_DOCUMENTED'
        elif any(c['candidate_count'] for c in local): cause = 'IDENTITY_OR_CURRENT_FT_UNRESOLVED'
        else: cause = 'COVERAGE_NOT_DEMONSTRATED'
        causes[cause] += 1
        comp = game.get('observed_competition') or observed_competitions.get(key, 'UNKNOWN')
        competitions[comp]['cohort'] += 1; competitions[comp]['certified'] += is_final
        competitions[comp]['effective_check_documented'] += evidence
        rows.append({'match_key': key, 'home': row['home'], 'away': row['away'],
            'kickoff_utc': row['kickoff_utc'], 'competition': comp, 'status': row['status'],
            'effective_check_documented': evidence, 'primary_obstacle': cause, 'current_blockers': blocked,
            'strict_api_locator': key in api_locators, 'strict_goal_locator': key in goal_locators,
            'cross_provider_competition_identity': 'NOT_PROVEN', 'providers': local})
    runs = read('data/lab/ft-api-audit.json')['runs']
    last_run = runs[-1] if runs else {}
    return {'schema_version': 1, 'measured_at': now.isoformat(), 'baseline_sha': cohort['baseline_sha'],
        'input_ledger_sha256': hashlib.sha256((root/'data/lab/ft-ledger.json').read_bytes()).hexdigest(),
        'cohort_size': len(keys), 'certified_since_baseline': sum(r['status']=='FINAL' for r in rows),
        'still_pending': sum(r['status']!='FINAL' for r in rows),
        'without_effective_check_documented': sum(not r['effective_check_documented'] and r['status']!='FINAL' for r in rows),
        'strict_api_locators_after_time_gates': len(api_locators),
        'strict_goal_locators_after_time_gates': sum(k in goal_locators for k in keys),
        'proven_cross_provider_competition_bindings': 0,
        'demonstrably_irrecoverable': 0, 'obstacles': dict(causes),
        'by_competition': dict(competitions),
        'last_normal_run_http': last_run.get('http_requests', {}),
        'last_run_new_ft': last_run.get('cohort_keys', {}).get('newly_certified_existing_pending', []),
        'last_run_trigger': last_run.get('trigger'), 'last_run_utc': last_run.get('utc'),
        'public_counts': report['timing_counts'], 'games': rows,
        'limitations': ['No HTTP performed. Missing effective-check records do not prove no historical HTTP.',
            'Strict locators are counterfactual after existing time gates, not certificates or live availability.',
            'Candidate absence is not proof of no supplier coverage; no game declared technically irrecoverable.',
            'Strong fuzzy review labels are not proven identities. No competition bindings activated.',
            'Per-provider HTTP is run-level; not invented as per-fixture HTTP attribution.']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--at', default=None)
    a=p.parse_args(); now=utc(a.at) if a.at else datetime.now(timezone.utc)
    if now is None: raise ValueError('Aware UTC audit time required')
    cohort=json.loads((a.root/'reports/ft-old-cohort-180.json').read_text())
    print(json.dumps(audit(a.root, cohort, now), ensure_ascii=False, sort_keys=True, indent=2))


if __name__=='__main__': main()
