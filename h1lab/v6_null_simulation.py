"""P0: prespecified e-process Monte Carlo under synthetic, calibrated market null.

This is an engineering calibration of the ONE registered sequential rule,
not resampling historical matches, a multiple-comparisons correction, or
evidence that market probabilities are calibrated in the wild.

10,000 independently seeded null paths; separate illustrative power scenarios.
Every path is monitored after EVERY draw, not just at checkpoints.
"""
from __future__ import annotations

import hashlib
import json
import math
import random

from .v6_shadow import ALPHA, ALT_EDGES, HYPOTHESIS, MIN_EDGE, MIN_OOS_FT

VERSION = "V6-P0-NULL-1"
SEED = 20261028
NULL_TRIALS = 10_000
POWER_TRIALS = 2_500
CHECKPOINTS = (25, 50, 100, 250, 500, 1000)
PROBABILITIES = (0.30, 0.50, 0.70)
POWER_DELTAS = (0.05, 0.10, 0.20)
THRESHOLD = 1.0 / ALPHA
LOG_THRESHOLD = math.log(THRESHOLD)


def settings():
    if tuple(ALT_EDGES) != (0.05, 0.10, 0.20) or ALPHA != 0.005 or MIN_OOS_FT != 1000:
        raise ValueError("Prespecified V6 sequential rule changed: new version required")
    return {
        "version": VERSION, "seed": SEED, "null_trials": NULL_TRIALS,
        "power_trials_per_effect": POWER_TRIALS,
        "checkpoints": list(CHECKPOINTS),
        "market_p_cycle": list(PROBABILITIES),
        "synthetic_true_probability_uplifts": list(POWER_DELTAS),
        "e_process_alternatives": list(ALT_EDGES),
        "alpha_single_registered_hypothesis": ALPHA,
        "e_value_threshold": THRESHOLD,
        "minimum_prospective_ft": MIN_OOS_FT, "minimum_observed_residual": MIN_EDGE,
        "hypothesis_id": HYPOTHESIS,
        "null_assumption": "Independent Bernoulli scores conditional on prespecified, perfectly calibrated p_cycle",
        "design_assumption": "Cycle of synthetic fixed p values, NOT fitted to football matches",
    }


def setting_hash():
    return hashlib.sha256(json.dumps(settings(), sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def _paths(trials, effect, seed):
    rng = random.Random(seed)
    cutoffs = list(CHECKPOINTS)
    counters = {i: 0 for i in cutoffs}
    terminal = {i: 0 for i in cutoffs}
    wins = 0
    # Precompute step log likelihoods for each p and fixed alternative.
    weights = {}
    for p in PROBABILITIES:
        up, down = [], []
        for delta in ALT_EDGES:
            q = min(0.999, p + delta)
            up.append(math.log(q/p))
            down.append(math.log((1-q)/(1-p)))
        weights[p] = (tuple(up), tuple(down))
    for _ in range(trials):
        l0 = l1 = l2 = 0.0
        hit = False
        for index in range(1, cutoffs[-1]+1):
            p = PROBABILITIES[(index-1) % len(PROBABILITIES)]
            truth = min(0.999, p + effect)
            draw = rng.random() < truth
            a,b,c = weights[p][0 if draw else 1]
            l0 += a
            l1 += b
            l2 += c
            # Max component >= log(threshold) is a necessary condition.
            # Check full mixture only when that can possibly cross.
            if not hit and max(l0,l1,l2) >= LOG_THRESHOLD:
                hi = max(l0,l1,l2)
                e_log = hi + math.log((math.exp(l0-hi)+math.exp(l1-hi)+math.exp(l2-hi))/3.0)
                if e_log >= LOG_THRESHOLD:
                    hit = True
            if index in counters:
                counters[index] += int(hit)
                # Terminal e-value at the checkpoint (different from ever-hit).
                hi = max(l0,l1,l2)
                e_log = hi + math.log((math.exp(l0-hi)+math.exp(l1-hi)+math.exp(l2-hi))/3.0)
                terminal[index] += int(e_log >= LOG_THRESHOLD)
        wins += int(hit)
    return {"paths": trials, "ever_hit_at_any_look": wins,
            "anytime_by_checkpoint": [
                {"n": c, "crossings": counters[c], "rate": round(counters[c]/trials, 6),
                 "terminal_crossings": terminal[c],
                 "terminal_rate": round(terminal[c]/trials, 6)}
                for c in cutoffs]}


def wilson_upper(k, n, z=1.96):
    """Approximate 95% upper confidence bound for a binomial Monte Carlo rate."""
    if n <= 0 or not 0 <= k <= n:
        raise ValueError("Invalid binomial count")
    x = k/n
    return min(1.0, (x+z*z/(2*n) + z*math.sqrt(
        (x*(1-x)+z*z/(4*n))/n)) / (1+z*z/n))


def run():
    null = _paths(NULL_TRIALS, 0.0, SEED)
    null["empirical_anytime_false_positive_rate"] = round(
        null["ever_hit_at_any_look"]/NULL_TRIALS, 6)
    null["monte_carlo_95pct_upper"] = round(wilson_upper(
        null["ever_hit_at_any_look"], NULL_TRIALS), 6)
    null["theoretical_ville_anytime_bound_under_assumptions"] = ALPHA
    # An observed MC rate near/above alpha is not proof of violated
    # martingale theory; retain both raw counts and its uncertainty.
    powers = []
    for j, delta in enumerate(POWER_DELTAS):
        p = _paths(POWER_TRIALS, delta, SEED + (j+1)*100_003)
        powers.append({"synthetic_true_probability_uplift": delta,
                       "power_at_any_look": round(p["ever_hit_at_any_look"]/POWER_TRIALS, 6),
                       **p})
    return {
        "schema_version": 1, "status": "V6_P0_SIMULATED_NULL_NOT_EMPIRICAL_VALIDATION",
        "scientific_state": "INCONCLUSIVO",
        "settings": settings(), "settings_sha256": setting_hash(),
        "null": null, "illustrative_power": powers,
        "limitations": [
            "Exactly 10000 synthetic null paths; repeated monitoring at every observation.",
            "Power paths are synthetic with a fixed p cycle, NOT out-of-sample football observations.",
            "Assumes the Poisson-derived market p is correctly calibrated conditionally; untested in data.",
            "The one-hypothesis alpha bound does NOT account for V5 post-hoc search among thousands of candidates.",
            "No inferred edge, model success, bankroll or betting alert is authorized.",
            "A crossing in simulation is never a prospective hypothesis-validation event.",
            "The reported FT chronology audit is a separate live evidence check.",
        ],
    }
