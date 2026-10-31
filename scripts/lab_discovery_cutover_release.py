"""Explicit, guarded segmented-discovery release helper. Not a workflow.

No action happens by import. 'prepare' stages a complete initial generation
on an isolated or expressly authorized checkout; 'publish' refuses stale remote
state and uses only a normal, non-force, fast-forward Git push. No automatic
rebase or retries with old producer results.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from h1lab import lab_discovery_dual_state as dual
from h1lab import lab_discovery_store as store
from h1lab.lab_discovery_git_bundle import (
    PREFIX, MIRROR, seal as segment_seal, verify_against_seal,
)

DIGEST = re.compile(r"[a-f0-9]{64}\Z")
WORKFLOW = ".github/workflows/lab-ft-results.yml"
# The first live commit MUST switch producer and stage a full complete bundle;
# publishing the pointer alone would break the next legacy-only FT cycle.
DUAL_PRODUCER = "python -m scripts.lab_discoveries --state-backend dual"
STAGE_COMMAND = "python -m scripts.lab_discovery_cutover_release stage"
NO_REBASE_GATE = "DISCOVERY_SEGMENTED_NO_REBASE"
SHA = re.compile(r"[a-f0-9]{40}\Z")

class CutoverBlocked(ValueError):
    """Safety gate refused the release; do not force/retry the same payload."""


def git(root, *args):
    command = ["git", "-C", str(root), *args]
    result = subprocess.run(command, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise CutoverBlocked("Git command failed; no release performed: " + " ".join(args[:2]))
    return result.stdout.decode("utf-8", errors="strict").strip()


def commit_sha(root, name="HEAD"):
    value = git(root, "rev-parse", "--verify", name)
    if not SHA.fullmatch(value):
        raise CutoverBlocked("Malformed Git commit SHA")
    return value


def remote_sha(root, *, remote="origin", branch="main"):
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", remote):
        raise CutoverBlocked("Invalid Git remote name")
    if not re.fullmatch(r"[a-zA-Z0-9._/-]+", branch) or branch.startswith("-"):
        raise CutoverBlocked("Invalid branch name")
    output = git(root, "ls-remote", "--exit-code", remote, "refs/heads/" + branch)
    fields = output.split()
    if len(fields) != 2 or fields[1] != "refs/heads/" + branch or not SHA.fullmatch(fields[0]):
        raise CutoverBlocked("Ambiguous remote branch")
    return fields[0]


def stage_reachable(root):
    """Stage exactly verified members. Never stage locks, temp paths or orphans."""
    root = Path(root)
    legacy, mirror = dual.legacy_source(root)
    segment, recovered = store.read(root / dual.SEGMENT)
    if legacy != segment or mirror != recovered:
        raise CutoverBlocked("Legacy/segmented mismatch before staging")
    directory = root / dual.SEGMENT
    refs = ["CURRENT.json"]
    if (directory / "PREVIOUS.json").exists():
        refs.append("PREVIOUS.json")
    names = [MIRROR]
    for ref in refs:
        pointer = store.decode((directory / ref).read_bytes())
        generation = pointer["generation"]
        if not DIGEST.fullmatch(generation):
            raise CutoverBlocked("Invalid segment generation")
        folder = directory / generation
        if folder.is_symlink():
            raise CutoverBlocked("Symlinked generation")
        manifest = store.decode((folder / "manifest.json").read_bytes())
        parts = manifest["parts"]
        if not isinstance(parts, list) or len(parts) > 1000:
            raise CutoverBlocked("Invalid manifest parts")
        names.append(PREFIX + ref)
        names.append(PREFIX + generation + "/manifest.json")
        names.append(PREFIX + generation + "/legacy.json.gz")
        for part in parts:
            name = part["name"]
            if not isinstance(name, str) or not re.fullmatch(r"state-[0-9]{4}\.json", name):
                raise CutoverBlocked("Unsafe segment shard")
            names.append(PREFIX + generation + "/" + name)
    names = sorted(set(names))
    for name in names:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise CutoverBlocked("Missing or symlinked release member: " + name)
    git(root, "add", "--", *names)
    staged = set(git(root, "diff", "--cached", "--name-only").splitlines())
    if any(path not in (MIRROR, WORKFLOW) and not path.startswith(PREFIX) for path in staged):
        raise CutoverBlocked("Unrelated staged change in initial release")
    proof = segment_seal(root, ref="INDEX")
    if set(proof["sha256"]) != set(names):
        raise CutoverBlocked("Staged release members differ from exact reachable set")
    return proof


def prepare_bootstrap(root, *, expected_head, remote="origin"):
    """Only initial bootstrap, with pinned main+remote base; no commit or push."""
    root = Path(root)
    if not SHA.fullmatch(expected_head):
        raise CutoverBlocked("Expected original HEAD required")
    if commit_sha(root) != expected_head or remote_sha(root, remote=remote) != expected_head:
        raise CutoverBlocked("Local or remote main advanced: rebuild from fresh checkout")
    status = git(root, "status", "--porcelain", "--untracked-files=all",
                 "--", MIRROR, PREFIX)
    if status:
        raise CutoverBlocked("Dirty legacy or segmented inputs; refuse bootstrap")
    if (root / PREFIX / "CURRENT.json").exists():
        raise CutoverBlocked("Segmented store already bootstrapped")
    result = dual.bootstrap(root)
    proof = stage_reachable(root)
    if result["generation"] != proof["current_generation"]:
        raise CutoverBlocked("Bootstrap generation mismatch")
    return {
        "status": "STAGED_NOT_COMMITTED_NOT_PUBLISHED",
        "expected_remote_head": expected_head,
        "generation": result["generation"],
        "members": len(proof["sha256"]),
        "proof": proof,
    }


def publish_pinned_commit(root, *, expected_parent, remote="origin"):
    """Non-force remote ref CAS. A race aborts, never rebase stale FT evidence."""
    root = Path(root)
    if not SHA.fullmatch(expected_parent):
        raise CutoverBlocked("Pinned pre-release parent required")
    if commit_sha(root, "HEAD^") != expected_parent:
        raise CutoverBlocked("Release commit parent changed; rebuild")
    if remote_sha(root, remote=remote) != expected_parent:
        raise CutoverBlocked("Remote main advanced; DO NOT rebase stale discovery output")
    changed = git(root, "diff", "--name-only", expected_parent, "HEAD").splitlines()
    if (WORKFLOW not in changed or
            any(path not in (MIRROR, WORKFLOW) and not path.startswith(PREFIX)
                for path in changed)):
        raise CutoverBlocked("Initial pointer requires atomic workflow cutover; no unrelated changes")
    workflow = git(root, "show", "HEAD:" + WORKFLOW)
    if not all(marker in workflow for marker in
               (DUAL_PRODUCER, STAGE_COMMAND, NO_REBASE_GATE)):
        raise CutoverBlocked("FT workflow not safely switched to dual producer and no-rebase staging")
    proof = segment_seal(root, ref="HEAD")
    verify_against_seal(root, proof, ref="HEAD")
    # A normal Git push performs an atomic remote ref update; a concurrent
    # fast-forward to another commit makes this push non-fast-forward and fail.
    # No --force, --force-with-lease, automatic rebase or retry is permitted.
    git(root, "push", remote, "HEAD:refs/heads/main")
    published = commit_sha(root)
    actual = remote_sha(root, remote=remote)
    if actual != published:
        raise CutoverBlocked("Remote moved after our push; inspect commit ancestry")
    return {"status": "PUBLISHED_COMPLETE_BUNDLE", "commit": published,
            "generation": proof["current_generation"],
            "members": len(proof["sha256"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "stage", "verify", "publish"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--expected-head")
    parser.add_argument("--expected-parent")
    parser.add_argument("--remote", default="origin")
    args = parser.parse_args(argv)
    if args.mode == "prepare":
        if args.expected_head is None:
            parser.error("--expected-head is required for prepare")
        result = prepare_bootstrap(args.root, expected_head=args.expected_head,
                                   remote=args.remote)
    elif args.mode == "stage":
        proof = stage_reachable(args.root)
        result = {"status": "STAGED_VERIFIED_NOT_PUBLISHED", "proof": proof}
    elif args.mode == "verify":
        result = {"status": "VERIFIED_LOCAL_HEAD_NOT_PUBLISHED",
                  "proof": segment_seal(args.root, ref="HEAD")}
    else:
        if args.expected_parent is None:
            parser.error("--expected-parent is required for publish")
        result = publish_pinned_commit(args.root, expected_parent=args.expected_parent,
                                       remote=args.remote)
    print("DISCOVERY_CONTROLLED_CUTOVER", json.dumps(result, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
