"""B1 diagnostic only: no I/O, outcomes, ranking changes or experiment execution.

Metadata is a separate, outcome-free contract. Missing provenance blocks admission.
Design floors are a priori candidates, not fitted or scientifically validated.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

from .research_dataset import OUTCOMES, VARIABLES
from .research_dsl import variables_used
from .research_executor import MIN_N, OOS_TRAIN_SHARE, membership, _bins
from .research_plan import PlanError, REQUIRED, OPTIONAL, inline, validate_plan
from .v6_shadow import utc

VERSION = 'B1_SHADOW_1'
# Probability units are fractions: .05 == five percentage points.
FLOORS = {'p_home_net': (.05, 'PROBABILITY_FRACTION'),
          'p_draw_net': (.05, 'PROBABILITY_FRACTION'),
          'p_away_net': (.05, 'PROBABILITY_FRACTION'),
          'lambda_net': (.10, 'IMPLIED_GOALS'),
          'lambda_abs_path': (.10, 'IMPLIED_GOALS'),
          'total_line_net': (.25, 'TOTAL_LINE'), 'ah_line_net': (.25, 'AH_LINE')}
UNAVAILABLE = re.compile(r'\b(bookmaker|operator|operador|live|in.play|btts price|post.kickoff|pós.kickoff|score|scores|ganhos|profit)\b', re.I)


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                     separators=(',', ':')).encode()).hexdigest()


def _dimensions(expr):
    """Check units and expression validity in either arm."""
    rejected, deferred = set(), set()

    def unit(n):
        if 'const' in n:
            return None
        if 'var' in n:
            v = n['var']
            if VARIABLES[v][0] == 'bool':
                return 'BOOL'
            if v.startswith('p_') or v == 'total_overround_last':
                return 'PROBABILITY'
            if v.startswith('total_line_') and v not in ('total_line_ups', 'total_line_downs'):
                return 'TOTAL_LINE'
            if v.startswith('ah_line_') and v != 'ah_line_moves':
                return 'AH_LINE'
            if v in ('lambda_first', 'lambda_last', 'lambda_net', 'lambda_abs_path',
                     'lambda_sd', 'lambda_unobserved_net'):
                return 'IMPLIED_GOALS'
            if v in ('lambda_velocity_h', 'lambda_accel_h'):
                return 'IMPLIED_GOALS_PER_HOUR'
            if v.endswith('_min'):
                return 'MINUTES'
            if v.endswith('_share'):
                return 'FRACTION'
            if v == 'kickoff_hour_utc':
                return 'HOUR_OF_DAY'
            return 'COUNT_OR_DIRECTION'
        op = n['op']
        units = {u for a in n['args'] if (u := unit(a)) is not None}
        if op in ('and', 'or', 'not', 'is_known'):
            return 'BOOL'
        if len(units) > 1:
            rejected.add('MIXED_MOVEMENT_UNITS')
        if op in ('mul', 'div') and sum('const' not in a for a in n['args']) > 1:
            deferred.add('COMPOUND_UNITS_REVIEW')
        if op in ('gt', 'ge', 'lt', 'le', 'eq', 'ne', 'between'):
            return 'BOOL'
        return next(iter(units)) if units else None

    unit(expr)
    if not variables_used(expr):
        rejected.add('CONSTANT_CONDITION')

    return rejected, deferred


def _design(expr):
    """Require a directional material bound on each signal path."""
    rejected, deferred = _dimensions(expr)

    def paths(n):
        if n == {'const': True}:
            return [[]]
        if n == {'const': False}:
            return []
        op = n.get('op')
        if op == 'or':
            result = [p for a in n['args'] for p in paths(a)]
            if len(result) > 64:
                raise ValueError('LOGIC_TOO_COMPLEX')
            return result
        if op == 'and':
            result = [[]]
            for a in n['args']:
                result = [x+y for x in result for y in paths(a)]
                if len(result) > 64:
                    raise ValueError('LOGIC_TOO_COMPLEX')
            return result
        return [[n]]

    try:
        branches = paths(expr)
        if not branches:
            rejected.add('CONSTANT_CONDITION')
        for branch in branches:
            bounds = {}
            branch_motion = set()
            complex_motion = False
            for n in branch:
                op, args = n.get('op'), n.get('args', [])
                if op == 'is_known':
                    continue
                if not variables_used(n):
                    rejected.add('CONSTANT_CONDITION')
                motion = variables_used(n) & FLOORS.keys()
                branch_motion.update(motion)
                if (op in ('gt', 'ge', 'lt', 'le') and len(args) == 2
                        and 'var' in args[0] and 'const' in args[1]):
                    v, bound = args[0]['var'], args[1]['const']
                    lower, upper = bounds.get(v, ((float('-inf'), False),
                                                   (float('inf'), False)))
                    if op in ('gt', 'ge'):
                        lower = max(lower, (bound, op == 'gt'))
                    else:
                        upper = min(upper, (bound, op != 'lt'))
                    bounds[v] = lower, upper
                elif motion:
                    complex_motion = True
            if any(lo > hi or (lo == hi and (strict_lo or not inclusive_hi))
                   for (lo, strict_lo), (hi, inclusive_hi) in bounds.values()):
                rejected.add('CONTRADICTORY_SIGNAL_PATH')
                continue
            if complex_motion or not branch_motion:
                deferred.add('MATERIALITY_UNPROVEN')
            for v in branch_motion:
                lower, upper = bounds.get(v, ((float('-inf'), False),
                                               (float('inf'), False)))
                lo, hi = lower[0], upper[0]
                floor = FLOORS[v][0]
                if lo >= floor or hi <= -floor:
                    continue
                if v not in bounds or complex_motion:
                    deferred.add('MATERIALITY_UNPROVEN')
                elif max(abs(x) for x in (lo, hi) if abs(x) != float('inf')) < floor:
                    rejected.add('IMMATERIAL_MOVEMENT')
                else:
                    deferred.add('MATERIAL_DIRECTION_UNPROVEN')
    except ValueError:
        deferred.add('MATERIALITY_UNPROVEN')
    return rejected, deferred


def raw_plan(plan):
    """Recover the existing submission contract from a canonical/legacy plan."""
    raw = {k: v for k, v in plan.items() if k in REQUIRED | OPTIONAL}
    raw['indicators'] = [{k: i[k] for k in ('name', 'description', 'expr')}
                         for i in plan.get('indicators', [])]
    return raw


def evaluate_quality(plan, metadata, *, design=None, prior_plans=()):
    """Canonical plan + pregame metadata only. Never accepts outcome-bearing rows.

    Metadata rows: match_key, variables, decision_at, kickoff_utc,
    feature_observed_at (every used variable), feature_frozen_at,
    source_event_ids, ft_verified (bool), ft_source_verified (bool),
    baseline_available (mapping of baseline key -> bool).
    design: threshold_origin=APRIORI or DISCOVERY, frozen_at; DISCOVERY also
    discovery_end. Every decision must follow freezing; discovery precedes holdout.
    Availability is counted only after group assignment and cannot define signals.
    """
    reject, defer = set(), set()
    counts = Counter(rows=len(metadata), group=0, control=0, unknown=0, overlap=0,
                     unassigned=0, ft=0, baseline=0, group_eligible=0, control_eligible=0)
    safe = []
    forbidden = {'outcome', 'score', 'scores', 'home', 'away', 'profit', 'gains'}
    try:
        raw = raw_plan(plan)
        canonical = validate_plan(raw)
        if canonical['fingerprint'] != plan.get('fingerprint'):
            reject.add('NONCANONICAL_PLAN')
        if any(forbidden & set(r) for r in metadata):
            reject.add('OUTCOME_METADATA_FORBIDDEN')
            metadata = []
        expr = inline(canonical['condition'], canonical['indicators'])
        ctrl = canonical.get('control_condition')
        r, d = _design(expr)
        reject |= r
        defer |= d
        if ctrl:
            ctrl = inline(ctrl, canonical['indicators'])
            r, d = _dimensions(ctrl)
            reject |= r
            defer |= d
            if expr == ctrl:
                reject.add('CONTROL_EQUALS_CONDITION')
        # Narrative is never evidence. Explicit unavailable claims fail closed;
        # absence of these words does not prove the claim is observable.
        narrative = ' '.join(str(canonical.get(k, '')) for k in
                             ('question', 'hypothesis', 'rationale', 'alternative_explanations'))
        if UNAVAILABLE.search(narrative):
            reject.add('UNOBSERVED_CONCEPT')
        used = set(canonical['variables_used'])
        if not used:
            reject.add('NO_OBSERVABLE_SIGNAL')
        base = OUTCOMES[canonical['market']][canonical['outcome']]
        design = design or {}
        frozen = utc(design.get('frozen_at'))
        if design.get('threshold_origin') not in ('APRIORI', 'DISCOVERY') or not frozen:
            defer.add('THRESHOLD_PROVENANCE_MISSING')
        # No production provenance adapter exists yet. JSON flags are not evidence.
        cells = {}
        seen = set()
        for row in metadata:
            key = row.get('match_key')
            if not key or key in seen:
                reject.add('DUPLICATE_MATCH_UNIT')
                continue
            seen.add(key)
            dec, ko = utc(row.get('decision_at')), utc(row.get('kickoff_utc'))
            if dec is None or ko is None:
                defer.add('DECISION_WINDOW_UNPROVEN')
            elif dec >= ko:
                reject.add('POST_KICKOFF_INFORMATION')
            if frozen and dec and frozen > dec:
                reject.add('DESIGN_NOT_FROZEN_BEFORE_DECISION')
            times = row.get('feature_observed_at', {})
            ff = utc(row.get('feature_frozen_at'))
            if not row.get('source_event_ids') or ff is None or dec is None or ko is None:
                defer.add('FEATURE_FREEZE_UNPROVEN')
            elif ff > dec or ff >= ko:
                reject.add('POST_DECISION_FEATURE_FREEZE')
            for v in used:
                t = utc(times.get(v))
                if t is None:
                    defer.add('FEATURE_WINDOW_UNPROVEN')
                elif dec and ko and (t > dec or t >= ko):
                    reject.add('POST_KICKOFF_INFORMATION')
            if ff and any(utc(times.get(v)) and utc(times[v]) > ff for v in used):
                reject.add('OBSERVATION_AFTER_FREEZE')
            g, c = membership(canonical, {'variables': row['variables']})
            if g is None:
                counts['unknown'] += 1
                continue
            if g == 'OVERLAP':
                counts['overlap'] += 1
                reject.add('GROUP_CONTROL_OVERLAP')
                continue
            if not g and not c:
                counts['unassigned'] += 1
                continue
            side = 'group' if g else 'control'
            counts[side] += 1
            bins = _bins(row)
            cell = tuple(bins[s] for s in canonical['confounders'])
            cells.setdefault(cell, Counter())[side] += 1
            ft = row.get('ft_verified') is True and row.get('ft_source_verified') is True
            baseline = base is None or row.get('baseline_available', {}).get(base) is True
            counts['ft'] += int(ft)
            counts[side + '_ft_present'] += int(row.get('ft_verified') is True)
            counts[side + '_ft_verified_source'] += int(ft)
            counts[side + '_baseline'] += int(baseline)
            counts['baseline'] += int(baseline)
            if not ft:
                defer.add('VERIFIED_FT_PROVENANCE_MISSING')
            if not baseline:
                defer.add('BASELINE_MISSING')
            if ft and baseline:
                counts[side + '_eligible'] += 1
                if ko:
                    safe.append((ko.date().isoformat(), side))
        if not metadata:
            defer.add('NO_METADATA')
        if metadata and counts['unknown'] == 0 and min(counts['group'], counts['control']) == 0:
            reject.add('TRIVIAL_PARTITION')
        if min(counts['group_eligible'], counts['control_eligible']) < MIN_N:
            defer.add('MIN_N_NOT_MET')
        days = sorted({d for d, _ in safe})
        cut = days[min(len(days)-1, max(1, int(len(days)*OOS_TRAIN_SHARE)))] if len(days) >= 4 else None
        oos = Counter({'train_group': 0, 'train_control': 0, 'test_group': 0, 'test_control': 0})
        if cut:
            for day, side in safe:
                oos[('train_' if day < cut else 'test_') + side] += 1
        if not cut or min(oos.values()) < 5:
            defer.add('CHRONOLOGICAL_OOS_INSUFFICIENT')
        if design.get('threshold_origin') == 'DISCOVERY':
            end = utc(design.get('discovery_end'))
            if not end or not frozen or not cut:
                defer.add('DISCOVERY_BOUNDARY_UNPROVEN')
            elif end > frozen or end.date().isoformat() >= cut:
                reject.add('DISCOVERY_HOLDOUT_CONTAMINATION')
        strata_vars = {'lead_bin': {'lead_first_min'}, 'line_bin': {'total_line_last'},
                       'competition_type': {'ctx_cup', 'ctx_youth_reserve', 'ctx_league_other'}}
        for s in canonical['confounders']:
            needed = strata_vars[s]
            if any(any(r['variables'].get(v) is None for v in needed) for r in metadata):
                defer.add('CONFOUNDER_DATA_MISSING')
        if not cells or any(min(c['group'], c['control']) < 2 for c in cells.values()):
            defer.add('COMMON_STRATUM_SUPPORT_MISSING')
        duplicates = sum(p.get('fingerprint') == canonical['fingerprint'] for p in prior_plans)
        near = sum(p.get('outcome') == canonical['outcome'] and
                   set(p.get('variables_used', ())) == used and
                   p.get('fingerprint') != canonical['fingerprint'] for p in prior_plans)
        if duplicates:
            reject.add('DUPLICATE_QUESTION')
        if near:
            defer.add('NEAR_DUPLICATE_REVIEW')
        metrics = dict(counts, coverage=(counts['group']+counts['control'])/counts['rows'] if counts['rows'] else 0,
                       split_day=cut, oos=dict(oos), duplicates=duplicates, near_duplicates=near)
    except (PlanError, KeyError, TypeError, ValueError, AttributeError):
        reject.add('QUALITY_INPUT_INVALID')
        metrics = dict(counts)
    design_status = 'REJECTED' if reject else 'INSUFFICIENT_DATA' if defer else 'SCIENTIFICALLY_TESTABLE'
    defer.add('TRUSTED_PROVENANCE_ADAPTER_UNAVAILABLE')
    status = 'REJECTED' if reject else 'INSUFFICIENT_DATA' if defer else 'SCIENTIFICALLY_TESTABLE'
    return {'version': VERSION, 'quality_status': status, 'design_quality_status': design_status, 'reasons': sorted(reject | defer),
            'metrics': metrics, 'diagnostic_only': True, 'promotion_eligible': False,
            'alternative_explanations': 'TEXT_NOT_VERIFIED',
            'confounding_scope': 'COMMON_SUPPORT_REQUIRED_NOT_CAUSAL_PROOF',
            'scientific_status': 'EXPLORATORY_NOT_VALIDATED'}


def shadow_report(plans, metadata, *, design=None, prior_plans=()):
    """Before/after diagnostic agenda. Zero executions and no memory writes."""
    cards, valid = [], 0
    for raw in plans:
        try:
            p = validate_plan(raw_plan(raw) if 'fingerprint' in raw else raw)
        except (PlanError, TypeError, AttributeError):
            cards.append({'structural_status': 'REJECTED', 'reasons': ['STRUCTURAL_INVALID']})
            continue
        valid += 1
        cards.append(dict(fingerprint=p['fingerprint'], structural_status='STRUCTURALLY_VALID',
                          **evaluate_quality(p, metadata, design=design, prior_plans=prior_plans)))
    statuses = Counter(c.get('quality_status') for c in cards if 'quality_status' in c)
    return {'mode': VERSION, 'input_sha256': sha({'plans': plans, 'metadata': metadata, 'design': design}),
            'funnel': {'received': len(plans), 'structurally_valid': valid,
                       'before_eligible_by_syntax': valid, 'after_eligible': statuses['SCIENTIFICALLY_TESTABLE'],
                       'quality': dict(sorted(statuses.items())), 'executed': 0},
            'agenda': cards, 'validated': [], 'memory_written': False}
