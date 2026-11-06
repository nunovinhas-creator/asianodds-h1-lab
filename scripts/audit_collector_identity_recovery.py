"""Offline proof for recovered artifact 13486524957; never contacts a provider.

First import the saved bundle into a local evidence ref (see incident README).
Verifies the working tree against the original base and unpublished commit.
"""
import hashlib
import json
import subprocess
from pathlib import Path

from h1lab.fixture_identity import validate
from scripts.collect_publish_safe import verify_state
from scripts.lab_ft_publish_safe import stable_fixtures

BASE = '45712d02f93605ecfdafb588416121dbba22feb0'
SOURCE = '619347ede68a5395fe1e9ac44c3108300219ae48'
FOLDER = 'reports/incidents/2026-11-06-collector-identity'
VIEWS = ('data/lab/formats-2026-11.jsonl', 'data/lab/markets-2026-11.jsonl',
         'data/lab/v4-revisions-2026-11.jsonl')


def audit(root):
    root = Path(root)
    def blob(ref, name):
        return subprocess.check_output(['git', '-C', str(root), 'show', ref+':'+name])
    previous_raw = blob(BASE, 'data/state.json')
    before = json.loads(previous_raw)
    source = json.loads(blob(SOURCE, 'data/state.json'))
    current_raw = (root/'data/state.json').read_bytes()
    current = json.loads(current_raw)
    validate(current)
    verify_state(previous_raw, current_raw)
    assert stable_fixtures(previous_raw, current_raw)
    q = current['fixture_quarantine']
    assert len(q) == 1 and q[0]['event_id'] == '3571094759:53107'
    assert current['last_id'] == source['last_id'] == 53130
    old_ids = {a['event_id'] for a in before['alerts']}
    additions = [a for a in source['alerts'] if a['event_id'] not in old_ids]
    observed = {a['event_id']: a for a in current['alerts']}
    observed.update({entry['event_id']: entry['alert'] for entry in q})
    assert len(additions) == 61
    assert observed == {a['event_id']: a for a in source['alerts']}
    for field in ('signals', 'tickets', 'collector', 'diagnostics'):
        assert current[field] == source[field], field
    for path in VIEWS:
        assert (root/path).read_bytes() == blob(SOURCE, path), path
    # All old V4 lines are exact prefixes; full production replay verifies SHA chains.
    for path in VIEWS:
        assert (root/path).read_bytes().startswith(blob(BASE, path)), path
    from h1lab.v4_revisions import verify_projection
    assert verify_projection(root)
    ledger = 'data/e5-over25-notifications.json'
    assert (root/ledger).read_bytes() == blob(BASE, ledger) == blob(SOURCE, ledger)
    assert json.loads(blob(BASE, 'config/research-autonomy.json'))['llm_live_enabled'] is False
    def sha(data):
        return hashlib.sha256(data).hexdigest()
    return {'status': 'OFFLINE_RECOVERY_VERIFIED_NOT_LIVE_PROOF', 'run_id': '42181923012',
            'artifact_id': 13486524957, 'base': BASE, 'source': SOURCE,
            'match_key': q[0]['alert']['match_key'], 'last_id': current['last_id'],
            'messages_preserved': len(additions), 'admitted_new_alerts': len(additions)-len(q),
            'quarantined': len(q), 'v4_rows_preserved_per_family': 61,
            'old_alerts_unchanged': len(before['alerts']),
            'old_signals_unchanged': len(before['signals']),
            'old_tickets_unchanged': len(before['tickets']),
            'source_signals_preserved': len(current['signals']),
            'source_tickets_preserved': len(current['tickets']),
            'e5_ledger_sha256': sha((root/ledger).read_bytes()),
            'bundle_sha256': sha((root/FOLDER/'collect-unpublished.bundle').read_bytes()),
            'v4_sha256': {path: sha((root/path).read_bytes()) for path in VIEWS}}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.')
    args = parser.parse_args()
    print(json.dumps(audit(args.root), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
