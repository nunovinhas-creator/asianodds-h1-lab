"""Tracked-code inventory and fail-closed known-consumer list for discovery.

Audits all tracked runtime code and Actions YAML, not just guessed filenames.
Dynamic path construction still requires manual review; a static search alone
is not proof of complete coverage.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

MARKERS = re.compile(r"discovery-state\.json|discovery-segmented|lab_discoveries(?:\.py|\b)|lab_discovery_dual_state", re.I)
CODE_EXTENSIONS = {".py", ".js", ".cjs", ".yml", ".yaml", ".sh", ".html"}
RUNTIME_DIRS = ("scripts/", "h1lab/", ".github/workflows/", "docs/")
APPROVED = {
    ".github/workflows/lab-ft-results.yml": "dual-workflow-and-publication",
    "scripts/lab_discoveries.py": "only-production-discovery-producer",
    "h1lab/lab_discovery_dual_state.py": "verified-dual-loader-and-legacy-mirror",
    "h1lab/lab_discovery_git_bundle.py": "git-immutable-members-and-mirror",
    "scripts/publication_guard.py": "git-index-seal-and-head-verifier",
    "scripts/lab_discovery_cutover_release.py": "pinned-bootstrap-and-segment-staging",
    "scripts/lab_discovery_ft_activation.py": "live-preflight-pinned-push-and-rollback",
    "scripts/lab_discovery_consumer_audit.py": "static-every-file-reader-inventory",
    "scripts/lab_discovery_activation_preflight.py": "read-only-migration-rehearsal",
    "scripts/lab_discovery_migration_trial.py": "offline-only-old-migration-prototype",
    "h1lab/lab_discovery_store.py": "standalone-segmented-storage-library",
    "h1lab/lab_discovery_snapshot_trial.py": "offline-snapshot-trial",
    "h1lab/lab_discovery_partition_trial.py": "offline-partition-trial",
    "docs/lab.html": "public-ui-only",
    "docs/lab-research.html": "public-ui-only",
    "docs/llm-discovery-plan.js": "public-ui-only",
}


def inventory(root: Path):
    root = Path(root)
    listed = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"]).decode().split("\0")
    matches = {}
    for name in sorted(set(listed)):
        if (not name or not name.startswith(RUNTIME_DIRS)
                or Path(name).suffix not in CODE_EXTENSIONS):
            continue
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("Missing/symlinked tracked runtime source: " + name)
        lines = [(number, line.strip()) for number, line in
                 enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
                 if MARKERS.search(line)]
        if lines:
            matches[name] = [number for number, _ in lines]
    return matches


def verify(root: Path):
    found = inventory(root)
    unreviewed = sorted(set(found) - set(APPROVED))
    if unreviewed:
        raise ValueError("Unreviewed discovery-state reader/writer: "
                         + ", ".join(unreviewed))
    required = {
        ".github/workflows/lab-ft-results.yml",
        "scripts/lab_discoveries.py",
        "h1lab/lab_discovery_dual_state.py",
        "scripts/lab_discovery_ft_activation.py",
        "scripts/publication_guard.py",
    }
    if not required.issubset(found):
        raise ValueError("Required dual reader/writer not found: "
                         + repr(sorted(required-set(found))))
    workflow = (Path(root) / ".github/workflows/lab-ft-results.yml").read_text()
    if ("python -m scripts.lab_discoveries --state-backend dual" not in workflow
            or "python -m scripts.lab_discovery_cutover_release stage" not in workflow
            or "DISCOVERY_SEGMENTED_NO_REBASE" not in workflow):
        raise ValueError("Unprotected discovery workflow migration")
    return {"classification": "STATIC_TRACKED_CODE_NOT_DYNAMIC_PROOF",
            "matched_files": {name: {"lines": lines,
                                     "role": APPROVED[name]}
                              for name, lines in found.items()},
            "unknown_files": [], "known_runtime_references": len(found)}


if __name__ == "__main__":
    print("DISCOVERY_READERS_AUDIT",
          json.dumps(verify(Path(__file__).resolve().parents[1]), sort_keys=True))
