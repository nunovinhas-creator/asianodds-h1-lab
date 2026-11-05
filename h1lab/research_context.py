"""Bounded, outcome-blind trajectory examples for the LLM research packet.

The model gets a few REAL pre-kickoff trajectories to reason about movement shapes
(line/price/implied-goals sequences, AH and 1X2 co-movement, timing, gaps). Rules:

* selection never reads outcomes, FT status or results: one example per structural
  bucket (message count, markets present, line moved), lowest salted hash wins;
* content is pre-kickoff only (the dataset already excludes post-kickoff messages);
* identities are pseudonymised (``ref`` = salted hash), no team names, no dates,
  no competition names (only the heuristic type), no Telegram text;
* provenance: source event ids + SHA-256 of the market files the gate verified;
* hard limits on examples, messages per example and bytes.
"""
from __future__ import annotations

import hashlib
import json

SALT = 'traj-examples-v1'
MAX_EXAMPLES = 8
MAX_MESSAGES = 10
MAX_BYTES = 16_000


def _bucket(row):
    v = row['variables']
    n = v.get('n_messages') or 0
    return ('1' if n <= 1 else '2-3' if n <= 3 else '4+',
            'AH' if v.get('ah_msgs') else '-', '1X2' if v.get('x12_msgs') else '-',
            'LINE_MOVED' if (v.get('total_line_ups') or 0) + (v.get('total_line_downs') or 0) else 'LINE_FLAT')


def _ref(key):
    return hashlib.sha256((SALT + ':' + key).encode()).hexdigest()[:12]


def _ctx(v):
    return ('CUP' if v.get('ctx_cup') else 'YOUTH_RESERVE' if v.get('ctx_youth_reserve')
            else 'LEAGUE_OTHER' if v.get('ctx_league_other') else 'UNKNOWN')


def trajectory_examples(dataset, source_sha256=None, *, k=MAX_EXAMPLES, max_messages=MAX_MESSAGES,
                        max_bytes=MAX_BYTES):
    buckets = {}
    for row in dataset['rows']:
        if not row.get('trajectory'):
            continue
        b = _bucket(row)
        h = _ref(row['match_key'])
        if b not in buckets or h < buckets[b][0]:
            buckets[b] = (h, row)
    # Prefer richer structures first (fixed order), never by outcome.
    order = sorted(buckets, key=lambda b: (-['1', '2-3', '4+'].index(b[0]), b[1] == '-', b[2] == '-', b))
    examples = []
    for b in order[:k]:
        h, row = buckets[b]
        msgs = row['trajectory']
        shown = msgs[-max_messages:]
        examples.append({
            'ref': h, 'structure': list(b), 'competition_type': _ctx(row['variables']),
            'kickoff_hour_utc': row['variables'].get('kickoff_hour_utc'),
            'messages_total': len(msgs), 'messages_shown': len(shown),
            'truncated_earliest': len(msgs) - len(shown),
            'messages': [{k2: v for k2, v in m.items() if k2 != 'event_id'} for m in shown],
            # Hashed ids: verifiable offline against the tracked files, not a lookup key.
            'provenance': {'source_event_sha256_12': [hashlib.sha256(m['event_id'].encode()).hexdigest()[:12]
                                                      for m in shown]},
        })
    while examples and len(json.dumps(examples, ensure_ascii=False).encode()) > max_bytes:
        examples.pop()
    markets = {k2: v for k2, v in (source_sha256 or {}).items() if '/markets-' in k2}
    return {'examples': examples, 'selection': 'ONE_PER_STRUCTURAL_BUCKET_LOWEST_SALTED_HASH_OUTCOME_BLIND',
            'contains': 'PRE_KICKOFF_QUOTES_ONLY_NO_OUTCOMES_NO_NAMES_NO_DATES',
            'source_files_sha256': markets, 'buckets_available': len(buckets)}
