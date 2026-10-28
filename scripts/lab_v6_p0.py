"""Publish P0 scientific gates and one fixed-seed 10,000-null Monte Carlo suite.

No provider calls or new scheduled job. The existing V4 shadow workflow
publishes the live P0 evidence. Null simulations are generated ONLY once;
subsequent runs verify settings/source hashes and re-use immutable results.
CI re-runs all paths to verify numerical reproducibility.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from h1lab.v6_null_simulation import run as run_nulls, setting_hash, VERSION
from h1lab.v6_p0_gates import evaluate

ROOT=Path(__file__).resolve().parents[1]
NULL_FILE="docs/lab/v6-p0-null-simulation.json"
GATES_FILE="docs/lab/v6-p0-gates.json"


def encode(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)+"\n"


def source_digest():
    src=Path(__file__).resolve().parents[1]/"h1lab/v6_null_simulation.py"
    return hashlib.sha256(src.read_bytes()).hexdigest()


def validate_null(value):
    if (value.get("status") != "V6_P0_SIMULATED_NULL_NOT_EMPIRICAL_VALIDATION"
            or value.get("scientific_state") != "INCONCLUSIVO"
            or value.get("settings_sha256") != setting_hash()
            or value.get("simulation_source_sha256") != source_digest()
            or value.get("null",{}).get("paths") != 10_000
            or value.get("settings",{}).get("version") != VERSION):
        raise ValueError("P0 null experiment/version changed, do not overwrite historical result")


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,default=ROOT)
    parser.add_argument("--verify-only",action="store_true")
    parser.add_argument("--recompute-nulls",action="store_true")
    args=parser.parse_args(argv)
    root=args.root
    null_path=root/NULL_FILE
    old=json.loads(null_path.read_text(encoding="utf-8")) if null_path.exists() else None
    if old:
        validate_null(old)
    elif args.verify_only:
        raise ValueError("Missing frozen P0 simulation")
    if args.recompute_nulls or not old:
        computed=run_nulls()
        computed["simulation_source_sha256"]=source_digest()
        if old and old!=computed:
            raise ValueError("Seeded Monte Carlo does not replay identically")
        if not old and not args.verify_only:
            null_path.parent.mkdir(parents=True,exist_ok=True)
            null_path.write_text(encode(computed),encoding="utf-8")
            old=computed
    if not old:
        raise ValueError("P0 simulation missing")
    now=datetime.now(timezone.utc)
    gate_path=root/GATES_FILE
    if args.verify_only:
        if not gate_path.exists():
            raise ValueError("P0 gates are missing")
        historical=json.loads(gate_path.read_text(encoding="utf-8"))
        replay=evaluate(root,datetime.fromisoformat(historical["evaluation_clock"]))
        if replay!=historical:
            raise ValueError("P0 temporal gate replay mismatch")
        gates=historical
    else:
        gates=evaluate(root,now)
        gate_path.parent.mkdir(parents=True,exist_ok=True)
        output=encode(gates)
        if not gate_path.exists() or gate_path.read_text(encoding="utf-8")!=output:
            gate_path.write_text(output,encoding="utf-8")
    print("V6_P0", "REPLAY_OK" if args.verify_only else "SHADOW",
          "null_paths",old["null"]["paths"],
          "anytime_null_hits",old["null"]["ever_hit_at_any_look"],
          "day7",gates["gates"]["7_days"]["status"],
          "day14",gates["gates"]["14_days"]["status"],
          "ft",gates["ft_knowledge_timeline"]["latest_temporally_consistent_ft_matches"],
          "science",gates["scientific_state"])
    return {"nulls":old,"gates":gates}


if __name__=="__main__":
    main()
