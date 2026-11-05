"""Two independent research contracts: EXPLORATION_GATE and SCIENTIFIC_VALIDATION_GATE.

EXPLORATION_GATE answers "is the data technically sound enough to *explore*?".
It checks integrity, schema, provenance (SHA-256), size/resource limits, JSONL
parse errors, duplicate ids and temporal coherence. It does NOT look at the
scientific coverage criteria: a 7-day gate at BELOW_99_PERCENT, WARMUP or an
INCONCLUSIVO state is reported as a *limitation*, never as a blocker.

SCIENTIFIC_VALIDATION_GATE is the pre-existing ``v6_llm_investigator.scientific_gate``
used unchanged (99% coverage, chronology, prospective sample, OOS). It is the only
authority that could ever allow promotion, and this module never relaxes it.
``promotion_guard`` makes promotion impossible for anything that only passed exploration.

Corrupt files, missing provenance or serious inconsistencies still block the
operations that depend on them. Nothing here writes files or uses the network.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .v6_llm_investigator import SOURCES as SCIENTIFIC_SOURCES, scientific_gate, strict_json

CONFIG_PATH = 'config/research-autonomy.json'
EXPLORATION_ALLOWED = 'EXPLORATION_ALLOWED'
EXPLORATION_BLOCKED = 'EXPLORATION_BLOCKED'
EXPLORATION_DISABLED = 'EXPLORATION_DISABLED'
MAX_JSON_BYTES = 20_000_000      # LAB per-file contract
MAX_STATE_BYTES = 60_000_000
DEFAULT_CONFIG = {
    'schema_version': 1, 'exploration_enabled': False, 'offline_cycle_enabled': False,
    'llm_live_enabled': False, 'max_experiments_per_cycle': 40,
    'max_llm_plans_per_call': 3, 'max_llm_calls_per_cycle': 1,
}
# Operations and the inputs each one strictly needs. A broken input blocks only
# the operations that depend on it.
OPERATION_INPUTS = {
    'odds_trajectories': ('data/state.json', 'markets'),
    'ft_outcomes': ('v6-ft-events', 'data/lab/ft-ledger.json'),
    'competition_context': ('data/state.json',),
    'scientific_context': SCIENTIFIC_SOURCES,
}


def load_config(root, env=None):
    """Kill switches. Missing/invalid config fails SAFE (everything disabled)."""
    env = os.environ if env is None else env
    path = Path(root) / CONFIG_PATH
    cfg = dict(DEFAULT_CONFIG)
    try:
        if path.is_file() and not path.is_symlink() and path.stat().st_size < 20_000:
            data = strict_json(path.read_text(encoding='utf-8'))
            if isinstance(data, dict) and data.get('schema_version') == 1:
                for k, default in DEFAULT_CONFIG.items():
                    v = data.get(k, default)
                    if type(v) is type(default):
                        cfg[k] = v
    except (OSError, ValueError, UnicodeDecodeError):
        cfg = dict(DEFAULT_CONFIG)
    if str(env.get('MASTER_BRAIN_EXPLORATION', '')).lower() in ('0', 'off', 'false', 'disabled'):
        cfg['exploration_enabled'] = False
        cfg['offline_cycle_enabled'] = False
    for k in ('max_experiments_per_cycle', 'max_llm_plans_per_call', 'max_llm_calls_per_cycle'):
        cfg[k] = max(0, min(cfg[k], {'max_experiments_per_cycle': 200,
                                     'max_llm_plans_per_call': 3,
                                     'max_llm_calls_per_cycle': 1}[k]))
    return cfg


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _check_json(root, name, limit, problems, digests):
    path = Path(root) / name
    if not path.is_file() or path.is_symlink():
        problems.append({'input': name, 'code': 'MISSING_OR_UNSAFE_FILE'})
        return None
    if path.stat().st_size > limit:
        problems.append({'input': name, 'code': 'RESOURCE_LIMIT_EXCEEDED'})
        return None
    raw = path.read_bytes()
    try:
        data = strict_json(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        problems.append({'input': name, 'code': 'CORRUPT_JSON'})
        return None
    digests[name] = _sha(raw)
    return data


def _check_jsonl_stream(root, prefix, problems, digests, *, id_key):
    from .lab_archive import monthly_paths
    try:
        paths = monthly_paths(root, prefix)
    except ValueError:
        problems.append({'input': prefix, 'code': 'ARCHIVE_SEQUENCE_INVALID'})
        return 0
    seen, count = set(), 0
    for path in paths:
        if path.is_symlink() or path.stat().st_size > MAX_JSON_BYTES:
            problems.append({'input': prefix, 'code': 'RESOURCE_LIMIT_EXCEEDED',
                             'file': path.name})
            continue
        raw = path.read_bytes()
        digests[str(path.relative_to(root))] = _sha(raw)
        for n, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line.decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                problems.append({'input': prefix, 'code': 'CORRUPT_JSONL_LINE',
                                 'file': path.name, 'line': n})
                continue
            if not isinstance(row, dict):
                problems.append({'input': prefix, 'code': 'NON_OBJECT_ROW', 'file': path.name, 'line': n})
                continue
            rid = row.get(id_key)
            if not isinstance(rid, str) or not rid:
                problems.append({'input': prefix, 'code': 'MISSING_PROVENANCE_ID',
                                 'file': path.name, 'line': n})
                continue
            if rid in seen:
                problems.append({'input': prefix, 'code': 'DUPLICATE_ID', 'file': path.name, 'line': n})
            seen.add(rid)
            count += 1
    return count


def _temporal(alerts, problems):
    """Kickoff/observation timestamps must parse; future observations are incoherent."""
    from .v6_shadow import utc
    now = datetime.now(timezone.utc)
    bad = 0
    for a in alerts:
        if not isinstance(a, dict):
            bad += 1
            continue
        obs = utc(a.get('observed_at'))
        if obs is None or obs > now:
            bad += 1
    if bad:
        problems.append({'input': 'data/state.json', 'code': 'INCOHERENT_OBSERVATION_TIME',
                         'count': bad, 'severity': 'ROW_LEVEL_EXCLUDED'})
    return bad


def scientific_validation_gate(root):
    """The existing scientific gate, unchanged. Errors are reported, not hidden."""
    try:
        result = scientific_gate(root)
        result.pop('source_sha256', None)
        return {'gate': 'SCIENTIFIC_VALIDATION_GATE', 'state': result['state'],
                'promotion_allowed': False, 'details': result,
                'meaning': ('Scientific validation is governed by the pre-existing 99% coverage, '
                            'chronology, prospective-sample and OOS criteria. Exploration never '
                            'changes them.')}
    except (ValueError, KeyError, TypeError) as exc:
        return {'gate': 'SCIENTIFIC_VALIDATION_GATE', 'state': 'SCIENTIFIC_SOURCES_INVALID',
                'promotion_allowed': False, 'error': type(exc).__name__ + ': ' + str(exc)[:160]}


def exploration_gate(root, env=None):
    """Technical soundness for exploration. Returns a dict; never raises on bad data."""
    root = Path(root)
    cfg = load_config(root, env)
    if not cfg['exploration_enabled']:
        return {'gate': 'EXPLORATION_GATE', 'state': EXPLORATION_DISABLED, 'config': cfg,
                'allowed_operations': [], 'blocked_operations': sorted(OPERATION_INPUTS),
                'problems': [], 'limitations': ['Exploration disabled by configuration.']}
    problems, digests = [], {}
    state = _check_json(root, 'data/state.json', MAX_STATE_BYTES, problems, digests)
    alerts = []
    if state is not None:
        if not isinstance(state, dict) or not isinstance(state.get('alerts'), list):
            problems.append({'input': 'data/state.json', 'code': 'SCHEMA_INVALID'})
        else:
            alerts = state['alerts']
    markets = _check_jsonl_stream(root, 'markets', problems, digests, id_key='event_id')
    ft_events = _check_jsonl_stream(root, 'v6-ft-events', problems, digests, id_key='id')
    _check_json(root, 'data/lab/ft-ledger.json', MAX_JSON_BYTES, problems, digests)
    for name in SCIENTIFIC_SOURCES:
        _check_json(root, name, 600_000, problems, digests)
    row_level = _temporal(alerts, problems) if alerts else 0
    blocking = [p for p in problems if p.get('severity') != 'ROW_LEVEL_EXCLUDED']
    blocked_ops = set()
    for op, inputs in OPERATION_INPUTS.items():
        for p in blocking:
            if any(p['input'] == i or p['input'].startswith(i) for i in inputs):
                blocked_ops.add(op)
    if not alerts and not markets:
        blocked_ops.add('odds_trajectories')
    science = scientific_validation_gate(root)
    limitations = []
    sci_state = science['state']
    if sci_state != 'AUTHORISED':
        limitations.append('Scientific validation gate is %s: exploratory findings cannot be '
                           'promoted and must be labelled exploratory.' % sci_state)
    gates = (science.get('details') or {}).get('gates') or {}
    for name, g in sorted(gates.items()):
        if g.get('status') in ('BELOW_99_PERCENT', 'WARMUP', 'INSUFFICIENT_N'):
            limitations.append('%s source coverage %s (ratio=%s): partial sample, '
                               'conclusions limited to observed games.' % (name, g.get('status'), g.get('ratio')))
    if row_level:
        limitations.append('%d H1 rows have unusable/future observation time and are excluded.' % row_level)
    core_ok = 'odds_trajectories' not in blocked_ops
    return {
        'gate': 'EXPLORATION_GATE',
        'state': EXPLORATION_ALLOWED if core_ok else EXPLORATION_BLOCKED,
        'config': cfg,
        'allowed_operations': sorted(set(OPERATION_INPUTS) - blocked_ops),
        'blocked_operations': sorted(blocked_ops),
        'problems': problems[:50], 'problem_count': len(problems),
        'counts': {'h1_alerts': len(alerts), 'v4_market_rows': markets, 'ft_events': ft_events},
        'source_sha256': digests,
        'scientific_validation_gate': science,
        'limitations': limitations,
        'meaning': ('Exploration is allowed on technically sound data even when scientific '
                    'coverage is below 99%. It produces exploratory results only.'),
    }


class PromotionForbidden(ValueError):
    """Raised whenever exploratory output would be presented as validated."""


EXPLORATORY_STATES = frozenset({
    'PROMISING_EXPLORATORY', 'NO_SUPPORT_IN_DATA', 'FALSIFIED_EXPLORATORY',
    'INCONCLUSIVE', 'INSUFFICIENT_DATA', 'PLAN_REJECTED'})


def promotion_guard(record, science_gate):
    """Only SCIENTIFIC_VALIDATION_GATE could ever validate; exploration never does.

    Any record claiming VALIDATED without a preregistered, prospective, scientifically
    authorised path raises. Returns the record's (unchanged) scientific status.
    """
    status = record.get('scientific_status')
    if status == 'EXPLORATORY_NOT_VALIDATED':
        if record.get('state') not in EXPLORATORY_STATES:
            raise PromotionForbidden('Unknown exploratory state: %r' % record.get('state'))
        return status
    if status == 'VALIDATED':
        if (science_gate.get('state') != 'AUTHORISED' or not science_gate.get('promotion_allowed')
                or not record.get('preregistration_id') or not record.get('prospective_oos')):
            raise PromotionForbidden('Exploratory output cannot be promoted to VALIDATED')
        return status
    raise PromotionForbidden('Unknown scientific status: %r' % status)
