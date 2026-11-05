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
                 (attempt 1) or workflow_dispatch with RESEARCH_LLM_CONFIRMATION=INVESTIGAR_UMA_VEZ,
                 and <=4 attempts per UTC day (5 on 2026-11-05 only) by BOTH the published memory and the pre-call
                 ledger (RESEARCH_PRIOR_LLM_ATTEMPTS, from scripts/lab_research_budget.py). No retries.
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

from h1lab.research_daily_limit import daily_llm_attempt_limit
from h1lab.research_cycle import build_panel, llm_packet, run_cycle, write_panel
from h1lab.research_dataset import build_dataset
from h1lab.research_gates import EXPLORATION_ALLOWED, exploration_gate
from h1lab.research_memory import read_memory, recover_torn_tail

ROOT = Path(__file__).resolve().parents[1]
PATHS = {'OPERATIONAL': ('data/research/memory.jsonl', 'docs/research/autonomous-research.json'),
         'DEMONSTRATION': ('docs/research/demo/memory.jsonl', 'docs/research/demo/panel.json')}
LIVE_CONFIRM = 'INVESTIGAR_UMA_VEZ'
# Contract v3 model (cloudflare-docs @ abaf629): documented JSON Mode (json_schema), 24k context,
# 26,668 / 204,805 neurons per M input / output tokens. The previous 8B alias returned
# 0 valid plans in both live calls (runs 42021728675 and 42030138637).
MODEL = '@cf/meta/llama-3.3-70b-instruct-fp8-fast'
SCHEDULE = '43 1,7,13,19 * * *'        # the four existing daily opportunities, unchanged
MAX_DAILY_LIVE_CALLS = 4               # base rule; dated exception in h1lab.research_daily_limit
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
    # Two independent counters; the larger wins. Memory sees only PUBLISHED cycles; the
    # pre-call ledger (scripts/lab_research_budget.py, GitHub run history) also sees calls
    # that were made but never published (invalid reply, crash, push conflict). Missing or
    # malformed ledger -> refuse: never call without proof of the remaining daily budget.
    published = sum(c.get('llm_calls', 0) for c in memory
                    if c.get('record_type') == 'CYCLE' and c.get('llm_origin') == 'LLM_LIVE'
                    and str(c.get('recorded_at', ''))[:10] == today)
    ledger = env.get('RESEARCH_PRIOR_LLM_ATTEMPTS', '')
    if not re.fullmatch(r'[0-9]{1,3}', ledger or ''):
        raise ValueError('LIVE_LEDGER_MISSING')
    if max(published, int(ledger)) >= daily_llm_attempt_limit(today):
        raise ValueError('LIVE_DAILY_LIMIT')
    return event


def _write_audit(path, reply, model, parsed=None):
    """Bounded audit file for the workflow artifact: the exact model reply (data, never
    executed) and, once parsed, the per-plan structural verdicts. No secrets: the request
    body and headers are not written."""
    if path is None:
        return
    audit = {'schema_version': 1, 'model': model, 'response_sha256': reply.get('response_sha256'),
             'usage': reply.get('usage'), 'content': reply.get('content'),
             'parsed': None if parsed is None else {
                 'received': parsed.get('received'), 'accepted': parsed.get('accepted'),
                 'accepted_hypothesis_ids': [pl['hypothesis_id'] for pl in parsed.get('plans', [])],
                 'rejected': parsed.get('rejected', [])}}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(audit, ensure_ascii=False, indent=1, sort_keys=True)
    if len(data.encode()) > 200_000:
        raise ValueError('LLM_AUDIT_TOO_LARGE')
    path.write_text(data + '\n', encoding='utf-8')


def _write_error_audit(path, diagnostic, model):
    """Audit file for a provider HTTP error: only the bounded, redacted diagnostic."""
    if path is None:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps({'schema_version': 1, 'model': model, 'provider_error': diagnostic},
                      ensure_ascii=False, indent=1, sort_keys=True)
    path.write_text(data + '\n', encoding='utf-8')


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
    ap.add_argument('--llm-audit', type=Path, default=None,
                    help='Write the raw model reply + structural verdicts here (workflow artifact only, '
                         'outside the repository; never published to memory or Pages)')
    args = ap.parse_args(argv)

    def refuse(reason, provider_error=None):
        out = {'status': 'REFUSED_OR_FAILED', 'reason': reason}
        if provider_error is not None:
            # Bounded, redacted provider diagnostic (h1lab.research_llm.provider_error_diagnostic).
            out['provider_error'] = provider_error
            out['llm_calls'] = provider_error.get('llm_calls')
        print(json.dumps(out, sort_keys=True))
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
        from h1lab.research_llm import MODEL_PROFILES, request_overhead_bytes
        profile = MODEL_PROFILES[MODEL]
        packet = llm_packet(gate, dataset, memory, max_plans,
                            budget_bytes=profile['max_request_bytes'] - request_overhead_bytes(
                                MODEL, profile, max_plans))
        llm = None
        if args.mode == 'packet':
            print(json.dumps(packet, ensure_ascii=False, indent=1, sort_keys=True))
            return 0
        from h1lab.research_llm import (CONTRACT_VERSION, ProviderHTTPError, invoke_once, neuron_bound,
                                        neurons_from_usage, parse_response)
        guard = {'example_fingerprints': tuple(packet.get('copy_guard_fingerprints', ())),
                 'copied_expressions': tuple(packet.get('copy_guard_expressions', ()))}
        if args.llm_audit and args.llm_audit.resolve().is_relative_to(root.resolve()):
            raise ValueError('LLM_AUDIT_PATH_MUST_BE_OUTSIDE_REPOSITORY')
        if args.mode == 'llm-response':
            if not args.response:
                raise ValueError('RESPONSE_FILE_REQUIRED')
            llm = parse_response(args.response.read_text(encoding='utf-8'), max_plans=max_plans, **guard)
            llm.update(origin='RESPONSE_FILE_NOT_LIVE_LLM', llm_calls=0,
                       packet_sha256=packet['packet_sha256'], model='RESPONSE_FILE',
                       contract_version=CONTRACT_VERSION)
        elif args.mode == 'llm-simulated':
            from h1lab.research_simulated_llm import ORIGIN, SimulatedLLMOpener
            sim = SimulatedLLMOpener()
            reply = invoke_once(packet, endpoint='https://simulated-llm.invalid/ai/run/SIMULATED',
                                model='SIMULATED', opener=sim, endpoint_kind='native',
                                json_mode=profile['json_mode'], max_plans=max_plans)
            _write_audit(args.llm_audit, reply, 'SIMULATED')
            llm = parse_response(reply['content'], max_plans=max_plans, **guard)
            # Simulated replies are not provider calls: llm_calls stays 0.
            llm.update(origin=ORIGIN, llm_calls=0, simulated_requests=len(sim.calls),
                       packet_sha256=packet['packet_sha256'], model='SIMULATED',
                       response_sha256=reply.get('response_sha256'), contract_version=CONTRACT_VERSION,
                       json_mode=profile['json_mode'])
            _write_audit(args.llm_audit, reply, 'SIMULATED', llm)
        elif args.mode == 'llm-live':
            if args.now:
                raise ValueError('LIVE_NOW_OVERRIDE_FORBIDDEN')   # the daily budget uses real UTC time
            if not gate['config']['llm_live_enabled']:
                raise ValueError('LLM_LIVE_DISABLED_BY_CONFIG')
            if not args.allow_network:
                raise ValueError('LLM_LIVE_NOT_AUTHORISED')
            live_authorisation(env, memory, now.date().isoformat())
            account, key = env.get('CLOUDFLARE_ACCOUNT_ID', ''), env.get('MASTER_BRAIN_LLM_API_KEY', '')
            if not re.fullmatch(r'[a-fA-F0-9]{32}', account) or not key:
                raise ValueError('LLM_SECRET_MISSING')
            base = 'https://api.cloudflare.com/client/v4/accounts/%s/ai/' % account
            kw = {'endpoint': base + ('run/' + MODEL if profile['endpoint'] == 'native' else 'v1/chat/completions'),
                  'model': MODEL, 'api_key': key, 'endpoint_kind': profile['endpoint'],
                  'json_mode': profile['json_mode'], 'max_request_bytes': profile['max_request_bytes'],
                  'max_plans': max_plans}
            if opener is not None:
                kw['opener'] = opener
            # Worst-case neurons BEFORE the request (fail closed): body size, context window,
            # per-call cap and daily budget given the attempts already counted by the ledger.
            from h1lab.research_llm import request_body
            body_len = len(request_body(packet, MODEL, endpoint_kind=profile['endpoint'],
                                        json_mode=profile['json_mode'], max_plans=max_plans))
            bound = neuron_bound(MODEL, body_len, prior_calls_today=int(env['RESEARCH_PRIOR_LLM_ATTEMPTS']))
            try:
                reply = invoke_once(packet, **kw)   # exactly one request; any failure aborts
            except ProviderHTTPError as exc:
                _write_error_audit(args.llm_audit, exc.diagnostic, MODEL)
                raise
            # Raw reply saved BEFORE parsing, so even an unparseable answer can be audited.
            _write_audit(args.llm_audit, reply, MODEL)
            llm = parse_response(reply['content'], max_plans=max_plans, **guard)
            llm.update(origin='LLM_LIVE', llm_calls=1, packet_sha256=packet['packet_sha256'],
                       usage=reply['usage'], model=MODEL, response_sha256=reply.get('response_sha256'),
                       contract_version=CONTRACT_VERSION, json_mode=profile['json_mode'],
                       neurons_bound=bound['neurons_max'],
                       neurons_from_tokens=neurons_from_usage(MODEL, reply['usage'].get('tokens')))
            _write_audit(args.llm_audit, reply, MODEL, llm)
        result = run_cycle(gate=gate, dataset=dataset, memory_path=memory_path, now=now,
                           run_kind=args.run_kind, cycle_label=args.mode, llm=llm,
                           offline_budget=args.budget)
        if result['status'] == 'RUN':
            write_panel(panel_path, build_panel(read_memory(memory_path), gate, now=now))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return refuse(type(exc).__name__ + ': ' + str(exc)[:200], getattr(exc, 'diagnostic', None))
    result.pop('records', None)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result['status'] in ('RUN', 'NOT_RUN') else 2


if __name__ == '__main__':
    raise SystemExit(main())
