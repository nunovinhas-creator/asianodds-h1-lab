"""Cutover gates for actual FT dual-mode workflows. No autonomous activation.

The FT publication uses a strict remote-parent check and an ordinary Git
fast-forward push. A concurrent writer must force a fresh FT recomputation,
never rebase a stale result produced from an obsolete ledger.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from h1lab import lab_discovery_dual_state as dual
from h1lab import lab_discovery_store as store
from h1lab.lab_ft_final_guard import snapshot_file, verify_files
from h1lab.lab_discovery_git_bundle import seal as segment_seal
from scripts.lab_discovery_cutover_release import (
    CutoverBlocked, git, commit_sha, remote_sha, stage_reachable,
)
from scripts import publication_guard


def preflight(root, baseline_file):
    root = Path(root)
    # No fallback: the first productive cutover MUST already have a complete
    # Git-committed segmented CURRENT and an exact legacy mirror.
    source = dual.load(root, format="dual")
    if source.get("schema_version") != 1:
        raise CutoverBlocked("Wrong discovery state schema")
    generation = dual.current_generation(root)
    baseline = snapshot_file(root / "data/lab/ft-ledger.json", baseline_file)
    return {"state_backend": "dual", "generation": generation,
            "prior_final": baseline["final_count"],
            "ft_sha256": baseline["ft_sha256"]}


def publish_ft(root, expected_parent, manifest, *, remote="origin"):
    root = Path(root)
    # Check everything on the prepared FT commit, including the CURRENT,
    # previous generation, legacy mirror, public pages and FT ledger.
    if commit_sha(root, "HEAD^") != expected_parent:
        raise CutoverBlocked("FT parent changed; rerun full reconciliation")
    publication_guard.verify(manifest)
    segment_seal(root, ref="HEAD")
    if remote_sha(root, remote=remote) != expected_parent:
        raise CutoverBlocked("FT_REMOTE_CONFLICT: rerun whole FT cycle on fresh main")
    # No remote retry/rebase/force; a race after ls-remote is rejected by Git.
    git(root, "push", remote, "HEAD:refs/heads/main")
    published = commit_sha(root)
    if remote_sha(root, remote=remote) != published:
        raise CutoverBlocked("Remote ref drift after FT push")
    return {"status": "FT_PUBLISHED_DUAL", "head": published}


def rollback_local(root, *, expected_current_sha256, crash_hook=lambda stage: None):
    """Explicit recovery of CURRENT and legacy mirror under ONE lock.

    This is a *local preparation*, not an autonomous remote rollback. The
    caller must stage/commit both updated objects with stage_reachable()
    and run a normal guarded Git push. An interruption remains detectably
    inconsistent and MUST block publication until manually reconciled.
    """
    root = Path(root)
    folder = root / dual.SEGMENT
    with store._lock(folder) as locked:
        current = store._read(locked, "CURRENT.json")
        if store.digest(current) != expected_current_sha256:
            raise CutoverBlocked("Rollback CURRENT CAS mismatch")
        # Never roll back a corrupt active object without explicit separate
        # recovery. Never use the previous pointer as silent fallback.
        _, existing = store._verify(locked, current)
        _, mirrored = dual.legacy_source(root)
        if existing != mirrored:
            raise CutoverBlocked("Active mirror and CURRENT already diverged")
        previous = store._read(locked, "PREVIOUS.json")
        previous_object, previous_bytes = store._verify(locked, previous)
        if previous_bytes == existing:
            raise CutoverBlocked("No distinct previous generation for rollback")
        crash_hook("before_mirror")
        dual._mirror_replace(root / dual.STATE, previous_bytes)
        crash_hook("mirror_written")
        store._replace(locked, "CURRENT.json", previous)
        crash_hook("pointer_written")
        store._replace(locked, "PREVIOUS.json", current)
        crash_hook("previous_swapped")
    dual.load(root, format="dual")
    # SHA-verified staged proof is checked by the release workflow separately.
    return {"status": "ROLLBACK_PREPARED_NOT_PUBLISHED",
            "previous_generation": store.decode(previous)["generation"],
            "snapshot_sha256": store.digest(previous_bytes)}


def publish_rollback(root, expected_parent, *, remote="origin"):
    """Push a prepared paired rollback with an exact remote-parent gate.

    Only mirror and CURRENT/PREVIOUS are allowed to change. Ledger and all
    unrelated FT/H1 files must be byte-identical to the parent commit.
    """
    root = Path(root)
    if commit_sha(root, "HEAD^") != expected_parent:
        raise CutoverBlocked("Rollback commit parent is stale")
    changed = set(git(root, "diff", "--name-only", expected_parent, "HEAD").splitlines())
    allowed = {"data/lab/discovery-state.json",
               "data/lab/discovery-segmented/CURRENT.json",
               "data/lab/discovery-segmented/PREVIOUS.json"}
    if not {"data/lab/discovery-state.json",
            "data/lab/discovery-segmented/CURRENT.json"}.issubset(changed):
        raise CutoverBlocked("Incomplete paired rollback")
    if not changed.issubset(allowed):
        raise CutoverBlocked("Rollback changed unrelated FT or H1 artifact")
    dual.load(root, format="dual")
    segment_seal(root, ref="HEAD")
    if remote_sha(root, remote=remote) != expected_parent:
        raise CutoverBlocked("Rollback remote conflict; revalidate against latest main")
    git(root, "push", remote, "HEAD:refs/heads/main")
    published = commit_sha(root)
    if remote_sha(root, remote=remote) != published:
        raise CutoverBlocked("Rollback push remote verification failed")
    return {"status": "ROLLBACK_PAIR_PUBLISHED", "commit": published}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "ft-check", "ft-publish",
                                          "rollback-publish"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--baseline")
    parser.add_argument("--manifest")
    parser.add_argument("--expected-parent")
    args = parser.parse_args(argv)
    if args.mode == "preflight":
        if not args.baseline:
            parser.error("--baseline is required")
        result = preflight(args.root, args.baseline)
    elif args.mode == "ft-check":
        if not args.baseline:
            parser.error("--baseline is required")
        result = verify_files(args.baseline, args.root / "data/lab/ft-ledger.json")
    elif args.mode == "ft-publish":
        if not args.manifest or not args.expected_parent:
            parser.error("--manifest and --expected-parent required")
        result = publish_ft(args.root, args.expected_parent, args.manifest)
    else:
        if not args.expected_parent:
            parser.error("--expected-parent required")
        result = publish_rollback(args.root, args.expected_parent)
    print("DISCOVERY_DUAL_FT_GATE", json.dumps(result, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
