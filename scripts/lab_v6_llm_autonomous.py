"""Bounded autonomous V6 research: discover first, one optional Workers AI call.

Never writes betting, H1 or FT data. Successful output is validated by an
independent publishing job. Failed calls must NOT retry automatically.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

from h1lab.v6_discovery_planner import candidate_id, plan
from h1lab.v6_llm_investigator import build_packet, invoke

ROOT = Path(__file__).resolve().parents[1]
MODEL = '@cf/meta/llama-3.1-8b-instruct-fast'
SCHEDULE = '43 1,7,13,19 * * *'
MAX_DAILY_AUTOMATED_REQUESTS = 4
AUTONOMY_CONFIRM = 'AUTONOMIA_LLM_UMA_VEZ'


def choose_candidates(root):
    """Fresh full archive scan and deterministic, outcome-blind shortlist.

    Prefer pairs for statistical power; retain a triple for mechanistic breadth.
    No ROI/FT is consulted for ranking.
    """
    proposal_queue = plan(root, limit=100)
    items = proposal_queue['queue']
    pairs = [p for p in items if len(p['feature_codes']) == 2]
    triples = [p for p in items if len(p['feature_codes']) == 3]
    selected = (pairs[:2] + triples[:1]) if pairs else triples[:3]
    if not selected:
        raise ValueError('NO_ELIGIBLE_AUTONOMOUS_COMBINATIONS')
    packet = build_packet(root)
    family = {item['code']: item['family'] for item in packet['feature_catalogue']}
    if any(c not in family for x in selected for c in x['feature_codes']):
        raise ValueError('UNKNOWN_AUTO_FEATURE')
    return {
        'choices': selected, 'queue': proposal_queue,
        'policy': 'HASH_ORDER_OUTCOME_BLIND_PREFER_PAIRS_ONE_TRIPLE',
    }


def utc_archives_today(root, today):
    archive_dir = Path(root) / 'docs/lab/llm-investigator-runs'
    total = 0
    for path in archive_dir.glob('*.json'):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 80000:
            raise ValueError('UNSAFE_AUTONOMOUS_ARCHIVE')
        obj = json.loads(path.read_text(encoding='utf-8'))
        date = obj.get('recorded_at_utc')
        if (isinstance(date, str) and date[:10] == today
                and isinstance(obj.get('autonomy'), dict)
                and obj['autonomy'].get('trigger') == 'schedule'):
            total += 1
    return total


def run(root, *, mode, allow_network=False, confirm='', env=None,
        now=None, opener=None):
    env = os.environ if env is None else env
    now = datetime.now(timezone.utc) if now is None else now
    if now.tzinfo is None:
        raise ValueError('UTC_TIMESTAMP_REQUIRED')
    today = now.astimezone(timezone.utc).date().isoformat()
    chosen = choose_candidates(root)
    pool = chosen['choices']
    preview = {
        'status': 'PREVIEW_ONLY_NO_LLM_CALLS',
        'eligible_remaining': chosen['queue']['remaining'],
        'candidate_pool': [{'candidate_id': x['candidate_id'], 'feature_codes': x['feature_codes']}
                           for x in pool],
        'selection_policy': chosen['policy'],
        'no_empirical_validation': True,
    }
    if mode == 'preview':
        return preview
    if mode != 'live' or not allow_network:
        raise ValueError('AUTONOMOUS_NETWORK_NOT_AUTHORIZED')
    if env.get('GITHUB_REF') != 'refs/heads/main':
        raise ValueError('AUTO_NOT_MAIN')
    event = env.get('GITHUB_EVENT_NAME')
    if event == 'schedule':
        if (env.get('GITHUB_RUN_ATTEMPT') != '1'
                or env.get('GITHUB_EVENT_SCHEDULE') != SCHEDULE):
            raise ValueError('AUTO_SCHEDULE_OR_RERUN_NOT_AUTHORIZED')
    elif event == 'workflow_dispatch':
        if confirm != AUTONOMY_CONFIRM:
            raise ValueError('MANUAL_AUTO_CONFIRMATION_MISSING')
    else:
        raise ValueError('AUTO_EVENT_NOT_AUTHORIZED')
    # Counts successful archive records as a second protection. Fixed four
    # cron slots + no retries bound the number of scheduled attempts per day.
    if event == 'schedule' and utc_archives_today(root, today) >= MAX_DAILY_AUTOMATED_REQUESTS:
        raise ValueError('AUTO_DAILY_ARCHIVE_LIMIT')
    account = env.get('CLOUDFLARE_ACCOUNT_ID', '')
    key = env.get('MASTER_BRAIN_LLM_API_KEY', '')
    if not re.fullmatch(r'[a-fA-F0-9]{32}', account) or not key:
        raise ValueError('AUTO_CLOUDFLARE_SECRET_MISSING')
    endpoint = ('https://api.cloudflare.com/client/v4/accounts/'
                + account + '/ai/v1/chat/completions')
    pool_codes = [x['feature_codes'] for x in pool]
    kw = {'candidate_options': pool_codes, 'endpoint': endpoint,
          'model': MODEL, 'api_key': key}
    if opener is not None:
        kw['opener'] = opener
    # Exactly one provider call. Errors abort; no retry, no fabricated drafts.
    output = invoke(build_packet(root), **kw)
    codes = sorted(output['proposals'][0]['feature_codes'])
    winner = candidate_id(codes)
    ids = [x['candidate_id'] for x in pool]
    if winner not in ids:
        raise ValueError('AUTONOMOUS_UNKNOWN_WINNER')
    output['autonomy'] = {
        'schema_version': 1,
        'trigger': event,
        'candidate_id': winner,
        'candidate_pool_ids': ids,
        'selection_policy': chosen['policy'],
        'daily_scheduled_call_slots': MAX_DAILY_AUTOMATED_REQUESTS,
        'account_neurons_verified': False,
        'status': 'SHADOW_EXPLORATION_NOT_VALIDATION',
    }
    return output


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--mode', choices=['preview', 'live'], default='preview')
    parser.add_argument('--allow-network', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = run(args.root, mode=args.mode, allow_network=args.allow_network,
                     confirm=os.environ.get('LLM_AUTO_CONFIRMATION', ''))
    except (ValueError, KeyError, TypeError) as exc:
        audit = getattr(exc, 'audit', {'status': 'BLOCKED_OR_FAILED_USAGE_UNKNOWN', 'llm_calls': None})
        print(json.dumps(audit, sort_keys=True, allow_nan=False))
        print('AUTONOMOUS_DISCOVERY_BLOCKED: ' + type(exc).__name__ + ' (' +
              str(exc)[:120] + ')', file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
