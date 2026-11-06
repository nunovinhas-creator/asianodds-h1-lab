"""Offline B1 replay. Writes only explicit output; never touches research memory.

Example: python -m scripts.lab_research_quality --source-root work/frozen --output work/b1.json
Source root must be the original run head, not a moving main checkout.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

from h1lab.research_dataset import build_dataset
from h1lab.research_quality import raw_plan, sha, shadow_report


def replay(source_root, proof):
    records = proof['records']
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
    report['provenance'] = {'source_commit': proof['source_commit'], 'run_id': proof['run_id'],
                            'original_memory_sha256': proof['memory_sha256'],
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
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(Path('data').resolve()) or args.output.resolve().is_relative_to(Path('docs').resolve()):
        parser.error('B1_OUTPUT_MUST_NOT_BE_OPERATIONAL_OR_PAGES')
    report = replay(args.source_root, json.loads(args.proof.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
