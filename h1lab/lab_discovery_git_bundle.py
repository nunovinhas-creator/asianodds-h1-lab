"""Fail-closed Git *index/commit* proof for a future discovery segmented bundle.

Purely offline: NOT imported by a productive reader, writer, or workflow.
Call verify_bundle(ref='INDEX') on the prospective *staged* commit; call
verify_against_seal(ref='HEAD') after commit/rebase. This never creates,
pushes or activates any production pointer.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from h1lab import lab_discovery_store as store

PREFIX = "data/lab/discovery-segmented/"
MIRROR = "data/lab/discovery-state.json"
POINTER_RE = re.compile(r"[a-f0-9]{64}")
SHARD_RE = re.compile(r"state-[0-9]{4}\.json")
MAX_SHARDS = 1000
MAX_MEMBERS = 2500


def _git(repo, *args):
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False)
    if proc.returncode:
        raise ValueError("Missing or invalid Git object/index for discovery bundle")
    return proc.stdout


def _tree(repo, ref):
    if ref == "INDEX":
        output = _git(repo, "ls-files", "--stage", "-z", "--", PREFIX, MIRROR)
    elif ref == "HEAD":
        output = _git(repo, "ls-tree", "-r", "-z", "HEAD", "--", PREFIX, MIRROR)
    else:
        raise ValueError("Only INDEX or HEAD proof is permitted")
    result = {}
    for record in filter(None, output.split(b"\0")):
        try:
            metadata, name = record.split(b"\t", 1)
            mode, kind, *_ = metadata.decode("ascii").split(" ")
            name = name.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("Invalid Git tree member") from exc
        if ref == "INDEX":
            # git ls-files --stage: mode sha stage\tpath
            parts = metadata.decode("ascii").split()
            mode = parts[0]
            if len(parts) != 3 or parts[2] != "0":
                raise ValueError("Unmerged index entries in discovery bundle")
        else:
            parts = metadata.decode("ascii").split()
            if len(parts) != 3 or parts[1] != "blob":
                raise ValueError("Not a regular Git file")
            mode = parts[0]
        if mode != "100644" or name in result:
            raise ValueError("Symlink, executable or duplicate discovery object")
        result[name] = True
    if len(result) > MAX_MEMBERS:
        raise ValueError("Too many discovery Git members")
    return result


def _read(repo, ref, name, available):
    if name not in available:
        raise ValueError("Missing staged/committed discovery member: " + name)
    key = ":" + name if ref == "INDEX" else "HEAD:" + name
    raw = _git(repo, "show", key)
    if len(raw) > store.STATE_LIMIT:
        raise ValueError("Discovery member exceeds safety limit")
    return raw


def _pointer(raw):
    value = store.decode(raw)
    if (not isinstance(value, dict)
            or set(value) != {"schema_version", "generation", "manifest_sha256"}
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or any(not isinstance(value[k], str)
                   or not POINTER_RE.fullmatch(value[k])
                   for k in ("generation", "manifest_sha256"))):
        raise ValueError("Invalid discovery generation pointer")
    return value


def _members(repo, ref, *, require_mirror=True):
    available = _tree(repo, ref)
    if PREFIX + "CURRENT.json" not in available:
        raise ValueError("Missing discovery CURRENT pointer")
    if require_mirror and MIRROR not in available:
        raise ValueError("Missing durable legacy mirror")

    members = {}
    def take(name):
        if name not in members:
            members[name] = _read(repo, ref, name, available)
        return members[name]

    mirror = take(MIRROR) if require_mirror else None
    if require_mirror and len(mirror) > 2_000_000:
        raise ValueError("Verified legacy mirror exceeds existing 2 MB gate")
    legacy_object = store.decode(mirror) if require_mirror else None
    current = _pointer(take(PREFIX + "CURRENT.json"))
    previous = None
    if PREFIX + "PREVIOUS.json" in available:
        previous = _pointer(take(PREFIX + "PREVIOUS.json"))
    for ptr in (current, previous):
        if ptr is None:
            continue
        gen = ptr["generation"]
        directory = PREFIX + gen + "/"
        manifest_raw = take(directory + "manifest.json")
        if len(manifest_raw) > store.SHARD_LIMIT:
            raise ValueError("Oversized segmented manifest")
        if store.digest(manifest_raw) != ptr["manifest_sha256"]:
            raise ValueError("Segmented manifest digest mismatch")
        manifest = store.decode(manifest_raw)
        if not isinstance(manifest, dict) or not isinstance(manifest.get("parts"), list):
            raise ValueError("Invalid segmented manifest")
        if len(manifest["parts"]) > MAX_SHARDS:
            raise ValueError("Too many segmented shards")
        for part in manifest["parts"]:
            if not isinstance(part, dict):
                raise ValueError("Invalid segmented part descriptor")
            name = part.get("name")
            if not isinstance(name, str) or not SHARD_RE.fullmatch(name):
                raise ValueError("Unsafe segmented shard path")
            take(directory + name)
        take(directory + "legacy.json.gz")
    if len(members) > MAX_MEMBERS:
        raise ValueError("Too many reachable discovery members")
    with tempfile.TemporaryDirectory(prefix="discovery-git-bundle-") as tmp:
        isolated = Path(tmp)
        for name, raw in members.items():
            relative = name[len(PREFIX):] if name.startswith(PREFIX) else None
            if relative is None:
                continue
            file = isolated / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(raw)
        decoded, legacy = store.read(isolated)
        if require_mirror and (legacy != mirror or decoded != legacy_object):
            raise ValueError("Staged segmented state differs from legacy source")
        if previous is not None:
            store._verify(isolated, members[PREFIX + "PREVIOUS.json"])

    # Never let a new unverified pointer, shard, lock or temporary file ride
    # along in the same staged transaction. Immutable old generations may
    # remain in HEAD but must not change with the active publication.
    if ref == "INDEX":
        changes = _git(repo, "diff", "--cached", "--name-only", "-z").decode("utf-8").split("\0")
        # Deletion of an unreachable old generation is permitted; leaving
        # unreferenced new objects staged is not. Deleted paths are absent
        # from the prospective index but remain recoverable from Git history.
        extras = [p for p in changes if p.startswith(PREFIX)
                  and p not in members and p in available]
        if extras:
            raise ValueError("Unreachable or temporary segmented members staged")
    return members, current, previous


def seal(repo, *, ref="INDEX", require_mirror=True):
    """Return a deterministic proof of every reachable staged object."""
    members, current, previous = _members(repo, ref, require_mirror=require_mirror)
    return {
        "schema_version": 1,
        "backend": "dual" if require_mirror else "segmented",
        "current_generation": current["generation"],
        "previous_generation": previous["generation"] if previous else None,
        "sha256": {name: hashlib.sha256(raw).hexdigest()
                   for name, raw in sorted(members.items())},
    }


def verify_against_seal(repo, expected, *, ref="HEAD"):
    """Recompute the complete tree and compare it against a prior index seal."""
    if (not isinstance(expected, dict) or expected.get("schema_version") != 1
            or not isinstance(expected.get("sha256"), dict)):
        raise ValueError("Missing or malformed segmented publication seal")
    mode = expected.get("backend", "dual")
    if mode not in ("dual", "segmented"):
        raise ValueError("Unknown discovery Git seal backend")
    actual = seal(repo, ref=ref, require_mirror=(mode == "dual"))
    if actual != expected:
        raise ValueError("Discovery bundle changed after commit or rebase")
    return actual
