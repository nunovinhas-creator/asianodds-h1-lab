"""Classify the V6 scientific gate for a workflow step, without network or writes.

Prints one JSON line and, with --github-output, writes ``state=AUTHORISED`` or
``state=SCIENTIFICALLY_BLOCKED`` to $GITHUB_OUTPUT. Unknown, accepted or corrupt gate
states raise (non-zero exit): they are errors, never a quiet skip.

``--verify-blocked`` additionally proves, on a SCIENTIFICALLY_BLOCKED snapshot, that the
production offline build refuses with ScientificGateBlocked, leaves every tracked data/report
file byte-identical, and that no evaluation is produced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from h1lab.v6_llm_investigator import ScientificGateBlocked, scientific_gate


def _hashes(root):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for top in ('data', 'docs/lab') for p in sorted((root / top).rglob('*')) if p.is_file()}


def verify_blocked(root):
    """The real build must refuse as blocked and write nothing; anything else is an error."""
    from h1lab.v6_offline_statistics import build
    before = _hashes(root)
    try:
        build(root, now=datetime.now(timezone.utc).replace(microsecond=0))
    except ScientificGateBlocked:
        pass
    else:
        raise SystemExit('V6_GATE_INCONSISTENT: offline build ran on a SCIENTIFICALLY_BLOCKED gate')
    if _hashes(root) != before:
        raise SystemExit('V6_GATE_INCONSISTENT: blocked build changed tracked files')
    return {'build_refused': 'ScientificGateBlocked', 'files_unchanged': len(before),
            'evaluation_performed': False, 'publishable_report': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--github-output', action='store_true')
    parser.add_argument('--verify-blocked', action='store_true')
    args = parser.parse_args(argv)
    result = scientific_gate(args.root)
    result.pop('source_sha256', None)
    if args.verify_blocked:
        if result['state'] != 'SCIENTIFICALLY_BLOCKED':
            raise SystemExit('V6_GATE_INCONSISTENT: --verify-blocked on state ' + result['state'])
        result['integrity'] = verify_blocked(args.root)
    print('V6_SCIENTIFIC_GATE', json.dumps(result, sort_keys=True))
    if args.github_output:
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as out:
            out.write('state=%s\n' % result['state'])
    return result


if __name__ == '__main__':
    main()
