"""Immutable FT FINAL baselines for controlled discovery cutover.

No score is invented, revised or inferred. A candidate cannot downgrade,
remove, re-identify, or alter a previously certified FINAL match.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

FIELDS = ("status", "home", "away", "kickoff_utc", "result")


def _no_duplicate_keys(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ValueError("Duplicate FT JSON key: " + key)
        out[key] = value
    return out


def _strict_json(raw):
    return json.loads(raw, object_pairs_hook=_no_duplicate_keys,
                      parse_constant=lambda _: (_ for _ in ()).throw(
                          ValueError("Nonfinite FT JSON")))


def final_snapshot(raw):
    doc = _strict_json(raw)
    if not isinstance(doc, dict) or doc.get("schema_version") != 1:
        raise ValueError("Invalid FT ledger schema")
    matches = doc.get("matches")
    if not isinstance(matches, dict):
        raise ValueError("Invalid FT ledger matches")
    finals = {}
    for key, row in matches.items():
        if not isinstance(key, str) or not isinstance(row, dict):
            raise ValueError("Invalid FT match key/record")
        if row.get("status") == "FINAL":
            value = {field: row.get(field) for field in FIELDS}
            if (not isinstance(value["result"], dict)
                    or type(value["result"].get("home_goals")) is not int
                    or type(value["result"].get("away_goals")) is not int
                    or value["result"]["home_goals"] < 0
                    or value["result"]["away_goals"] < 0):
                raise ValueError("Invalid historical FINAL score")
            finals[key] = value
    return {
        "schema_version": 1,
        "ft_sha256": hashlib.sha256(raw).hexdigest(),
        "final_count": len(finals),
        "final_records": finals,
    }


def verify_preserved(baseline, candidate_raw):
    if (not isinstance(baseline, dict) or baseline.get("schema_version") != 1
            or not isinstance(baseline.get("final_records"), dict)):
        raise ValueError("Invalid immutable FINAL baseline")
    current = final_snapshot(candidate_raw)
    prior = baseline["final_records"]
    lost = sorted(k for k in prior if k not in current["final_records"])
    changed = sorted(k for k, value in prior.items()
                     if k in current["final_records"]
                     and current["final_records"][k] != value)
    if lost or changed:
        raise ValueError("Previously certified FT FINAL altered or lost: "
                         + str({"lost": lost[:4], "changed": changed[:4],
                                "lost_count": len(lost), "changed_count": len(changed)}))
    return {"baseline_final_count": len(prior),
            "candidate_final_count": current["final_count"],
            "new_final_count": current["final_count"] - len(prior),
            "previous_final_unchanged": True}


def snapshot_file(path, destination):
    path, destination = Path(path), Path(destination)
    if not path.is_file() or path.is_symlink() or destination.exists():
        raise ValueError("Missing/symlinked FT source or existing FT baseline")
    baseline = final_snapshot(path.read_bytes())
    # The baseline includes match keys, certified FT scores and identity.
    # Keep it outside Git, in the runner's ephemeral directory.
    destination.write_text(json.dumps(baseline, sort_keys=True) + "\n")
    return baseline


def verify_files(baseline_path, candidate_path):
    baseline = _strict_json(Path(baseline_path).read_bytes())
    return verify_preserved(baseline, Path(candidate_path).read_bytes())
