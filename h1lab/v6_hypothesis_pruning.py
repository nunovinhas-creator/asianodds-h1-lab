"""V6.2 P2#13. Outcome-blind reduction of a frozen V5 exploratory catalogue.

No full-time (FT), outcome, residual, p-value, ROI or bet data are read.
Only the 800 original definitions and historical pre-KO pattern incidence are
used. The first selected incidence universe is frozen; future runs replay it.
"""
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from .pattern_engine import build_features, holds, hypothesis_id, complexity
from .pattern_features import FEATURE_VERSION, PATTERNS
from .timeline import read_sources, collect_timelines

CATALOG = "data/lab/v6-pruning-catalog-v1.json"
FROZEN = "data/lab/v6-pruning-selection-v1.json"
REPORT = "docs/lab/v6-pruning.json"
STATUS = "V6_EXPLORATORY_PODA_NOT_VALIDATED"
CAP = 300


def sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def catalog_read(root):
    doc = json.loads((Path(root) / CATALOG).read_text(encoding="utf-8"))
    items = doc["definitions"]
    if (doc["schema_version"] != 1 or doc["feature_version"] != FEATURE_VERSION or
            len(items) != 800 or len({x["id"] for x in items}) != 800):
        raise ValueError("V5 catalogue version or size invalid")
    for item in items:
        if hypothesis_id(item["definition"], feature_version=FEATURE_VERSION) != item["id"]:
            raise ValueError("V5 definition hash changed: " + item["id"])
    return doc


def incidence(root, catalog):
    alerts, v4, errors = read_sources(Path(root))
    timelines, _, _ = collect_timelines(alerts, v4, source_errors=errors)
    features, _, _ = build_features(timelines, cache=None)
    feats = sorted((f for f in features if not f.get("excluded")), key=lambda x: x["match_key"])
    keys = [f["match_key"] for f in feats]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate match keys")
    masks = [sum(1 << k for k, f in enumerate(feats) if holds(h["definition"], f))
             for h in catalog["definitions"]]
    return keys, masks


def family(defn):
    op = defn["op"]
    keys = ([defn["a"]] if op == "HAS" else
            [defn["first"], defn["then"]] if op == "BEFORE" else
            list(defn.get("all", ())) + list(defn.get("none", ())))
    return op + "|" + ",".join(sorted({PATTERNS[p][1] for p in keys}))


def phi(a, b, n, na=None, nb=None):
    na = a.bit_count() if na is None else na
    nb = b.bit_count() if nb is None else nb
    if n == 0 or na in (0, n) or nb in (0, n):
        return None
    return min(1., abs((n * (a & b).bit_count() - na * nb) /
                       math.sqrt(na * nb * (n - na) * (n - nb))))


def analyse(catalog, keys, masks):
    defs, n = catalog["definitions"], len(keys)
    m = len(defs)
    if m != 800 or len(masks) != m or n < 10 or len(keys) != len(set(keys)):
        raise ValueError("Incomplete frozen incidence matrix")
    if any(x < 0 or x >> n for x in masks):
        raise ValueError("Incidence mask outside observed matches")
    counts = [v.bit_count() for v in masks]
    valid = [0 < v < n for v in counts]
    corr = [[None] * m for _ in range(m)]
    sumsq = 0.
    high = near = 0
    for i in range(m):
        if not valid[i]:
            continue
        corr[i][i] = 1.
        sumsq += 1.
        for j in range(i + 1, m):
            if not valid[j]:
                continue
            v = phi(masks[i], masks[j], n, counts[i], counts[j])
            corr[i][j] = corr[j][i] = v
            sumsq += 2 * v * v
            high += v >= .90
            near += v >= .95
    valid_count = sum(valid)
    effective = (valid_count ** 2 / sumsq) if sumsq else 0
    all_bits = (1 << n) - 1
    exact = Counter(min(v, all_bits ^ v) for v in masks)
    redundant_exact = sum(c - 1 for c in exact.values())
    families = {}
    for i, h in enumerate(defs):
        families.setdefault(family(h["definition"]), []).append(i)
    def priority(i):
        return (not valid[i], abs(counts[i] - n / 2),
                complexity(defs[i]["definition"]), defs[i]["id"])
    chosen = [min(families[key], key=priority) for key in sorted(families)[:CAP]]
    left = set(range(m)) - set(chosen)
    distances = [1.] * m
    for j in chosen:
        for i in left:
            if corr[i][j] is not None:
                distances[i] = min(distances[i], 1-corr[i][j])
    while len(chosen) < min(CAP, m):
        j = min(left, key=lambda i: (-round(distances[i], 12), priority(i)))
        chosen.append(j)
        left.remove(j)
        for i in left:
            if corr[i][j] is not None:
                distances[i] = min(distances[i], 1-corr[i][j])
    chosen_set = set(chosen)
    mapping = []
    for i, h in enumerate(defs):
        if i in chosen_set:
            j, strength, reason = i, 1., "REPRESENTATIVE"
        else:
            j = min(chosen, key=lambda t: (
                -(corr[i][t] if corr[i][t] is not None else
                  1. if masks[i] in (masks[t], all_bits ^ masks[t]) else -1.),
                defs[t]["id"]))
            strength = corr[i][j]
            if masks[i] == masks[j]:
                reason, strength = "IDENTICAL_OBSERVATIONS", 1.
            elif masks[i] == all_bits ^ masks[j]:
                reason, strength = "COMPLEMENT_OBSERVATIONS", 1.
            elif strength is None:
                reason = "DEGENERATE_INCIDENCE_CAP"
            elif strength >= .95:
                reason = "NEAR_EQUIVALENT_PHI"
            elif strength >= .90:
                reason = "HIGH_CORRELATION_PHI"
            else:
                reason = "DIVERSITY_CAP_300"
        mapping.append({"id":h["id"],"representative":defs[j]["id"],
                        "decision":reason,"abs_phi":round(strength,6) if strength is not None else None,
                        "family":family(h["definition"]),"incidence_n":counts[i]})
    mapping.sort(key=lambda x:x["id"])
    decisions = Counter(x["decision"] for x in mapping)
    return {
        "schema_version":1,"status":STATUS,"scientific_state":"INCONCLUSIVO",
        "scope":{"original_catalog":m,"representatives":len(chosen),
                 "mapped_originals":len(mapping),"observed_matches_frozen":n,
                 "non_degenerate_columns":valid_count,"constant_columns":m-valid_count,
                 "exact_or_complement_redundancies":redundant_exact,
                 "pairs_phi_ge_090":high,"pairs_phi_ge_095":near,
                 "families":len(families),"decision_counts":dict(sorted(decisions.items()))},
        "effective_tests":{"estimate":round(effective,3),
                           "method":"participation_ratio = (tr R)^2/tr(R^2), binary phi correlations",
                           "not_a_multiple_testing_alpha_adjustment":True,
                           "original_proposals_considered":catalog["original_generation"]["considered"],
                           "distinct_pre_cap":catalog["original_generation"]["generated"]},
        "selection":{"algorithm":"family/operator seed then farthest-first 1-|phi|, outcome blind",
                     "near_threshold_abs_phi":.95,"high_threshold_abs_phi":.90,
                     "representatives":sorted(defs[i]["id"] for i in chosen),
                     "mapping":mapping},
        "limitations":["800 is not the full original proposal universe.",
                       "Participation ratio is a descriptive effective dimension, not an alpha correction.",
                       "Telegram alert-selected historical observations, not OOS validation.",
                       "Historical observed_at does not establish prospective collector known_at.",
                       "No market outcomes, FT, residuals, strike rates, ROI or p-values used.",
                       "300 bounds exploratory research, not historical testing multiplicity."]}


def make_snapshot(catalog, keys, masks):
    doc = {"schema_version":1,"status":"FROZEN_EXPLORATORY_INCIDENCE",
           "catalog_sha256":sha(catalog),"match_keys":keys,
           "incidence_hex":[format(v,"x") for v in masks]}
    doc["sha256"] = sha(doc)
    return doc


def replay(catalog, snapshot):
    if snapshot.get("schema_version") != 1 or snapshot.get("status") != "FROZEN_EXPLORATORY_INCIDENCE":
        raise ValueError("Unknown frozen snapshot")
    if snapshot.get("sha256") != sha({k:v for k,v in snapshot.items() if k != "sha256"}):
        raise ValueError("Frozen snapshot modified")
    if snapshot.get("catalog_sha256") != sha(catalog):
        raise ValueError("Catalogue modified after freeze")
    report = analyse(catalog,snapshot["match_keys"],[int(x,16) for x in snapshot["incidence_hex"]])
    report["source"]={"catalog_sha256":snapshot["catalog_sha256"],
                      "incidence_sha256":snapshot["sha256"],
                      "original_source_commit":catalog["source_commit"],
                      "original_source_report_blob_sha":catalog["source_report_blob_sha"],
                      "feature_version":catalog["feature_version"],
                      "ft_outcomes_used":False}
    return report


def run(root, *, verify_only=False):
    root = Path(root)
    catalog = catalog_read(root)
    path, out = root/FROZEN, root/REPORT
    if path.is_file():
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    elif verify_only:
        raise ValueError("No published snapshot")
    else:
        keys, masks = incidence(root,catalog)
        snapshot = make_snapshot(catalog,keys,masks)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(snapshot,sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    report = replay(catalog,snapshot)
    body = json.dumps(report,sort_keys=True,ensure_ascii=False,indent=2)+"\n"
    if verify_only:
        if not out.is_file() or out.read_text(encoding="utf-8") != body:
            raise ValueError("Frozen report replay mismatch")
    elif not out.is_file() or out.read_text(encoding="utf-8") != body:
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(body,encoding="utf-8")
    return report
