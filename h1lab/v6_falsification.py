"""V6 deterministic falsification battery: 10 challenges to a frozen hypothesis.

This is an *experimental descriptive audit*, never an OOS promotion or trading
signal. Sources are only append-only FROZEN forecasts and the current effective
FT event in append-only science memory. No historical reconstruction is used
to fill missing capture context. A passed screen is NOT proof of an edge.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .v6_hypotheses import ensure_registered
from .v6_science_memory import digest, read_stream
from .v6_shadow import HYPOTHESIS, read_journal, utc

SCHEMA = 1
TEST_VERSION = "V6-FALSIFICATION-1"
TEST_IDS = (
    "F01_EPISODE_INDEPENDENCE",
    "F02_RISING_VS_FLAT",
    "F03_1X2_AH_CONSISTENCY",
    "F04_LEAD_TIME_STRATA",
    "F05_COMPETITION_CONTEXT",
    "F06_LEAVE_DAY_OUT_AND_TRIM",
    "F07_RESIDUAL_VS_MARKET",
    "F08_COMPETING_MARKET_LINE",
    "F09_MATCHED_MARKET_PEERS",
    "F10_PROSPECTIVE_CONFIRMATION",
)
MIN_PROSPECTIVE_FT = 1000  # Claude's predeclared validation readiness threshold


def verdict(code, state, *, used=0, requirement=None, diagnostics=None, keys=()):
    if state not in ("PASS", "FAIL", "INSUFFICIENT_N"):
        raise ValueError("invalid falsification result")
    return {"code": code, "result": state, "n": used, "required": requirement,
            "diagnostics": diagnostics or {},
            "source_match_keys": sorted(set(keys))[:25],
            "meaning": ("DESCRIPTIVE_SCREEN_NOT_OOS_APPROVAL" if state != "INSUFFICIENT_N"
                        else "NOT_ENOUGH_PROSPECTIVE_INFORMATION")}


def _num(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _mean(vals):
    return sum(vals) / len(vals) if vals else None


def _summary(rows):
    if not rows:
        return {"n": 0, "residual": None, "market": None, "observed": None}
    return {
        "n": len(rows),
        "residual": round(_mean([r["residual"] for r in rows]), 4),
        "market": round(_mean([r["p"] for r in rows]), 4),
        "observed": round(_mean([r["y"] for r in rows]), 4),
    }


def _band(minutes):
    if not _num(minutes) or minutes < 0:
        return "UNKNOWN"
    if minutes < 60:
        return "LT_1H"
    if minutes < 360:
        return "1_TO_6H"
    if minutes < 1440:
        return "6_TO_24H"
    return "GT_24H"


def _line(row):
    q = row.get("price_quality") or {}
    side = q.get("after") or {}
    return side.get("line") if _num(side.get("line")) else None


def _lambda(row):
    q = row.get("price_quality") or {}
    return q.get("lambda_after") if _num(q.get("lambda_after")) else None


def _context(row):
    ctx = row.get("falsification_context")
    return ctx if isinstance(ctx, dict) and ctx.get("schema") == "V6-FALSIFICATION-CONTEXT-1" else None


def _latest(frozen):
    latest = {}
    for item in frozen:
        last = latest.get(item["match_key"])
        # The journal is append-only: freeze the latest actually known
        # observation by real known_at, not by selected outcome.
        if last is None or (item["known_at"], item["event_id"]) > (last["known_at"], last["event_id"]):
            latest[item["match_key"]] = item
    return latest


def _current_ft(evidence):
    effective = {}
    for item in evidence:
        e = item["event"]
        key = e["match_key"]
        prev = effective.get(key)
        if e.get("previous_evidence_event_id") != (prev["event_id"] if prev else None):
            raise ValueError("broken FT revision lineage")
        effective[key] = e
    return effective


def score_rows(frozen, evidence, registration, now):
    """Use only genuine pre-KO freezes *after formal registration*.

    Additional conservative FT guard: one observed result per match, with an
    auditable checked_at no earlier than KO or later than process time.
    """
    reg_at = utc(registration["registered_at"])
    if reg_at is None:
        raise ValueError("registration has no valid timestamp")
    latest = _latest(frozen)
    effective = _current_ft(evidence)
    scored, prospective, excluded = [], [], Counter()
    for key, row in sorted(latest.items()):
        known = utc(row.get("known_at"))
        ko = utc(row.get("kickoff_utc"))
        if (not known or not ko or known >= ko or known > now or ko > now):
            excluded["not_completed_prospective_freeze"] += 1
            continue
        if known < reg_at:
            excluded["captured_before_formal_registration"] += 1
            continue
        if row.get("hypothesis_id") != HYPOTHESIS:
            excluded["different_hypothesis"] += 1
            continue
        ctx = _context(row)
        p = row.get("market_probability_over_2_5")
        if not _num(p) or not 0 < p < 1:
            excluded["no_clean_market_probability"] += 1
            continue
        r = {"key": key, "source_event_id": row["event_id"], "source_sha256": row["sha256"],
             "p": p, "line": _line(row), "lambda": _lambda(row),
             "ko": ko, "known": known, "context": ctx,
             "pattern": bool(row["pattern_original_posthoc"]),
             "strict": bool(row["pattern_strict_posthoc"]),
             "lead": ((ctx or {}).get("first_lead_minutes")
                      if ctx else (ko - utc(row["observed_at"])).total_seconds() / 60),
             "message_count": row["message_count_at_capture"]}
        prospective.append(r)
        ft = effective.get(key)
        if ft is None or ft.get("state") != "CONFIRMED":
            excluded["ft_missing_or_quarantined"] += 1
            continue
        checked = utc(ft.get("ft_checked_at"))
        if checked is None or checked < ko or checked > now:
            excluded["ft_not_temporally_proven"] += 1
            continue
        score = ft.get("ft") or {}
        if (ft.get("frozen_source_sha256") != row["sha256"]
                or not isinstance(score.get("over_2_5"), bool)):
            excluded["ft_source_mismatch"] += 1
            continue
        scored.append(dict(r, y=int(score["over_2_5"]),
                           residual=int(score["over_2_5"]) - p,
                           ft_source=ft.get("ft_source"),
                           ft_checked_at=ft["ft_checked_at"],
                           ft_evidence_level=ft.get("ft_evidence_level")))
    return prospective, scored, dict(excluded)


def ten_tests(prospective, scored, *, registry, now, coverage=None):
    """Predefined fixed rules. Uses NO significance-based hypothesis selection."""
    selected = [r for r in scored if r["pattern"]]
    all_selected = [r for r in prospective if r["pattern"]]
    controls = [r for r in scored if not r["pattern"]]
    c = {}
    # F01 Does the historic multi-ALERT condition correspond to independent episodes?
    observed_ctx = [r for r in all_selected if r["context"] is not None]
    strict = [r for r in observed_ctx if r["strict"]]
    ratio = len(strict) / len(observed_ctx) if observed_ctx else None
    c[TEST_IDS[0]] = verdict(TEST_IDS[0],
        "INSUFFICIENT_N" if len(observed_ctx) < 10 else
        ("PASS" if ratio >= 0.80 else "FAIL"),
        used=len(observed_ctx), requirement="10 selected freezes with captured context; strict >= 80%",
        diagnostics={"with_independent_episodes": len(strict), "strict_ratio": ratio,
                     "legacy_without_context_excluded": len(all_selected)-len(observed_ctx)},
        keys=[r["key"] for r in observed_ctx])
    # F02 Rising vs flat: require actual frozen episode classifications, no guessed interpolation.
    groups = defaultdict(list)
    for r in selected:
        ctx = r["context"]
        if ctx:
            groups[ctx.get("watch_category") or "UNKNOWN"].append(r)
    relevant = ["RISING_EACH_EPISODE", "RISING_WITH_FLAT", "FLAT_EACH_EPISODE"]
    valid = [k for k in relevant if len(groups[k]) >= 10]
    c[TEST_IDS[1]] = verdict(TEST_IDS[1],
        "INSUFFICIENT_N" if len(valid) < 2 else
        ("PASS" if all(_mean([r["residual"] for r in groups[k]]) > 0 for k in valid) else "FAIL"),
        used=sum(len(groups[k]) for k in relevant),
        requirement="two episode-category cells with >=10 genuine scored FT each",
        diagnostics={"categories": {k: _summary(groups[k]) for k in relevant}},
        keys=[r["key"] for k in relevant for r in groups[k]])
    # F03 Agreement between AH and 1X2: not a direct confirmation of Over!
    checks = [v for r in all_selected for v in
              ((r["context"] or {}).get("cross_market_agreements") or []) if isinstance(v, bool)]
    both = len(checks)
    consistency = sum(checks) / both if both else None
    c[TEST_IDS[2]] = verdict(TEST_IDS[2],
        "INSUFFICIENT_N" if both < 10 else ("PASS" if consistency >= .60 else "FAIL"),
        used=both, requirement="10 comparable simultaneous AH/1X2 direction events",
        diagnostics={"agreement_fraction": consistency,
                     "warning": "Agreement of AH and 1X2 is not independent evidence of Over"},
        keys=[r["key"] for r in all_selected
              if (r["context"] or {}).get("cross_market_agreements")])
    # F04 Lead time: does residual persist over more than one timing stratum?
    buckets = defaultdict(list)
    for r in selected:
        buckets[_band(r["lead"])].append(r)
    full = [k for k, group in buckets.items() if k != "UNKNOWN" and len(group) >= 20]
    c[TEST_IDS[3]] = verdict(TEST_IDS[3],
        "INSUFFICIENT_N" if len(full) < 2 else
        ("PASS" if all(_mean([r["residual"] for r in buckets[k]]) > 0 for k in full) else "FAIL"),
        used=len(selected), requirement="two lead-time strata each with >=20 eligible FT",
        diagnostics={"lead_strata": {k: _summary(v) for k, v in sorted(buckets.items())}},
        keys=[r["key"] for r in selected])
    # F05 Type of competition: impossible to assign reliably from team name alone.
    kinds = defaultdict(list)
    for r in selected:
        g = (r["context"] or {}).get("competition_group_heuristic") or "UNKNOWN"
        kinds[g].append(r)
    ready = [k for k in kinds if k != "UNKNOWN" and len(kinds[k]) >= 20]
    c[TEST_IDS[4]] = verdict(TEST_IDS[4],
        "INSUFFICIENT_N" if len(ready) < 2 else
        ("PASS" if all(_mean([r["residual"] for r in kinds[k]]) > 0 for k in ready) else "FAIL"),
        used=len(selected), requirement="two heuristic competition types with >=20 scored FT each",
        diagnostics={"groups": {k: _summary(v) for k, v in sorted(kinds.items())},
                     "classifier": "heuristic competition label, not validated taxonomy"},
        keys=[r["key"] for r in selected])
    # F06 Remove one day each time, and 5% most extreme residuals (fixed).
    days = defaultdict(list)
    for r in selected:
        days[r["ko"].date().isoformat()].append(r)
    jack = {day: _mean([r["residual"] for r in selected if r["ko"].date().isoformat() != day])
            for day in sorted(days) if len(selected) > len(days[day])}
    ntrim = math.ceil(len(selected)*.05)
    trimmed = sorted(selected, key=lambda r: (abs(r["residual"]), r["key"]))
    robust = _mean([r["residual"] for r in trimmed[:-ntrim]]) if ntrim and len(selected)>ntrim else None
    c[TEST_IDS[5]] = verdict(TEST_IDS[5],
        "INSUFFICIENT_N" if len(selected) < 30 or len(days) < 3 else
        ("PASS" if robust is not None and robust > 0 and all(v > 0 for v in jack.values()) else "FAIL"),
        used=len(selected), requirement="30 selected FT spanning 3 days, leave-one-day-out and trim highest 5% absolute residual",
        diagnostics={"days": len(days), "leave_one_day_out_residual": {k: round(v, 4) for k,v in jack.items()},
                     "trimmed_residual": round(robust, 4) if robust is not None else None},
        keys=[r["key"] for r in selected])
    # F07 Residual vs market. A screen PASS is reserved for 1000 genuine FT.
    weeks = {r["ko"].isocalendar()[:2] for r in selected}
    base = _summary(selected)
    c[TEST_IDS[6]] = verdict(TEST_IDS[6],
        "INSUFFICIENT_N" if len(selected) < MIN_PROSPECTIVE_FT or len(weeks) < 3 else
        ("PASS" if base["residual"] > .05 else "FAIL"),
        used=len(selected), requirement=">=1000 FT after hypothesis registration across >=3 weeks; mean residual > 5 pp",
        diagnostics={"compared_to_market": base, "distinct_weeks":len(weeks),
                     "not_a_p_value": True, "formal_e_process_required_independently": True},
        keys=[r["key"] for r in selected])
    # F08 Strong competing explanation: high Total line / lambda market strata.
    def market_bucket(r):
        line = r["line"]
        return ("HIGH" if line >= 3.25 else "LOW" if line <= 2.25 else "MID") if _num(line) else "UNKNOWN"
    members, others = defaultdict(list), defaultdict(list)
    for r in selected: members[market_bucket(r)].append(r)
    for r in controls: others[market_bucket(r)].append(r)
    common = [b for b in ("LOW", "MID", "HIGH") if len(members[b]) >= 20 and len(others[b]) >= 20]
    contrasts = {b: round(_mean([r["residual"] for r in members[b]]) -
                          _mean([r["residual"] for r in others[b]]), 4) for b in common}
    c[TEST_IDS[7]] = verdict(TEST_IDS[7],
        "INSUFFICIENT_N" if len(common) < 2 else
        ("PASS" if all(x > 0 for x in contrasts.values()) else "FAIL"),
        used=len(selected), requirement="two market-line bins with >=20 selected AND 20 controls each",
        diagnostics={"within_line_residual_uplift_vs_controls": contrasts,
                     "matched_bins":common,
                     "scope": "observed alert-selected sample; not causal"},
        keys=[r["key"] for r in selected])
    # F09 Independent controls with similar market lambda and lead time.
    # Greedy matching WITHOUT reuse; matched pairs are descriptive only.
    pool = sorted([r for r in controls if _num(r["lambda"]) and _num(r["lead"])],
                  key=lambda r:r["key"])
    pairs = []
    for r in sorted(selected, key=lambda a:a["key"]):
        if not _num(r["lambda"]) or not _num(r["lead"]):
            continue
        fits = [(abs(r["lambda"] - v["lambda"]) / .25 +
                 abs(r["lead"] - v["lead"]) / 360., j, v)
                for j,v in enumerate(pool)
                if abs(r["lambda"] - v["lambda"]) <= .25
                and abs(r["lead"] - v["lead"]) <= 360.]
        if fits:
            _, idx, mate = min(fits, key=lambda x:(x[0], x[2]["key"]))
            pairs.append((r,mate))
            pool.pop(idx)
    contrasts = [a["residual"] - b["residual"] for a,b in pairs]
    c[TEST_IDS[8]] = verdict(TEST_IDS[8],
        "INSUFFICIENT_N" if len(pairs) < 30 else
        ("PASS" if _mean(contrasts) > 0 else "FAIL"),
        used=len(pairs), requirement="30 no-reuse peers within lambda 0.25 and lead time 6h",
        diagnostics={"matched_mean_residual_difference": (round(_mean(contrasts), 4)
                       if contrasts else None), "match_method": "fixed scales, greedy, no control reuse"},
        keys=[r["key"] for r,_ in pairs])
    # F10 Was the evidence genuinely registered before kickoff AND complete?
    registered = utc(registry["registered_at"])
    invalid = [r for r in prospective if r["known"] < registered or r["known"] >= r["ko"]]
    quality = len(selected) / len(all_selected) if all_selected else None
    coverage_gate = (coverage or {}).get("v6_1_14_day_gate", "UNKNOWN")
    c[TEST_IDS[9]] = verdict(TEST_IDS[9],
        "FAIL" if invalid else "INSUFFICIENT_N" if (
            len(selected)<MIN_PROSPECTIVE_FT or len(weeks)<3 or
            coverage_gate != "SOURCE_COVERAGE_PASS_PENDING_EXTERNAL_VERIFICATION"
        ) else "PASS",
        used=len(selected), requirement="1000 registered genuine FT in >=3 weeks AND source coverage 14-day gate",
        diagnostics={"invalid_freezes":len(invalid), "registered_at":registry["registered_at"],
                     "selected_with_clean_ft":len(selected),
                     "prospective_pattern_without_ft":len(all_selected)-len(selected),
                     "coverage_gate":coverage_gate, "scored_fraction_of_observed_selected":quality,
                     "coverage_is_source_observable_not_delivery_certification":True},
        keys=[r["key"] for r in selected])
    if tuple(c) != TEST_IDS:
        raise ValueError("falsification catalogue changed without versioning")
    return [c[i] for i in TEST_IDS]


def evaluate(frozen, evidence, registration, now, *, coverage=None):
    if now.tzinfo is None:
        raise ValueError("timezone-aware now required")
    now = now.astimezone(timezone.utc)
    prospective, scored, excluded = score_rows(frozen, evidence, registration, now)
    checks = ten_tests(prospective, scored, registry=registration, now=now, coverage=coverage)
    result_counts = dict(Counter(r["result"] for r in checks))
    # Never label an overall hypothesis valid just because one descriptive check PASSes.
    return {
        "schema_version": SCHEMA, "test_version": TEST_VERSION,
        "status": "V6_FALSIFICATION_SHADOW_NO_PROMOTION",
        "hypothesis_id": HYPOTHESIS,
        "hypothesis_definition_sha256": registration["definition_sha256"],
        "registered_at": registration["registered_at"],
        "evaluation_clock": now.isoformat(timespec="seconds"),
        "data_lineage": {"forecast_journal_tail": frozen[-1]["sha256"] if frozen else None,
                         "memory_evidence_tail": evidence[-1]["sha256"] if evidence else None,
                         "frozen_records": len(frozen), "confirmed_evidence_events": len(evidence),
                         "excluded_reasons": excluded,
                         "source": "frozen forecasts + append-only V6 FT evidence; no historical V5 backfill"},
        "sample": {"eligible_completed":len(prospective),
                   "eligible_scored":len(scored),
                   "selected_completed":sum(r["pattern"] for r in prospective),
                   "selected_scored":sum(r["pattern"] for r in scored),
                   "controls_scored":sum(not r["pattern"] for r in scored)},
        "checks":checks, "check_result_counts":result_counts,
        "overall": "INCONCLUSIVO",
        "limitations": [
            "PASS/FAIL describe predefined falsification screens, NOT validation/p-value/edge.",
            "Only one registered post-hoc hypothesis; exploratory V5 hypotheses are NOT frozen.",
            "Missing capture-time context stays UNKNOWN; old journal rows are never rewritten.",
            "Missing FT or unknown checked_at is excluded rather than backfilled.",
            "The 7/14-day evidence gate remains separate and required.",
            "No odds feed between Telegram messages, no causal claims or betting recommendation.",
        ],
    }


def run(root, now):
    root = Path(root)
    frozen = read_journal(root)
    hypothesis_file = root / "data/lab/v6-hypotheses.jsonl"
    if not hypothesis_file.exists():
        raise ValueError("missing formal frozen hypothesis registration")
    lines = hypothesis_file.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1:
        raise ValueError("unexpected frozen hypothesis history length")
    registration = json.loads(lines[0])
    if registration.get("id") != HYPOTHESIS:
        raise ValueError("hypothesis mismatch")
    from .v6_hypotheses import definition_digest
    if registration.get("definition_sha256") != definition_digest():
        raise ValueError("frozen hypothesis definition changed")
    evidence = read_stream(root, "evidence")
    p = root / "docs/lab/v6-readiness.json"
    coverage = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    return evaluate(frozen, evidence, registration, now, coverage=coverage)
