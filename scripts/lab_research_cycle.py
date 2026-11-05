"""Autonomous research cycle CLI (exploratory; never validation).

Run kinds keep demonstration and operational research physically separate:
  OPERATIONAL    data/research/memory.jsonl + docs/research/autonomous-research.json
                 accepts only the offline proposer or ONE real bounded LLM call
  DEMONSTRATION  docs/research/demo/memory.jsonl + docs/research/demo/panel.json
                 accepts response files and the SIMULATED LLM, never real calls
  TEST           explicit --memory/--panel only (temporary paths)

Modes:
  offline        offline proposer only, zero LLM calls (default)
  llm-response   plans from a saved response file (DEMONSTRATION/TEST only), zero calls
  llm-simulated  SIMULATED LLM through the real request path (DEMONSTRATION/TEST), zero calls
  packet         print the exact packet an LLM would receive, zero calls
  llm-live       ONE request (OPERATIONAL only). Refused unless config llm_live_enabled,
                 --allow-network, and either the original 4-slot schedule on main
                 (attempt 1, <=4 per UTC day) or workflow_dispatch with
                 RESEARCH_LLM_CONFIRMATION=INVESTIGAR_UMA_VEZ. No retries.
  recover-torn-tail  explicit recovery of an interrupted foreign write (quarantines tail)

Exit 0 on success or clean NOT_RUN, 2 on refusal/error (JSON reason on stdout).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from h1lab.research_cycle import build_panel, llm_packet, run_cycle, write_panel
from h1lab.research_dataset import build_dataset
from h1lab.research_gates import EXPLORATION_ALLOWED, exploration_gate
from h1lab.research_memory import read_memory, recover_torn_tail

ROOT = Path(__file__).resolve().parents[1]
PATHS = {'OPERATIONAL': ('data/research/memory.jsonl', 'docs/research/autonomous-research.json'),
         'DEMONSTRATION': ('docs/research/demo/memory.jsonl', 'docs/research/demo/panel.json')}
LIVE_CONFIRM = 'INVESTIGAR_UMA_VEZ'
MODEL = '@cf/meta/llama-3.1-8b-instruct-fast'
SCHEDULE = '43 1,7,13,19 * * *'        # the four existing daily opportunities, unchanged
MAX_DAILY_LIVE_CALLS = 4
MODE_KINDS = {'offline': ('OPERATIONAL', 'DEMONSTRATION', 'TEST'),
              'llm-response': ('DEMONSTRATION', 'TEST'), 'llm-simulated': ('DEMONSTRATION', 'TEST'),
              'packet': ('OPERATIONAL', 'DEMONSTRATION', 'TEST'), 'llm-live': ('OPERATIONAL',),
              'recover-torn-tail': ('OPERATIONAL', 'DEMONSTRATION', 'TEST')}


def live_authorisation(env, memory, today):
    """Mirror of the existing autonomous workflow protections (fail closed)."""
    if env.get('GITHUB_REF') != 'refs/heads/main':
        raise ValueError('LIVE_NOT_MAIN')
    if env.get('GITHUB_RUN_ATTEMPT') != '1':
        raise ValueError('LIVE_RERUN_NOT_AUTHORISED')
    event = env.get('GITHUB_EVENT_NAME')
    if event == 'schedule':
        if env.get('GITHUB_EVENT_SCHEDULE') != SCHEDULE:
            raise ValueError('LIVE_SCHEDULE_NOT_AUTHORISED')
    elif event == 'workflow_dispatch':
        if env.get('RESEARCH_LLM_CONFIRMATION') != LIVE_CONFIRM:
            raise ValueError('LIVE_CONFIRMATION_MISSING')
    else:
        raise ValueError('LIVE_EVENT_NOT_AUTHORISED')
    used = sum(c.get('llm_calls', 0) for c in memory
               if c.get('record_type') == 'CYCLE' and c.get('llm_origin') == 'LLM_LIVE'
               and str(c.get('recorded_at', ''))[:10] == today)
    if used >= MAX_DAILY_LIVE_CALLS:
        raise ValueError('LIVE_DAILY_LIMIT')
    return event


def main(argv=None, *, env=None, opener=None):
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=ROOT)
    ap.add_argument('--mode', choices=sorted(MODE_KINDS), default='offline')
    ap.add_argument('--run-kind', choices=['OPERATIONAL', 'DEMONSTRATION', 'TEST'], default='OPERATIONAL')
    ap.add_argument('--memory', type=Path, default=None)
    ap.add_argument('--panel', type=Path, default=None)
    ap.add_argument('--response', type=Path, help='LLM response JSON content (llm-response mode)')
    ap.add_argument('--budget', type=int, default=None)
    ap.add_argument('--now', default=None, help='UTC ISO time (reproducible replays)')
    ap.add_argument('--allow-network', action='store_true')
    args = ap.parse_args(argv)

    def refuse(reason):
        print(json.dumps({'status': 'REFUSED_OR_FAILED', 'reason': reason}))
        print('RESEARCH_CYCLE_FAILED', file=sys.stderr)
        return 2

    if args.run_kind not in MODE_KINDS[args.mode]:
        return refuse('MODE_%s_NOT_ALLOWED_FOR_%s' % (args.mode, args.run_kind))
    root = args.root
    if args.run_kind == 'TEST':
        if not args.memory or not args.panel:
            return refuse('TEST_RUN_REQUIRES_EXPLICIT_PATHS')
        memory_path, panel_path = args.memory, args.panel
    else:
        mem_default, panel_default = PATHS[args.run_kind]
        if (args.memory and args.memory.resolve() != (root / mem_default).resolve()
                and args.memory.resolve().is_relative_to(root.resolve())):
            return refuse('NON_DEFAULT_IN_REPO_MEMORY_PATH')
        memory_path = args.memory or root / mem_default
        panel_path = args.panel or root / panel_default
    if args.mode == 'recover-torn-tail':
        try:
            print(json.dumps(recover_torn_tail(memory_path), sort_keys=True))
            return 0
        except (ValueError, OSError) as exc:
            return refuse(type(exc).__name__ + ': ' + str(exc)[:200])
    try:
        now = (datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)).replace(microsecond=0)
    except ValueError:
        return refuse('INVALID_NOW')
    if now.tzinfo is None:
        return refuse('UTC_NOW_REQUIRED')
    gate = exploration_gate(root, env)
    if gate['state'] != EXPLORATION_ALLOWED:
        print(json.dumps({'status': 'NOT_RUN', 'reason': gate['state'],
                          'problems': gate.get('problems', [])[:10]}, sort_keys=True))
        return 0 if gate['state'] == 'EXPLORATION_DISABLED' else 2
    try:
        dataset = build_dataset(root, now=now)
        memory = read_memory(memory_path)
        max_plans = gate['config']['max_llm_plans_per_call']
        packet = llm_packet(gate, dataset, memory, max_plans)
        llm = None
        if args.mode == 'packet':
            print(json.dumps(packet, ensure_ascii=False, indent=1, sort_keys=True))
            return 0
        from h1lab.research_llm import invoke_once, parse_response
        if args.mode == 'llm-response':
            if not args.response:
                raise ValueError('RESPONSE_FILE_REQUIRED')
            llm = parse_response(args.response.read_text(encoding='utf-8'), max_plans=max_plans)
            llm.update(origin='RESPONSE_FILE_NOT_LIVE_LLM', llm_calls=0,
                       packet_sha256=packet['packet_sha256'])
        elif args.mode == 'llm-simulated':
            from h1lab.research_simulated_llm import ORIGIN, SimulatedLLMOpener
            sim = SimulatedLLMOpener()
            reply = invoke_once(packet, endpoint='https://simulated-llm.invalid/v1/chat/completions',
                                model='SIMULATED', opener=sim)
            llm = parse_response(reply['content'], max_plans=max_plans)
            # Simulated replies are not provider calls: llm_calls stays 0.
            llm.update(origin=ORIGIN, llm_calls=0, simulated_requests=len(sim.calls),
                       packet_sha256=packet['packet_sha256'])
        elif args.mode == 'llm-live':
            if not gate['config']['llm_live_enabled']:
                raise ValueError('LLM_LIVE_DISABLED_BY_CONFIG')
            if not args.allow_network:
                raise ValueError('LLM_LIVE_NOT_AUTHORISED')
            live_authorisation(env, memory, now.date().isoformat())
            account, key = env.get('CLOUDFLARE_ACCOUNT_ID', ''), env.get('MASTER_BRAIN_LLM_API_KEY', '')
            if not re.fullmatch(r'[a-fA-F0-9]{32}', account) or not key:
                raise ValueError('LLM_SECRET_MISSING')
            kw = {'endpoint': 'https://api.cloudflare.com/client/v4/accounts/%s/ai/v1/chat/completions' % account,
                  'model': MODEL, 'api_key': key}
            if opener is not None:
                kw['opener'] = opener
            reply = invoke_once(packet, **kw)   # exactly one request; any failure aborts
            llm = parse_response(reply['content'], max_plans=max_plans)
            llm.update(origin='LLM_LIVE', llm_calls=1, packet_sha256=packet['packet_sha256'],
                       usage=reply['usage'])
        result = run_cycle(gate=gate, dataset=dataset, memory_path=memory_path, now=now,
                           run_kind=args.run_kind, cycle_label=args.mode, llm=llm,
                           offline_budget=args.budget)
        if result['status'] == 'RUN':
            write_panel(panel_path, build_panel(read_memory(memory_path), gate, now=now))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return refuse(type(exc).__name__ + ': ' + str(exc)[:200])
    result.pop('records', None)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result['status'] in ('RUN', 'NOT_RUN') else 2


if __name__ == '__main__':
    raise SystemExit(main())
