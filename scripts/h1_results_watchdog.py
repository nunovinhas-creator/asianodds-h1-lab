"""Bounded fallback for delayed H1 schedules; never calls a sports provider.

A committed receipt proves completion of reconciliation + promotion + rendering,
not provider availability, result coverage, or operational stability.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from scripts.lab_ft_watchdog import OWNER_REPO, SOURCE_WORKFLOW, _json_request, _utc

RECEIPT = Path('data/health/h1-results.json')
# Free-tier safeguard: a completed H1 cycle checks at most 20 fixtures.
# Never dispatch a fallback more often than once per 65 minutes.
# The normal hourly cron and its separate 45-minute due gate remain unchanged;
# this bounds fallback frequency without promising an overall hourly quota.
# The original 90-minute fallback left first checks unnecessarily late.
MIN_AGE = timedelta(minutes=65)
OUTPUTS = ('data/results.csv', 'data/result_audit.json')


def receipt_age(root, now):
    try:
        receipt = json.loads((Path(root) / RECEIPT).read_text())
        if receipt['schema_version'] != 1 or receipt['status'] != 'CYCLE_COMPLETED':
            return None
        age = now - _utc(receipt['completed_at'])
        if age < timedelta(0):
            return None
        for name in OUTPUTS:
            if hashlib.sha256((Path(root) / name).read_bytes()).hexdigest() != receipt['sha256'][name]:
                return None
        return age
    except (OSError, ValueError, KeyError, TypeError):
        return None


def proven_noop_jobs(payload):
    """Completed H1 run performed no promotion, provider checks or publication.

    Only the GitHub Actions *job step conclusions* are accepted as evidence.
    Missing/unknown status fails closed and remains a normal recent attempt.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get('jobs'), list):
        return False
    jobs = [j for j in payload['jobs']
            if isinstance(j, dict) and j.get('name') == 'results']
    if len(jobs) != 1 or jobs[0].get('status') != 'completed' or jobs[0].get('conclusion') != 'success':
        return False
    steps = jobs[0].get('steps')
    if not isinstance(steps, list):
        return False
    by_name = {s.get('name'): s.get('conclusion') for s in steps
               if isinstance(s, dict) and isinstance(s.get('name'), str)}
    required = (
        'Avoid duplicate queued result cycles',
        'Import confirmed LAB FT into H1 without changing signal rules',
        'Check BSD and TheSportsDB results with strict FT validation',
        'Rebuild ROI for singles and triples',
        'Record completed result cycle (not a coverage certificate)',
        'Publish confirmed finals and audit',
    )
    return (by_name.get(required[0]) == 'success'
            and all(by_name.get(name) == 'skipped' for name in required[1:]))


def annotate_recent_noops(runs, now, base, headers, opener):
    """At most four read-only GitHub job lookups for recent completed attempts.

    Never mark an active, failed, unknown or partially executed job as a noop;
    never query sports providers. If the bound is exceeded, fail closed.
    """
    eligible = []
    for entry in runs:
        if not isinstance(entry, dict):
            raise ValueError('Invalid GitHub run')
        if entry.get('status') != 'completed':
            continue
        created = _utc(entry.get('created_at'))
        if not timedelta(0) <= now - created < MIN_AGE:
            continue
        eligible.append(entry)
    if len(eligible) > 4:
        raise ValueError('Too many recent H1 runs to certify no-ops')
    updated = [dict(entry) if isinstance(entry, dict) else entry for entry in runs]
    for index, entry in enumerate(runs):
        if entry not in eligible:
            continue
        # Reject malformed run IDs rather than constructing arbitrary URLs.
        run_id = entry.get('id')
        if type(run_id) is not int or run_id <= 0:
            raise ValueError('Missing H1 run identifier')
        uri = base.rsplit('/actions/workflows/', 1)[0] + '/actions/runs/' + str(run_id) + '/jobs?per_page=10'
        jobs = _json_request(opener, Request(uri, headers=headers))
        updated[index]['verified_noop'] = (
            entry.get('conclusion') == 'success'
            and proven_noop_jobs(jobs)
        )
    return updated


def plan(runs, now, age=None):
    if now.tzinfo is None or not isinstance(runs, list) or len(runs) > 100:
        raise ValueError('Invalid workflow history or clock')
    if age is not None and timedelta(0) <= age < MIN_AGE:
        return {'dispatch': False, 'reason': 'RECENT_COMPLETED_CYCLE'}
    times = []
    for run in runs:
        if not isinstance(run, dict):
            raise ValueError('Invalid run')
        when = _utc(run.get('created_at'))
        if when > now + timedelta(minutes=2):
            raise ValueError('Future run')
        # Any queued/active attempt can still publish: do not pile up dispatches.
        if run.get('status') != 'completed':
            return {'dispatch': False, 'reason': 'ACTIVE_OR_UNKNOWN_RUN'}
        # A completed workflow whose due gate skipped every H1 effect is
        # NOT a provider attempt, and must not extend the fallback cooldown.
        if run.get('verified_noop') is not True:
            times.append(when)
    if times and now - max(times) < MIN_AGE:
        return {'dispatch': False, 'reason': 'ATTEMPT_COOLDOWN'}
    return {'dispatch': True, 'reason': 'OVERDUE_CYCLE'}


def run(*, env=None, now=None, root='.', opener=urlopen):
    e = os.environ if env is None else env
    if (e.get('GITHUB_WORKFLOW') != SOURCE_WORKFLOW
            or e.get('GITHUB_REF') != 'refs/heads/main'
            or e.get('GITHUB_REPOSITORY') != OWNER_REPO
            or e.get('GITHUB_EVENT_NAME') not in ('schedule', 'workflow_dispatch', 'push')):
        return {'dispatch': False, 'reason': 'CONTEXT_SKIP'}
    if not e.get('GITHUB_TOKEN'):
        return {'dispatch': False, 'reason': 'NO_TOKEN'}
    now = datetime.now(timezone.utc) if now is None else now
    if now.tzinfo is None:
        return {'dispatch': False, 'reason': 'INVALID_CLOCK'}
    age = receipt_age(root, now)
    if age is not None and age < MIN_AGE:
        return {'dispatch': False, 'reason': 'RECENT_COMPLETED_CYCLE'}
    base = 'https://api.github.com/repos/' + OWNER_REPO + '/actions/workflows/results.yml'
    headers = {'Authorization': 'Bearer ' + e['GITHUB_TOKEN'],
               'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
    try:
        payload = _json_request(opener, Request(base + '/runs?branch=main&per_page=100', headers=headers))
        history = payload['workflow_runs']
        # Receipt is checked first; once genuinely stale, inspect only recent
        # H1 job-step conclusions. Failed/unknown runs remain conservative.
        history = annotate_recent_noops(history, now, base, headers, opener)
        choice = plan(history, now, age)
        if not choice['dispatch']:
            return choice
        body = json.dumps({'ref': 'main', 'inputs': {'trigger_source': 'h1-results-watchdog'}}).encode()
        request = Request(base + '/dispatches', data=body,
                          headers={**headers, 'Content-Type': 'application/json'}, method='POST')
        with opener(request, timeout=10) as response:
            if response.status != 204:
                raise ValueError('Dispatch not accepted')
        return {'dispatch': True, 'reason': 'DISPATCH_ACCEPTED'}
    except (OSError, ValueError, KeyError, TypeError):
        return {'dispatch': False, 'reason': 'GITHUB_UNAVAILABLE'}


def write_receipt(root='.', now=None, env=None):
    root = Path(root)
    e = os.environ if env is None else env
    # Missing or truncated output cannot receive a completion receipt.
    import csv
    with (root / OUTPUTS[0]).open(newline='') as stream:
        rows = csv.DictReader(stream)
        if rows.fieldnames != ['match_key', 'status', 'home_goals', 'away_goals', 'source']:
            raise ValueError('Invalid results CSV')
        for row in rows:
            if None in row or any(value is None for value in row.values()):
                raise ValueError('Incomplete results CSV')
    audit = json.loads((root / OUTPUTS[1]).read_text())
    if not isinstance(audit, dict):
        raise ValueError('Invalid result audit')
    document = {'schema_version': 1, 'status': 'CYCLE_COMPLETED',
                'completed_at': (now or datetime.now(timezone.utc)).isoformat(),
                'run_id': e.get('GITHUB_RUN_ID'), 'source_sha': e.get('H1_SOURCE_SHA'),
                'sha256': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in OUTPUTS}}
    target = root / RECEIPT
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(document, indent=2) + '\n')
    temporary.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('watch', 'due', 'receipt'), nargs='?', default='watch')
    args = parser.parse_args()
    if args.mode == 'receipt':
        write_receipt()
    elif args.mode == 'due':
        age = receipt_age('.', datetime.now(timezone.utc))
        fallback = os.environ.get('H1_TRIGGER_SOURCE') == 'h1-results-watchdog'
        scheduled = os.environ.get('GITHUB_EVENT_NAME') == 'schedule'
        threshold = MIN_AGE if fallback else timedelta(minutes=45)
        due = not ((fallback or scheduled) and age is not None and age < threshold)
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('run=' + str(due).lower() + '\n')
        print('H1_RESULTS_DUE', due)
    else:
        print(json.dumps(run(), sort_keys=True))


if __name__ == '__main__':
    main()
