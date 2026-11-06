"""Offline B1 replay. Writes only explicit output; never touches research memory.

Example: python -m scripts.lab_research_quality --source-root work/frozen --output work/b1.json
Source root must be the original run head, not a moving main checkout.
"""
import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from scripts.master_brain_a1_audit import git_read, git_object as verified_git_object
from h1lab.research_dataset import build_dataset
from h1lab.research_quality import raw_plan, sha, shadow_report
from h1lab.research_memory import _hash
from h1lab.research_plan import validate_plan


ROOT = Path(__file__).resolve().parents[1]
INPUT_COMMIT = 'ede8b771cc20a9236a0163df47ce2f6e7e915b25'
PUBLICATION_COMMIT = '58c928893f0ba95df361b3ae43c17a3ecdba53e3'
RUN_ID = 42202804803


def git_object(spec):
    if ':' in spec:
        oid = git_read(ROOT, 'rev-parse', spec).decode().strip()
        return verified_git_object(ROOT, 'blob', oid)
    return verified_git_object(ROOT, 'commit', spec)


def verify_history(proof):
    # Pinned original run, not caller-selected refs. Shallow/missing objects fail closed.
    from h1lab.research_memory import _parse
    memory = git_object(PUBLICATION_COMMIT + ':data/research/memory.jsonl')
    history = _parse(memory)
    expected = [r for r in history if r.get('cycle_id') == 'C84726a3448c725b'
                and r.get('record_type') == 'EXPERIMENT' and r.get('origin') == 'LLM_LIVE']
    if (proof['source_commit'] != PUBLICATION_COMMIT or proof['run_id'] != RUN_ID
            or proof['memory_sha256'] != hashlib.sha256(memory).hexdigest()
            or proof['records'] != expected or len(expected) != 3):
        raise ValueError('HISTORICAL_PROVENANCE_MISMATCH')
    message = git_object(PUBLICATION_COMMIT).decode()
    if str(RUN_ID) not in message:
        raise ValueError('RUN_PUBLICATION_LINK_UNPROVEN')
    git_object(INPUT_COMMIT)
    git_read(ROOT, 'merge-base', '--is-ancestor', INPUT_COMMIT, PUBLICATION_COMMIT)
    return INPUT_COMMIT, PUBLICATION_COMMIT


def write_diagnostic(name, report):
    # Only a basename; root and both directory components are opened without
    # following symlinks. Directory descriptors prevent path substitution races.
    if not isinstance(name, str) or not name.endswith('.json') or Path(name).name != name or name in ('.', '..') or '/' in name or '\\' in name:
        raise ValueError('DIAGNOSTIC_BASENAME_REQUIRED')
    fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in ('work', 'b1-diagnostics'):
            try:
                os.mkdir(component, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        with os.fdopen(out, 'w') as stream:
            stream.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n')
    finally:
        os.close(fd)


def replay(source_root, proof):
    input_commit, publication_commit = verify_history(proof)
    records = proof['records']
    for record in records:
        if _hash(record) != record['sha256']:
            raise ValueError('ORIGINAL_RECORD_HASH_MISMATCH')
        plan = raw_plan(dict(record['plan'], question=record['question'],
                             hypothesis=record['hypothesis'], null_hypothesis=record['null_hypothesis']))
        if validate_plan(plan)['fingerprint'] != record['fingerprint']:
            raise ValueError('ORIGINAL_PLAN_FINGERPRINT_MISMATCH')
    source_hashes = records[0]['data']['sources_sha256']
    for relative, expected_hash in source_hashes.items():
        path = (Path(source_root) / relative).resolve()
        if not path.is_relative_to(Path(source_root).resolve()):
            raise ValueError('SOURCE_PATH_OUTSIDE_ROOT')
        blob = git_object(input_commit + ':' + relative)
        if path.read_bytes() != blob or hashlib.sha256(blob).hexdigest() != expected_hash:
            raise ValueError('ORIGINAL_SOURCE_HASH_MISMATCH')
    now = datetime.fromisoformat(records[0]['recorded_at'])
    dataset = build_dataset(source_root, now=now)
    expected = records[0]['data']['dataset_sha256']
    if dataset['digest'] != expected:
        raise ValueError('ORIGINAL_DATASET_HASH_MISMATCH')
    metadata = []
    for row in dataset['rows']:
        # Do not inspect outcome, score, FT hash or targets. Legacy dataset carries
        # no separate per-feature freeze or FT-source provenance: leave unproven.
        metadata.append(dict({k: row[k] for k in ('match_key', 'variables', 'decision_at',
                                                  'kickoff_utc', 'source_event_ids')},
                             ft_verified=row['ft_status'] == 'VERIFIED_FT',
                             ft_source_verified=False,
                             baseline_available={k: v is not None for k, v in row['baselines'].items()}))
    plans = [raw_plan(dict(r['plan'], question=r['question'], hypothesis=r['hypothesis'],
                           null_hypothesis=r['null_hypothesis'])) for r in records]
    report = shadow_report(plans, metadata)
    report['provenance'] = {'input_commit': input_commit, 'publication_commit': publication_commit, 'run_id': proof['run_id'],
                            'original_memory_sha256': proof['memory_sha256'],
                            'verified_source_files_sha256': source_hashes,
                            'original_dataset_sha256': expected,
                            'replayed_dataset_sha256': dataset['digest'], 'proof_sha256': sha(proof)}
    report['before'] = [{'fingerprint': r['fingerprint'], 'counts': r['results']['counts'],
                         'group': r['results'].get('group'), 'control': r['results'].get('control'),
                         'state': r['state'], 'scientific_status': r['scientific_status']}
                        for r in records]
    report['limits'] = ['NO_PER_FEATURE_FREEZE_PROOF_IN_LEGACY_DATASET',
                        'NO_OUTCOME_FREE_FT_SOURCE_PROOF_IN_LEGACY_DATASET',
                        'NO_APRIORI_THRESHOLD_FREEZE_IN_LEGACY_PLAN',
                        'BEFORE_RESULTS_ARE_ORIGINAL_NOT_RECOMPUTED',
                        'NO_NEW_PREDICTIVE_SUCCESS_RATE']
    report['costs'] = {'llm_calls': 0, 'neurons': 0, 'provider_queries': 0, 'money_operations': 0}
    report['output_sha256'] = sha(report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--proof', type=Path, default=Path('evidence/b1/real-plans.json'))
    parser.add_argument('--output', required=True, help='New JSON basename under repository work/b1-diagnostics')
    args = parser.parse_args()
    report = replay(args.source_root, json.loads(args.proof.read_text()))
    write_diagnostic(args.output, report)


if __name__ == '__main__':
    main()
