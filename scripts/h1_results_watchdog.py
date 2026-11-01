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
# Never dispatch a fallback more often than once per 65 minutes; this is
# <= 20 candidates/hour even if GitHub's best-effort hourly cron is delayed.
# The original 90-minute fallback left verified first checks unnecessarily late.
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
        choice = plan(payload['workflow_runs'], now, age)
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
