"""Append-only, hash-chained research memory and outcome-blind research agenda.

Every record carries ``seq``, ``prev_sha256`` and ``sha256`` (of the canonical record
without ``sha256``). Reading verifies the whole chain; any edit, deletion, reorder or
truncation in the middle fails closed. Writing only appends, under an exclusive
lock, with an atomic replace (temp file + fsync + rename) and an optimistic
``expected_tip`` check, so concurrent cycles cannot interleave or lose updates and
an interrupted write leaves the previous file intact.

Learning here is operational: the memory decides what to investigate next (novelty,
re-tests when data grew, follow-ups), it never changes model weights, scientific
criteria, frozen forecasts or any production file.

Prioritisation never reads outcome VALUES: only the availability of verified FT
(``ft_status``) and pre-kickoff variable prevalence are used, so hypotheses are not
selected by results.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from .research_dsl import canonical_json, variables_used
from .research_plan import inline

MEMORY_SCHEMA = 1
DEFAULT_PATH = 'data/research/memory.jsonl'
MAX_BYTES = 19_000_000          # below the 20 MB LAB file contract
MAX_RECORD_BYTES = 64_000
GENESIS = '0' * 64
RUN_KINDS = ('OPERATIONAL', 'DEMONSTRATION', 'TEST')
LOCK_TIMEOUT_S = 10.0


class MemoryError_(ValueError):
    pass


class MemoryConflict(MemoryError_):
    """Another writer extended the memory after this cycle read it (lost-update guard)."""


class MemoryTornTail(MemoryError_):
    """The last line has no terminating newline: an interrupted foreign write."""


def _hash(record):
    body = {k: v for k, v in record.items() if k != 'sha256'}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def _parse(raw, *, where='memory'):
    out, prev = [], GENESIS
    for n, line in enumerate(raw.decode('utf-8').split('\n')[:-1], 1):
        if not line.strip():
            raise MemoryError_('BLANK_MEMORY_LINE:%d' % n)
        try:
            rec = json.loads(line)
        except ValueError:
            raise MemoryError_('MEMORY_LINE_NOT_JSON:%d' % n) from None
        if (not isinstance(rec, dict) or rec.get('schema_version') != MEMORY_SCHEMA
                or rec.get('seq') != n or rec.get('prev_sha256') != prev
                or rec.get('sha256') != _hash(rec) or rec.get('run_kind') not in RUN_KINDS):
            raise MemoryError_('MEMORY_CHAIN_INVALID_AT_LINE:%d' % n)
        prev = rec['sha256']
        out.append(rec)
    kinds = {r['run_kind'] for r in out}
    if len(kinds) > 1:
        raise MemoryError_('MEMORY_RUN_KIND_MIXED')
    return out


def read_memory(path):
    """Strict read. Any defect fails closed; a torn tail is reported, never truncated."""
    path = Path(path)
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise MemoryError_('UNSAFE_MEMORY_PATH')
    if path.stat().st_size > MAX_BYTES:
        raise MemoryError_('MEMORY_SIZE_LIMIT_REVIEW_REQUIRED')
    raw = path.read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise MemoryTornTail('MEMORY_TORN_TAIL')
    return _parse(raw)


def tip(records):
    return records[-1]['sha256'] if records else GENESIS


@contextmanager
def _locked(path, timeout=LOCK_TIMEOUT_S):
    """Exclusive advisory lock on a sidecar file; bounded wait, then fail (no hang)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + '.lock')
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise MemoryError_('MEMORY_LOCK_TIMEOUT') from None
                time.sleep(0.02)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _atomic_write(path, data):
    """Write-to-temp, fsync, rename, fsync dir: readers see old or new, never partial."""
    path = Path(path)
    tmp = path.with_name('.%s.tmp-%d-%s' % (path.name, os.getpid(), os.urandom(4).hex()))
    try:
        with open(tmp, 'wb') as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if tmp.exists():
            tmp.unlink()


def append(path, records, *, run_kind, expected_tip=None, lock_timeout=LOCK_TIMEOUT_S):
    """Append under an exclusive lock, re-reading the chain inside the lock.

    ``expected_tip``: the last sha256 the caller based its computation on (novelty,
    multiplicity). If the memory moved meanwhile, raise MemoryConflict and write
    nothing, rather than appending results computed against a stale memory.
    """
    if run_kind not in RUN_KINDS:
        raise MemoryError_('INVALID_RUN_KIND')
    path = Path(path)
    with _locked(path, lock_timeout):
        current = read_memory(path)
        if expected_tip is not None and tip(current) != expected_tip:
            raise MemoryConflict('MEMORY_CHANGED_DURING_CYCLE')
        if current and current[0]['run_kind'] != run_kind:
            raise MemoryError_('MEMORY_RUN_KIND_MIXING_FORBIDDEN')
        prev, seq = tip(current), len(current)
        sealed, lines = [], []
        for rec in records:
            seq += 1
            r = dict(rec, schema_version=MEMORY_SCHEMA, seq=seq, prev_sha256=prev, run_kind=run_kind)
            r['sha256'] = _hash(r)
            line = json.dumps(r, sort_keys=True, ensure_ascii=False, allow_nan=False)
            if len(line.encode()) > MAX_RECORD_BYTES:
                raise MemoryError_('MEMORY_RECORD_TOO_LARGE')
            lines.append(line)
            sealed.append(r)
            prev = r['sha256']
        old = path.read_bytes() if path.exists() else b''
        data = old + ''.join(line + '\n' for line in lines).encode()
        if len(data) > MAX_BYTES:
            raise MemoryError_('MEMORY_SIZE_LIMIT_REVIEW_REQUIRED')
        _atomic_write(path, data)
    return sealed


def recover_torn_tail(path, *, lock_timeout=LOCK_TIMEOUT_S):
    """Explicit, human-invoked recovery of an interrupted foreign write.

    Only a final fragment WITHOUT newline is removed, and only if every complete line
    before it forms a valid chain. The fragment is preserved in a quarantine file.
    Mid-file corruption is never repaired.
    """
    path = Path(path)
    with _locked(path, lock_timeout):
        raw = path.read_bytes()
        if not raw or raw.endswith(b'\n'):
            return {'status': 'NOTHING_TO_RECOVER', 'records': len(read_memory(path))}
        cut = raw.rfind(b'\n') + 1
        prefix, tail = raw[:cut], raw[cut:]
        records = _parse(prefix)
        digest = hashlib.sha256(tail).hexdigest()
        quarantine = path.with_name('%s.torn-%s' % (path.name, digest[:12]))
        _atomic_write(quarantine, tail)
        _atomic_write(path, prefix)
    return {'status': 'TORN_TAIL_QUARANTINED', 'records': len(records),
            'quarantine': quarantine.name, 'tail_bytes': len(tail), 'tail_sha256': digest}


def memory_kind(records):
    return records[0]['run_kind'] if records else None


# ---------------------------------------------------------------------------
# Novelty, relations, next questions

def experiments(memory):
    return [r for r in memory if r.get('record_type') == 'EXPERIMENT']


def _vars(plan):
    expr = inline(plan['condition'], plan.get('indicators', []))
    s = variables_used(expr)
    if plan.get('control_condition'):
        s |= variables_used(inline(plan['control_condition'], plan.get('indicators', [])))
    return s


def jaccard(a, b):
    return len(a & b) / len(a | b) if a | b else 0.0


def novelty(plan, memory, dataset_digest):
    """NEW | VARIANT | RETEST_NEW_DATA | DUPLICATE, plus related ids and version."""
    same = [r for r in experiments(memory) if r['fingerprint'] == plan['fingerprint']]
    if same:
        latest = same[-1]
        if latest['data']['dataset_sha256'] == dataset_digest:
            return {'grade': 'DUPLICATE', 'related': [latest['experiment_id']],
                    'version': latest['version']}
        return {'grade': 'RETEST_NEW_DATA', 'related': [latest['experiment_id']],
                'version': latest['version'] + 1}
    mine = _vars(plan)
    related = []
    for r in experiments(memory):
        j = jaccard(mine, set(r['plan']['variables_closure']))
        if j >= 0.5 and r['plan']['outcome'] == plan['outcome']:
            related.append((j, r['experiment_id']))
    related.sort(key=lambda x: (-x[0], x[1]))
    return {'grade': 'VARIANT' if related else 'NEW',
            'related': [x[1] for x in related[:5]], 'version': 1}


def next_question(plan, result):
    """Deterministic follow-up proposed from the result (no model text)."""
    s = result['state']
    if s == 'INSUFFICIENT_DATA':
        return ('Repetir quando houver mais jogos com FT verificado: ' + ' '.join(result.get('missing', [])))[:400]
    if s == 'PROMISING_EXPLORATORY':
        return ('Pré-registar esta condição e avaliá-la apenas em jogos futuros; verificar se o efeito '
                'persiste por tipo de competição e linha.')
    if s == 'FALSIFIED_EXPLORATORY':
        failed = [k for k, v in result['checks'].items() if v == 'FAIL']
        return ('O efeito aparente falhou %s; investigar se depende de um subperíodo ou estrato '
                'específico antes de qualquer nova hipótese.' % ', '.join(failed))
    if s == 'NO_SUPPORT_IN_DATA':
        return ('Sem diferença face ao mercado; testar uma interação com outro mercado '
                '(1X2 ou AH) em vez de repetir a mesma condição.')
    return 'Acumular mais jogos e repetir; o resultado atual não distingue as explicações.'


def experiment_record(plan, result, *, origin, cycle_id, dataset, sources_sha256, now, nov):
    return {
        'record_type': 'EXPERIMENT', 'recorded_at': now.isoformat(), 'cycle_id': cycle_id,
        'hypothesis_id': plan['hypothesis_id'],
        'experiment_id': plan['hypothesis_id'] + '-v%d' % nov['version'],
        'version': nov['version'], 'fingerprint': plan['fingerprint'], 'origin': origin,
        'question': plan['question'], 'hypothesis': plan['hypothesis'],
        'null_hypothesis': plan['null_hypothesis'],
        'plan': {'market': plan['market'], 'outcome': plan['outcome'],
                 'condition': plan['condition'], 'control_condition': plan['control_condition'],
                 'indicators': plan['indicators'], 'confounders': plan['confounders'],
                 'alternative_explanations': plan['alternative_explanations'],
                 'rationale': plan.get('rationale', ''),
                 'variables_used': plan['variables_used'],
                 'variables_closure': sorted(_vars(plan)),
                 'test_version': plan['test_version']},
        'variables': {v: definition(v) for v in sorted(_vars(plan))},
        'data': {'dataset_sha256': dataset['digest'], 'dataset_version': dataset['version'],
                 'information_available_until': dataset['as_of'],
                 'decision_rule': 'Variáveis apenas de mensagens observadas antes do início',
                 'sources_sha256': sources_sha256},
        'results': {k: v for k, v in result.items() if k not in ('limitations', 'state')},
        'limitations': result.get('limitations', []),
        'state': result['state'],
        'scientific_status': result['scientific_status'],
        'novelty': nov['grade'], 'related_to': sorted(set(nov['related']) | set(plan['related_to'])),
        'next_question': next_question(plan, result),
    }


def definition(name):
    from .research_dataset import VARIABLES
    t, market, desc = VARIABLES[name]
    return {'type': t, 'market': market, 'description': desc}


def rejected_record(index, reason, *, origin, cycle_id, now):
    return {'record_type': 'PLAN_REJECTED', 'recorded_at': now.isoformat(), 'cycle_id': cycle_id,
            'origin': origin, 'plan_index': index, 'reason': reason[:200],
            'state': 'PLAN_REJECTED', 'scientific_status': 'EXPLORATORY_NOT_VALIDATED'}


# ---------------------------------------------------------------------------
# Agenda for the next cycle (outcome-blind)

def agenda(memory, dataset):
    """What to look at next, from memory + current data availability only."""
    ft_now = sum(r['ft_status'] == 'VERIFIED_FT' for r in dataset['rows'])
    items = []
    latest = {}
    for r in experiments(memory):
        latest[r['fingerprint']] = r
    for fp, r in sorted(latest.items(), key=lambda kv: kv[1]['experiment_id']):
        before = r['results'].get('verified_ft_in_dataset')
        grew = before is not None and ft_now > before
        if r['state'] in ('INSUFFICIENT_DATA', 'INCONCLUSIVE'):
            items.append({'experiment_id': r['experiment_id'], 'kind': 'RETEST_WHEN_DATA_GROWS',
                          'ready': bool(grew), 'ft_then': before, 'ft_now': ft_now,
                          'question': r['next_question']})
        elif r['state'] == 'PROMISING_EXPLORATORY':
            items.append({'experiment_id': r['experiment_id'], 'kind': 'NEEDS_PREREGISTRATION',
                          'ready': False, 'question': r['next_question']})
        elif r['state'] in ('NO_SUPPORT_IN_DATA', 'FALSIFIED_EXPLORATORY'):
            items.append({'experiment_id': r['experiment_id'], 'kind': 'EXPLORE_ALTERNATIVE',
                          'ready': True, 'question': r['next_question'],
                          'avoid_condition': canonical_json(r['plan']['condition'])[:300]})
    return items


def digest_for_llm(memory, limit=12):
    """Structured memory summary for the LLM. No free model text is fed back."""
    out = []
    for r in experiments(memory)[-limit:]:
        res = r['results']
        out.append({'experiment_id': r['experiment_id'], 'market': r['plan']['market'],
                    'outcome': r['plan']['outcome'], 'condition': r['plan']['condition'],
                    'control_condition': r['plan']['control_condition'],
                    'indicators': [{'name': i['name'], 'expr': i['expr']} for i in r['plan']['indicators']],
                    'state': r['state'], 'effect': res.get('effect'),
                    'group_n': (res.get('group') or {}).get('n'),
                    'control_n': (res.get('control') or {}).get('n'),
                    'p_value': res.get('p_value'),
                    'checks': res.get('checks'), 'next_question': r['next_question']})
    return out
