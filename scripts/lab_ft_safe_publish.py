"""Allow FT publication after an unrelated V4 *report-only* commit.

This is NOT a generic rebase escape hatch. Anything touching H1 inputs, FT,
discovery, pages, source code, workflows or an unreviewed V4 output is refused.
The caller must independently verify identical sealed FT/discovery bytes AFTER
each rebase and use a normal non-force Git push.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess

SAFE_REMOTE_REPORTS = frozenset({
    "docs/lab/golden-priority.json",
    "docs/lab/golden-report.json",
    "docs/lab/match-trajectories.json",
    "docs/lab/outcome-readiness.json",
    "docs/lab/trajectory-research.json",
    "docs/lab/v4-audit.json",
    "docs/lab/v6-falsification.json",
    "docs/lab/v6-p0-gates.json",
    "docs/lab/v6-readiness.json",
})
SHA = re.compile(r"[a-f0-9]{40}\\Z")

def checked_paths(paths):
    if not isinstance(paths, (list, tuple)) or not paths:
        raise ValueError("No independently changed remote paths")
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate remote changes")
    unsafe = sorted(set(paths) - SAFE_REMOTE_REPORTS)
    if unsafe:
        raise ValueError("FT remote advanced with relevant or unreviewed files: "
                         + ", ".join(unsafe[:15]))
    return tuple(sorted(paths))

def git(*args):
    result = subprocess.run(["git", *args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise ValueError("Cannot verify remote FT input independence")
    return result.stdout

def validate(base, head):
    if not all(isinstance(x, str) and SHA.fullmatch(x) for x in (base, head)):
        raise ValueError("Expected literal 40-digit commit SHA")
    if base == head:
        return {"status":"UNCHANGED", "changed":[], "base":base, "head":head}
    git("merge-base", "--is-ancestor", base, head)
    raw = git("diff", "--name-only", "-z", base, head)
    names = raw.decode("utf-8").split("\\0")
    checked = checked_paths([p for p in names if p])
    return {"status":"SAFE_REPORT_ONLY_REMOTE_ADVANCE", "changed":checked,
            "base":base,"head":head}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args(argv)
    result = validate(args.base,args.head)
    print("FT_STRICT_REMOTE_CHANGE_GATE",json.dumps(result,sort_keys=True))
    return result

if __name__ == "__main__":
    main()
