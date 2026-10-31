"""Strict opt-in discovery-state dual adapter (productive default stays legacy).

The default producer does NOT invoke the segmented path. A future separate,
reviewed activation must stage/seal Git pointer + all shards in one commit and
supply remote optimistic concurrency checks. This module alone is NOT that
activation.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from . import lab_discovery_store as store

STATE = Path("data/lab/discovery-state.json")
SEGMENT = Path("data/lab/discovery-segmented")
LEGACY_LIMIT = 2_000_000
FORMATS = ("legacy", "dual")


def legacy_source(root):
    path = Path(root) / STATE
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or symlinked legacy discovery state")
    if path.stat().st_size > LEGACY_LIMIT:
        raise ValueError("Legacy discovery mirror exceeded 2 MB")
    raw = path.read_bytes()
    obj = store.decode(raw)
    if not isinstance(obj, dict) or obj.get("schema_version") != 1:
        raise ValueError("Invalid discovery legacy state")
    return obj, raw


def load(root, *, format="legacy"):
    """Fail closed in dual mode; never silently replace missing/corrupt shards."""
    if format not in FORMATS:
        raise ValueError("Unknown discovery state format")
    legacy, raw = legacy_source(root)
    if format == "legacy":
        return legacy
    segmented, restored = store.read(Path(root) / SEGMENT)
    if raw != restored or segmented != legacy:
        raise ValueError("Discovery state mirror/segment mismatch")
    return segmented


def current_generation(root):
    """The active generation must be intact to be used as a CAS token."""
    _, raw = store.read(Path(root) / SEGMENT)
    return store.digest(raw)


def bootstrap(root):
    """One-time isolated migration. Must NOT be called by the live workflow."""
    root = Path(root)
    _, raw = legacy_source(root)
    directory = root / SEGMENT
    if (directory / "CURRENT.json").exists():
        raise ValueError("Already bootstrapped: refuse pointer overwrite")
    if directory.is_symlink():
        raise ValueError("Symlinked segmented state store")
    new = store.publish(raw, directory, expected_generation=None)
    if store.read(directory)[1] != raw:
        raise ValueError("Segmented bootstrap verification failed")
    return new


def _mirror_replace(path, data):
    """Local atomic write; remote Git atomicity is an independent gate."""
    path = Path(path)
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent,
                                     prefix=".legacy-discovery-", delete=False) as f:
        temp = Path(f.name)
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    try:
        os.replace(temp, path)
        store._sync(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def write_dual(root, state, *, expected_generation):
    """Advance one validated generation while retaining a byte-exact mirror.

    Refuse stale writers and mirror mismatches BEFORE any modification. The
    2 MB limit remains active: this is a dual-validation phase only, not the
    later segmented-authoritative capacity release.
    """
    root = Path(root)
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise ValueError("Invalid discovery state for dual write")
    if not isinstance(expected_generation, str) or len(expected_generation) != 64:
        raise ValueError("Expected generation is required")
    load(root, format="dual")
    active = current_generation(root)
    if active != expected_generation:
        raise ValueError("Stale dual discovery writer")
    raw = store.encode(state)
    if len(raw) > LEGACY_LIMIT:
        raise ValueError("Dual mirror reached legacy 2 MB cap")
    # Preserve any existing legacy formatting? New writes use the same
    # compact canonical serializer as the old productive writer.
    directory = root / SEGMENT
    result = store.publish(raw, directory, expected_generation=active)
    # An interruption here leaves mismatch visible; a publication guard
    # must verify the complete Git index and refuse a partial commit.
    _mirror_replace(root / STATE, raw)
    load(root, format="dual")
    return result
