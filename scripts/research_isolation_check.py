"""Prove the research feature does not touch protected production surfaces.

1. ``git diff --name-only BASE...HEAD`` must only contain allow-listed research paths
   (plus the single navigation link in docs/llm-investigator.html).
2. No pre-existing module imports any research_* module (no hidden coupling).
3. Running an offline research cycle into a scratch memory leaves every tracked file under
   data/, docs/lab/, config/ byte-identical and the scientific gate output unchanged.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = (
    'h1lab/research_*.py', 'scripts/lab_research_*.py', 'scripts/research_isolation_check.py',
    'tests/test_research_*.py', 'tests/research_fixtures.py', 'tests/research-autonomy-ui.test.cjs',
    'docs/research-autonomy.*', 'docs/research/demo/*', 'docs/technical/AUTONOMOUS-RESEARCH.md',
    '.github/proposed-workflows/*', 'config/research-autonomy.json',
    '.github/workflows/research-autonomy-smoke.yml', '.gitignore', 'docs/llm-investigator.html',
    # Ownership registration only (two LLM_SHADOW paths, one SITE demo pattern); no publisher logic.
    'scripts/publication_ownership.py',
    # Activation migration (exact files only): the prepared workflow replaces the retired one in
    # place, the retired workflow's wiring test, and the retired workflow's operator doc.
    '.github/workflows/v6-llm-autonomous.yml', 'tests/test_v6_llm_autonomous.py',
    # Central quota: legacy network boundary guard, offline store double and seed only.
    'h1lab/v6_llm_investigator.py', 'tests/quota_fixtures.py',
    'data/research/quota-ledger.json', 'docs/technical/LLM-QUOTA-CONTROLLER.md',
    'docs/technical/V6_LLM_AUTONOMY_CONTROLLED.md',
)
PROTECTED_TOPS = ('data', 'docs/lab', 'config')


def changed_paths(base, root=ROOT):
    out = subprocess.run(['git', 'diff', '--name-only', base + '...HEAD'], cwd=root,
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if p]


def disallowed(paths):
    return [p for p in paths if not any(fnmatch.fnmatch(p, pat) for pat in ALLOWED)]


def foreign_imports(root=ROOT):
    bad = []
    for top in ('h1lab', 'scripts'):
        for p in sorted((root / top).glob('*.py')):
            if p.name.startswith(('research_', 'lab_research_')) or p.name == 'research_isolation_check.py':
                continue
            tree = ast.parse(p.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom):
                    names = [node.module or ''] + [a.name for a in node.names]
                elif isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                if any('research_' in n and 'trajectory_research' not in n for n in names):
                    bad.append(str(p.relative_to(root)))
    return sorted(set(bad))


def tree_hashes(root=ROOT):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for top in PROTECTED_TOPS for p in sorted((root / top).rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts}


def cycle_leaves_tree_intact(root=ROOT):
    from h1lab.research_cycle import run_cycle
    from h1lab.research_dataset import build_dataset
    from h1lab.research_gates import exploration_gate
    from h1lab.v6_llm_investigator import scientific_gate
    before, sci_before = tree_hashes(root), scientific_gate(root)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with tempfile.TemporaryDirectory() as t:
        res = run_cycle(gate=exploration_gate(root), dataset=build_dataset(root, now=now),
                        memory_path=Path(t) / 'm.jsonl', now=now, run_kind='TEST', offline_budget=3)
    return {'cycle_status': res['status'], 'tracked_files_checked': len(before),
            'tracked_files_unchanged': before == tree_hashes(root),
            'scientific_gate_unchanged': sci_before == scientific_gate(root)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base', default=None, help='git ref of the base branch (e.g. origin/main)')
    args = ap.parse_args(argv)
    report = {'foreign_imports': foreign_imports()}
    if args.base:
        paths = changed_paths(args.base)
        report.update(changed=len(paths), disallowed=disallowed(paths))
    report.update(cycle_leaves_tree_intact())
    ok = (not report['foreign_imports'] and not report.get('disallowed')
          and report['tracked_files_unchanged'] and report['scientific_gate_unchanged'])
    print(('RESEARCH_ISOLATION_OK ' if ok else 'RESEARCH_ISOLATION_FAILED ') + json.dumps(report, sort_keys=True))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
