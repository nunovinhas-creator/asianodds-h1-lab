"""Deterministic shadow queue. No network, outcomes, fitting or promotion."""
from __future__ import annotations

import hashlib
from itertools import combinations
import json
from pathlib import Path

from h1lab.v6_llm_investigator import build_packet, strict_json


def candidate_id(codes):
    identity = {'version': 1, 'feature_codes': sorted(codes),
                'outcome': 'OVER_2_5', 'baseline': 'MARKET_MODEL_OVER25'}
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def plan(root, *, limit=20):
    """Enumerate one feature per family, skipping ALL published archives.

    Order is hash-based, independent of outcome and catalogue insertion order.
    An archive is evidence of a prior proposal, never evidence of a test.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('INVALID_QUEUE_LIMIT')
    packet = build_packet(root)
    archive = Path(root) / 'docs/lab/llm-investigator-runs'
    seen = set()
    archive_hashes = {}
    if archive.is_symlink():
        raise ValueError('UNSAFE_DISCOVERY_ARCHIVE')
    paths = sorted(archive.glob('*.json'))
    if len(paths) > 10_000:
        raise ValueError('DISCOVERY_ARCHIVE_REQUIRES_REVIEW')
    for path in paths:
        if path.is_symlink() or path.stat().st_size > 80_000:
            raise ValueError('UNSAFE_DISCOVERY_ARCHIVE')
        raw = path.read_bytes()
        report = strict_json(raw.decode('utf-8'))
        if (not isinstance(report, dict) or report.get('schema_version') != 1
                or report.get('state') != 'SHADOW_DRAFT_NOT_EMPIRICALLY_VALIDATED'
                or not isinstance(report.get('proposals'), list) or not report['proposals']):
            raise ValueError('INVALID_DISCOVERY_ARCHIVE')
        archive_hashes[path.name] = hashlib.sha256(raw).hexdigest()
        for proposal in report['proposals']:
            codes = proposal.get('feature_codes') if isinstance(proposal, dict) else None
            if (not isinstance(codes, list) or not 2 <= len(codes) <= 3
                    or any(not isinstance(c, str) for c in codes) or len(set(codes)) != len(codes)
                    or proposal.get('outcome') != 'OVER_2_5'
                    or proposal.get('baseline') != 'MARKET_MODEL_OVER25'):
                raise ValueError('INVALID_ARCHIVED_COMBINATION')
            seen.add(candidate_id(codes))
    candidates = []
    counts = {}
    for size in (2, 3):
        count = 0
        for features in combinations(packet['feature_catalogue'], size):
            if len({f['family'] for f in features}) != size:
                continue
            count += 1
            codes = sorted(f['code'] for f in features)
            cid = candidate_id(codes)
            if cid not in seen:
                candidates.append({'candidate_id': cid, 'feature_codes': codes,
                    'state': 'UNPROPOSED_NOT_TESTED',
                    'outcome': 'OVER_2_5', 'baseline': 'MARKET_MODEL_OVER25'})
        counts[str(size)] = count
    candidates.sort(key=lambda x: x['candidate_id'])
    return {'schema_version': 1, 'state': 'OFFLINE_QUEUE_NOT_SCIENTIFIC_EVIDENCE',
        'source_sha256': packet['source_sha256'], 'archive_sha256': archive_hashes,
        'distinct_family_space': counts, 'remaining': len(candidates),
        'previously_proposed_unique': len(seen), 'queue': candidates[:limit],
        'ordering': 'CANONICAL_HASH_NO_OUTCOMES_NO_ROI',
        'blocked_on': ['Human preregistration and V6 gates',
            'Verified pre-kickoff match-level data and FT knowledge times',
            'Temporal holdout, multiple-testing protocol and market baseline comparison'],
        'llm_calls': 0, 'empirical_tests_performed': 0}
