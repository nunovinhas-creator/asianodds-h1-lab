"""Offline activation preflight for segmented discovery-state.json.

READ-ONLY on the repository: uses an isolated temporary store and existing
builder. It neither switches the production loader nor publishes a Git pointer.
"""
import argparse
import copy
import hashlib
import json
import tempfile
from pathlib import Path

from h1lab import lab_discovery_store as store
from h1lab.discovery_timeline import build
from h1lab.discovery_public_pages import paginate, verify
from scripts.lab_discoveries import MAX_STATE_BYTES

ROOT = Path(__file__).resolve().parents[1]
INPUTS = (
    "docs/lab/pattern-research.json",
    "data/lab/pattern-watch-first-seen.json",
    "data/lab/ft-ledger.json",
)
STATE = "data/lab/discovery-state.json"
CONSUMER_EXTENSIONS = {".py", ".js", ".cjs", ".yml", ".yaml", ".sh", ".html"}


def consumers(root):
    """Enumerate potential production readers/writers to review before activation.

    This list is diagnostic, not a claimed proof that all dynamic paths have
    been found. Includes workflows and scripts, but excludes test fixtures.
    """
    seen = []
    for directory in ("h1lab", "scripts", ".github/workflows", "docs"):
        folder = root / directory
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.is_symlink() or path.suffix not in CONSUMER_EXTENSIONS:
                continue
            if "discovery-state.json" in path.read_text(encoding="utf-8", errors="replace"):
                seen.append(path.relative_to(root).as_posix())
    return sorted(set(seen))


def preflight(root=ROOT, *, stress=True):
    """Compare the legacy and segment-reconstructed state and public output."""
    root = Path(root)
    source = root / STATE
    if source.is_symlink() or not source.is_file():
        raise ValueError("Missing, symlinked or invalid discovery state")
    legacy = source.read_bytes()
    if len(legacy) > store.STATE_LIMIT:
        raise ValueError("Legacy state beyond segmented store safety limit")
    previous = store.decode(legacy)
    inputs = []
    for relative in INPUTS:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError("Missing or symlinked producer input: " + relative)
        inputs.append(store.decode(path.read_bytes()))
    with tempfile.TemporaryDirectory(prefix="discovery-activation-preflight-") as temp:
        initial = store.publish(legacy, temp, expected_generation=None)
        hydrated, recovered = store.read(temp)
        if recovered != legacy or hydrated != previous:
            raise ValueError("Segmented legacy state parity failed")
        before = build(*inputs, previous)
        after = build(*inputs, hydrated)
        if before != after:
            raise ValueError("Discovery producer semantics changed on reload")
        root_before, pages_before = paginate(before[1])
        root_after, pages_after = paginate(after[1])
        if root_before != root_after or pages_before != pages_after:
            raise ValueError("Public paged payload diverged after state reload")
        verify(root_before, pages_before)
        result = {
            "status": "PASS_OFFLINE_NOT_ACTIVATED",
            "production_migration_enabled": False,
            "legacy_bytes": len(legacy),
            "legacy_sha256": hashlib.sha256(legacy).hexdigest(),
            "legacy_cap_bytes": MAX_STATE_BYTES,
            "legacy_margin_bytes": MAX_STATE_BYTES - len(legacy),
            "initial_generation": initial["generation"],
            "initial_shards": initial["shards"],
            "public_patterns": root_before["pattern_count"],
            "public_pages": len(pages_before),
            "public_root_bytes": len(store.encode(root_before)),
            "producer_output_parity": True,
            "byte_exact_reconstruction": True,
            "consumer_inventory": consumers(root),
            "consumer_inventory_completeness": "STATIC_HEURISTIC_REQUIRES_REVIEW",
        }
        if stress:
            grown = copy.deepcopy(previous)
            # Synthetic-only growth, strictly outside productive history.
            grown["__preflight_growth_only__"] = []
            number = 0
            while len(store.encode(grown)) <= MAX_STATE_BYTES + 100_000:
                grown["__preflight_growth_only__"].append(
                    {"sequence": number, "payload": "x" * 4096})
                number += 1
            next_bytes = store.encode(grown)
            if len(next_bytes) <= MAX_STATE_BYTES:
                raise AssertionError("Stress payload never crossed 2 MB")
            second = store.publish(next_bytes, temp,
                                   expected_generation=initial["generation"])
            stress_state, stress_bytes = store.read(temp)
            if stress_bytes != next_bytes or stress_state != grown:
                raise ValueError("Over-limit segmented recovery failed")
            pointer = (Path(temp) / "CURRENT.json").read_bytes()
            restored_generation = store.rollback(
                temp, expected_pointer_sha256=store.digest(pointer))
            if restored_generation != initial["generation"] or store.read(temp)[1] != legacy:
                raise ValueError("Rollback was not byte-identical")
            result.update({
                "synthetic_growth_only": True,
                "stress_bytes": len(next_bytes),
                "stress_shards": second["shards"],
                "stress_over_legacy_cap": True,
                "rollback_exact": True,
            })
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--without-stress", action="store_true")
    args = parser.parse_args(argv)
    result = preflight(args.root, stress=not args.without_stress)
    print("DISCOVERY_SEGMENTATION_PREFLIGHT",
          json.dumps(result, sort_keys=True, ensure_ascii=False))
    return result


if __name__ == "__main__":
    main()
