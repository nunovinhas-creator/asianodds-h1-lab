"""Autonomous research cycle CLI (exploratory; never validation).

Modes:
  offline       offline proposer only, zero LLM calls (default)
  llm-response  plans from a saved LLM response file (fixture or reviewed output), zero calls
  packet        print the exact packet an LLM would receive, zero calls
  llm-live      ONE request; refused unless config llm_live_enabled=true, --allow-network
                and RESEARCH_LLM_CONFIRMATION=INVESTIGAR_UMA_VEZ. No retries.

Writes only --memory (append-only) and --panel. Exit 0 on success or clean NOT_RUN,
2 on refusal/error (always with a JSON reason on stdout; never silent).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from h1lab.research_cycle import build_panel, llm_packet, run_cycle, write_panel
from h1lab.research_dataset import build_dataset
from h1lab.research_gates import EXPLORATION_ALLOWED, exploration_gate
from h1lab.research_memory import DEFAULT_PATH, read_memory

ROOT = Path(__file__).resolve().parents[1]
PANEL = 'docs/research/autonomous-research.json'
LIVE_CONFIRM = 'INVESTIGAR_UMA_VEZ'
MODEL = '@cf/meta/llama-3.1-8b-instruct-fast'


def main(argv=None, *, env=None, opener=None):
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=ROOT)
    ap.add_argument('--mode', choices=['offline', 'llm-response', 'packet', 'llm-live'], default='offline')
    ap.add_argument('--memory', type=Path, default=None)
    ap.add_argument('--panel', type=Path, default=None)
    ap.add_argument('--response', type=Path, help='LLM response JSON content (llm-response mode)')
    ap.add_argument('--budget', type=int, default=None)
    ap.add_argument('--now', default=None, help='UTC ISO time (reproducible replays)')
    ap.add_argument('--allow-network', action='store_true')
    args = ap.parse_args(argv)
    root = args.root
    memory_path = args.memory or root / DEFAULT_PATH
    panel_path = args.panel or root / PANEL
    now = (datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)).replace(microsecond=0)
    if now.tzinfo is None:
        print(json.dumps({'status': 'REFUSED', 'reason': 'UTC_NOW_REQUIRED'}))
        return 2
    gate = exploration_gate(root, env)
    if gate['state'] != EXPLORATION_ALLOWED:
        print(json.dumps({'status': 'NOT_RUN', 'reason': gate['state'],
                          'problems': gate.get('problems', [])[:10]}, sort_keys=True))
        return 0 if gate['state'] == 'EXPLORATION_DISABLED' else 2
    try:
        dataset = build_dataset(root, now=now)
        memory = read_memory(memory_path)
        packet = llm_packet(gate, dataset, memory, gate['config']['max_llm_plans_per_call'])
        llm = None
        if args.mode == 'packet':
            print(json.dumps(packet, ensure_ascii=False, indent=1, sort_keys=True))
            return 0
        if args.mode == 'llm-response':
            from h1lab.research_llm import parse_response
            if not args.response:
                raise ValueError('RESPONSE_FILE_REQUIRED')
            llm = parse_response(args.response.read_text(encoding='utf-8'),
                                 max_plans=gate['config']['max_llm_plans_per_call'])
            llm.update(origin='LLM_RESPONSE_FILE', llm_calls=0, packet_sha256=packet['packet_sha256'])
        if args.mode == 'llm-live':
            from h1lab.research_llm import invoke_once, parse_response
            if not gate['config']['llm_live_enabled']:
                raise ValueError('LLM_LIVE_DISABLED_BY_CONFIG')
            if not args.allow_network or env.get('RESEARCH_LLM_CONFIRMATION') != LIVE_CONFIRM:
                raise ValueError('LLM_LIVE_NOT_AUTHORISED')
            account, key = env.get('CLOUDFLARE_ACCOUNT_ID', ''), env.get('MASTER_BRAIN_LLM_API_KEY', '')
            if not account or not key:
                raise ValueError('LLM_SECRET_MISSING')
            kw = {'endpoint': 'https://api.cloudflare.com/client/v4/accounts/%s/ai/v1/chat/completions' % account,
                  'model': MODEL, 'api_key': key}
            if opener is not None:
                kw['opener'] = opener
            reply = invoke_once(packet, **kw)
            llm = parse_response(reply['content'], max_plans=gate['config']['max_llm_plans_per_call'])
            llm.update(origin='LLM_LIVE', llm_calls=1, packet_sha256=packet['packet_sha256'],
                       usage=reply['usage'])
        result = run_cycle(gate=gate, dataset=dataset, memory_path=memory_path, now=now,
                           cycle_label=args.mode, llm=llm, offline_budget=args.budget)
        write_panel(panel_path, build_panel(read_memory(memory_path), gate, now=now))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({'status': 'REFUSED_OR_FAILED', 'reason': type(exc).__name__ + ': ' + str(exc)[:200]}))
        print('RESEARCH_CYCLE_FAILED', file=sys.stderr)
        return 2
    result.pop('records', None)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
