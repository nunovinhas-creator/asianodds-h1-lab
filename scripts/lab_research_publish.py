"""Publisher-side verification for the active research workflow (.github/workflows/v6-llm-autonomous.yml).

Runs in a job WITHOUT LLM secrets. It accepts a candidate operational memory produced
by the discover job only if it is a byte-exact, strict extension of the memory tracked
at the publishing checkout, adds exactly one OPERATIONAL cycle with at most one real
call, and contains no validated or demonstration content. Then it writes the memory
and regenerates the panel. Any doubt fails closed (exit 2) and nothing is written.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from h1lab.research_cycle import build_panel, write_panel
from h1lab.research_gates import exploration_gate, promotion_guard
from h1lab.research_memory import MAX_BYTES, _atomic_write, _locked, _parse

ROOT = Path(__file__).resolve().parents[1]
MEMORY = 'data/research/memory.jsonl'
PANEL = 'docs/research/autonomous-research.json'
ALLOWED_EXPERIMENT_ORIGINS = ('LLM_LIVE', 'OFFLINE_PROPOSER')


def verify_extension(base_raw, cand_raw, science_gate):
    if len(cand_raw) > MAX_BYTES:
        raise ValueError('CANDIDATE_TOO_LARGE')
    if not cand_raw.startswith(base_raw):
        raise ValueError('NOT_A_STRICT_EXTENSION')
    if not cand_raw.endswith(b'\n'):
        raise ValueError('CANDIDATE_TORN_TAIL')
    base = _parse(base_raw)
    cand = _parse(cand_raw)
    new = cand[len(base):]
    if not new:
        raise ValueError('NOTHING_NEW')
    if any(r['run_kind'] != 'OPERATIONAL' for r in cand):
        raise ValueError('NON_OPERATIONAL_RECORDS')
    cycles = [r for r in new if r['record_type'] == 'CYCLE']
    if len(cycles) != 1 or new[-1]['record_type'] != 'CYCLE':
        raise ValueError('EXACTLY_ONE_CYCLE_REQUIRED')
    c = cycles[0]
    if c.get('llm_origin') not in (None, 'LLM_LIVE') or c.get('llm_calls', 0) > 1:
        raise ValueError('CYCLE_ORIGIN_OR_CALL_BUDGET_INVALID')
    for r in new:
        if r['record_type'] == 'EXPERIMENT':
            if r['origin'] not in ALLOWED_EXPERIMENT_ORIGINS:
                raise ValueError('EXPERIMENT_ORIGIN_NOT_ALLOWED')
            promotion_guard(r, science_gate)
        elif r['record_type'] == 'PLAN_REJECTED':
            if r['origin'] != 'LLM_LIVE':
                raise ValueError('REJECTION_ORIGIN_NOT_ALLOWED')
        elif r['record_type'] != 'CYCLE':
            raise ValueError('UNKNOWN_RECORD_TYPE')
    return {'base_records': len(base), 'new_records': len(new), 'llm_calls': c.get('llm_calls', 0),
            'cycle_id': c['cycle_id']}


def publish(root, candidate, *, now):
    root = Path(root)
    mem = root / MEMORY
    gate = exploration_gate(root)
    with _locked(mem):
        base_raw = mem.read_bytes() if mem.exists() else b''
        summary = verify_extension(base_raw, Path(candidate).read_bytes(),
                                   gate['scientific_validation_gate'])
        _atomic_write(mem, Path(candidate).read_bytes())
    write_panel(root / PANEL, build_panel(_parse(mem.read_bytes()), gate, now=now))
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=ROOT)
    ap.add_argument('--candidate', type=Path, required=True)
    ap.add_argument('--verify-only', action='store_true')
    args = ap.parse_args(argv)
    try:
        if args.verify_only:
            mem = args.root / MEMORY
            out = verify_extension(mem.read_bytes() if mem.exists() else b'', args.candidate.read_bytes(),
                                   exploration_gate(args.root)['scientific_validation_gate'])
        else:
            out = publish(args.root, args.candidate, now=datetime.now(timezone.utc).replace(microsecond=0))
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({'status': 'REFUSED', 'reason': type(exc).__name__ + ': ' + str(exc)[:200]}))
        return 2
    print(json.dumps(dict(out, status='VERIFIED' if args.verify_only else 'WRITTEN'), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
