"""Stage and seal the complete authoritative discovery generation, never the mirror.

This command does NOT push, merge, or activate a workflow. The first cutover
must commit a pinned bootstrap generation together with the FT workflow switch.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from h1lab import lab_discovery_dual_state as dual
from h1lab import lab_discovery_store as store
from h1lab.lab_discovery_git_bundle import PREFIX, seal

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SHARD = re.compile(r"state-[0-9]{4}\.json\Z")

def git(root, *args):
    proc = subprocess.run(["git", "-C", str(root), *args],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise ValueError("Cannot stage authoritative discovery Git bundle")
    return proc.stdout

def stage(root):
    """Stage only reachable CURRENT/PREVIOUS generation members and SHA-verify INDEX."""
    root = Path(root)
    directory = root / dual.SEGMENT
    store.read(directory)  # No legacy fallback or 2 MB limit.
    names = []
    for pointer_name in ("CURRENT.json", "PREVIOUS.json"):
        path = directory / pointer_name
        if not path.exists():
            if pointer_name == "CURRENT.json":
                raise ValueError("No authoritative CURRENT")
            continue
        if not path.is_file() or path.is_symlink():
            raise ValueError("Invalid discovery pointer")
        pointer = store.decode(path.read_bytes())
        generation = pointer.get("generation")
        if not isinstance(generation, str) or not SHA256.fullmatch(generation):
            raise ValueError("Invalid generation SHA")
        folder = directory / generation
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError("Missing generation")
        manifest_raw = (folder / "manifest.json").read_bytes()
        if store.digest(manifest_raw) != pointer.get("manifest_sha256"):
            raise ValueError("Invalid generation manifest hash")
        manifest = store.decode(manifest_raw)
        parts = manifest.get("parts")
        if not isinstance(parts, list) or len(parts) > 1000:
            raise ValueError("Invalid manifest parts")
        names.extend([PREFIX + pointer_name,
                      PREFIX + generation + "/manifest.json",
                      PREFIX + generation + "/legacy.json.gz"])
        for part in parts:
            name = part.get("name") if isinstance(part, dict) else None
            if not isinstance(name, str) or not SHARD.fullmatch(name):
                raise ValueError("Invalid shard name")
            names.append(PREFIX + generation + "/" + name)
        # A PREVIOUS pointer must remain wholly recoverable.
        if pointer_name == "PREVIOUS.json":
            store._verify(directory, path.read_bytes())
    names = sorted(set(names))
    for name in names:
        member = root / name
        if not member.is_file() or member.is_symlink():
            raise ValueError("Missing/nonregular generation member: " + name)
    git(root, "add", "-f", "--", *names)
    proof = seal(root, ref="INDEX", require_mirror=False)
    if set(proof["sha256"]) != set(names):
        raise ValueError("Index does not exactly seal reachable authoritative members")
    return {"status": "STAGED_AUTHORITATIVE_NOT_PUBLISHED",
            "generation": proof["current_generation"],
            "members": len(names), "proof": proof}

def bootstrap(root):
    """Prepare ONE pinned first generation only; never invoked by FT workflow."""
    root = Path(root)
    if (root / dual.SEGMENT / "CURRENT.json").exists():
        raise ValueError("Already bootstrapped")
    _, raw = dual.legacy_source(root)
    result = store.publish(raw, root / dual.SEGMENT,
                           expected_generation=None)
    proof = stage(root)
    if result["generation"] != proof["generation"]:
        raise ValueError("Bootstrap generation changed")
    return proof

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("bootstrap", "stage", "verify"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    if args.operation == "bootstrap":
        result=bootstrap(args.root)
    elif args.operation == "stage":
        result=stage(args.root)
    else:
        proof=seal(args.root,ref="HEAD",require_mirror=False)
        result={"status":"VERIFIED_AUTHORITATIVE_HEAD","proof":proof}
    print("DISCOVERY_AUTHORITATIVE",json.dumps(result,sort_keys=True))
    return result

if __name__=="__main__":
    main()
