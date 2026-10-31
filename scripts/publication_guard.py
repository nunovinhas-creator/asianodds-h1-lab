"""Fail-closed publication barrier for LAB bundles, including after rebase.

Optional producers may keep running for diagnostics, but no bundle is committed
unless every producer succeeded. Seal staged bytes and required snapshots; reject
truncated JSON/JSONL and any post-rebase change to those exact bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
from pathlib import Path

PRODUCERS = {
    'audit': ('v6_capture', 'v6_science_memory', 'v6_falsification', 'timeline',
              'trajectory', 'outcome', 'v4_revisions', 'v6_scientific_radar',
              'v6_weekly', 'lab_archive', 'v6_p0'),
    'ft': ('v6_ft_events', 'v6_pruning', 'research', 'v6_residual', 'prospective', 'discovery'),
}
REQUIRED = {
    'audit': tuple('docs/lab/' + name + '.json' for name in (
        'v4-audit', 'golden-candidates', 'golden-report', 'golden-priority',
        'v6-shadow', 'v6-readiness', 'v6-price-quality', 'v6-feature-coverage',
        'v6-memory', 'v6-falsification', 'match-trajectories', 'trajectory-research',
        'outcome-readiness', 'v4-revisions', 'v6-scientific-radar', 'v6-weekly-drift',
        'v6-archive-health', 'v6-p0-null-simulation', 'v6-p0-gates')),
    'ft': ('data/lab/ft-ledger.json', 'data/lab/pattern-registry.json',
           'data/lab/pattern-watch-first-seen.json', 'data/lab/discovery-state.json') +
          tuple('docs/lab/' + name + '.json' for name in (
              'ft-results', 'ft-backlog', 'ft-provider-identity', 'v6-ft-evidence',
              'v6-pruning', 'pattern-research', 'v6-residual-research', 'pattern-watch', 'discoveries')),
}

# Seal unchanged journals too: reports and replay streams form one bundle.
STREAMS = {
    'audit': ('data/lab/v6-forecasts-*.jsonl', 'data/lab/v6-memory-*.jsonl',
              'data/lab/v6-hypotheses.jsonl', 'data/lab/v6-weekly-snapshots.jsonl',
              'data/lab/v6-archive-index.json', 'data/lab/v4-runchecks.jsonl'),
    'ft': ('data/lab/v6-ft-events-*.jsonl', 'data/lab/discovery-events-*.jsonl',
           'data/lab/v6-pruning-selection-v1.json', 'data/lab/ft-*.json'),
}


def inventory(pipeline):
    return sorted(name for name in git('ls-files', '-z', '--', *STREAMS[pipeline]).decode().split('\0') if name)


def outcomes(pipeline, steps):
    if not isinstance(steps, dict):
        raise ValueError('Invalid step outcomes')
    failed = [name for name in PRODUCERS[pipeline]
              if not isinstance(steps.get(name), dict) or steps[name].get('outcome') != 'success']
    if failed:
        raise ValueError('Publication blocked; producers not successful: ' + ', '.join(failed))


def reject_constant(value):
    raise ValueError('Non-finite JSON value')


def finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('Non-finite JSON number')
    return number


def validate(name, content):
    text = content.decode('utf-8')
    if name.endswith('.json'):
        value = json.loads(text, parse_constant=reject_constant, parse_float=finite_float)
        if not isinstance(value, (dict, list)):
            raise ValueError('Invalid JSON document: ' + name)
    elif name.endswith('.jsonl'):
        if text and not text.endswith('\n'):
            raise ValueError('Unterminated journal: ' + name)
        for line in text.splitlines():
            if not isinstance(json.loads(line, parse_constant=reject_constant, parse_float=finite_float), dict):
                raise ValueError('Invalid journal event: ' + name)


def git(*args):
    return subprocess.check_output(['git', *args])


def seal(pipeline, manifest):
    changed = git('diff', '--cached', '--name-only', '-z').decode().split('\0')
    streams = inventory(pipeline)
    names = sorted(set(REQUIRED[pipeline]) | set(streams) | {name for name in changed if name})
    if pipeline == 'ft' and 'docs/lab/discoveries.json' in REQUIRED[pipeline]:
        # Seal every reachable content-addressed page with the public root in
        # the same Git commit. Old unreferenced pages may remain immutable.
        from h1lab.discovery_public_pages import verify as verify_public_pages
        root = json.loads(git('show', ':docs/lab/discoveries.json'))
        if 'pattern_pages' in root:
            descriptors = root['pattern_pages']
            if not isinstance(descriptors, list):
                raise ValueError('Invalid discovery page manifest')
            pages = {}
            for item in descriptors:
                if not isinstance(item, dict) or not isinstance(item.get('path'), str):
                    raise ValueError('Invalid discovery page path')
                relative = item['path']
                if not re.fullmatch(r'discovery-pages/[a-f0-9]{64}\.json', relative):
                    raise ValueError('Unsafe discovery page path')
                file = 'docs/lab/' + relative
                if file in pages:
                    raise ValueError('Duplicate discovery page path')
                pages[file] = git('show', ':' + file)
            verify_public_pages(root, {name[len('docs/lab/'):]: raw for name, raw in pages.items()})
            names = sorted(set(names) | set(pages))
    # Only when the Git index contains a segmented store, require all
    # reachable CURRENT/PREVIOUS members and the byte-exact legacy mirror.
    # No activation flag: legacy-only production remains unchanged.
    segmented = None
    if pipeline == 'ft':
        from h1lab.lab_discovery_git_bundle import (
            PREFIX, seal as seal_segmented)
        present = [name for name in git('ls-files', '-z', '--', PREFIX).decode().split('\0') if name]
        if present:
            if PREFIX + 'CURRENT.json' not in present:
                raise ValueError('Segmented files staged without CURRENT pointer')
            segmented = seal_segmented(Path.cwd(), ref='INDEX')
            names = sorted(set(names) | set(segmented['sha256']))
    hashes = {}
    for name in names:
        if not name.startswith(('data/lab/', 'docs/lab/')):
            raise ValueError('Unexpected staged file: ' + name)
        # Index is the prospective commit: a deleted/missing artifact fails here.
        content = git('show', ':' + name)
        validate(name, content)
        hashes[name] = hashlib.sha256(content).hexdigest()
    Path(manifest).write_text(json.dumps({'pipeline': pipeline, 'streams': streams, 'sha256': hashes, 'segmented': segmented}, sort_keys=True) + '\n')
    print('PUBLICATION_BUNDLE_SEALED', pipeline, len(hashes))


def verify(manifest):
    document = json.loads(Path(manifest).read_text())
    if inventory(document['pipeline']) != document['streams']:
        raise ValueError('Publication blocked; journal inventory changed during rebase')
    hashes = document['sha256']
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError('Missing publication seal')
    if document['pipeline'] == 'ft':
        from h1lab.lab_discovery_git_bundle import (
            PREFIX, verify_against_seal)
        current = PREFIX + 'CURRENT.json'
        committed = set(name for name in git('ls-tree', '-r', '--name-only',
                                             'HEAD', '--', PREFIX).decode().splitlines()
                        if name)
        if document.get('segmented') is None:
            if committed:
                raise ValueError('Unsealed segmented generation introduced during rebase')
        else:
            if current not in committed:
                raise ValueError('Segmented CURRENT missing after rebase')
            verify_against_seal(Path.cwd(), document['segmented'], ref='HEAD')
    for name, expected in hashes.items():
        actual = hashlib.sha256(git('show', 'HEAD:' + name)).hexdigest()
        if actual != expected:
            raise ValueError('Publication blocked; bundle changed during rebase: ' + name)
    print('PUBLICATION_BUNDLE_VERIFIED', len(hashes))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('outcomes', 'seal', 'verify'))
    parser.add_argument('--pipeline', choices=tuple(PRODUCERS))
    parser.add_argument('--manifest')
    args = parser.parse_args()
    if args.mode == 'outcomes':
        outcomes(args.pipeline, json.loads(os.environ['PUBLICATION_STEPS']))
    elif args.mode == 'seal':
        seal(args.pipeline, args.manifest)
    else:
        verify(args.manifest)


if __name__ == '__main__':
    main()
