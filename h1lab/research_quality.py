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
from .research_executor import MIN_N, OOS_TRAIN_SHARE, membership
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


def _design(expr):
    """Conservative dimension checking; complex motion expressions need review.

    A signed directional bound must exclude the dead zone. A threshold with the
    opposite direction (e.g. x < +floor) does not establish a material move.
    """
    rejected, deferred = set(), set()

    def walk(n):
        used = variables_used(n)
        motion = used & FLOORS.keys()
        op, args = n.get('op'), n.get('args', [])
        if op in ('and', 'or'):
            for a in args:
                walk(a)
        elif op == 'is_known':
            pass  # availability guard, never evidence of material movement
        elif motion:
            if (op in ('ge', 'gt', 'le', 'lt') and len(args) == 2
                    and args[0].get('var') in FLOORS and 'const' in args[1]):
                name, bound = args[0]['var'], args[1]['const']
                floor, _ = FLOORS[name]
                if abs(bound) < floor:
                    rejected.add('IMMATERIAL_MOVEMENT')
                elif not ((op in ('ge', 'gt') and bound > 0)
                          or (op in ('le', 'lt') and bound < 0)):
                    deferred.add('MATERIAL_DIRECTION_UNPROVEN')
            else:
                units = {FLOORS[v][1] for v in motion}
                if len(units) > 1:
                    rejected.add('MIXED_MOVEMENT_UNITS')
                else:
                    deferred.add('MATERIALITY_UNPROVEN')
        elif not used:
            rejected.add('CONSTANT_CONDITION')
    walk(expr)
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
    status = 'REJECTED' if reject else 'INSUFFICIENT_DATA' if defer else 'SCIENTIFICALLY_TESTABLE'
    return {'version': VERSION, 'quality_status': status, 'reasons': sorted(reject | defer),
            'metrics': metrics, 'diagnostic_only': True, 'promotion_eligible': False,
            'alternative_explanations': 'TEXT_NOT_VERIFIED',
            'confounding_scope': 'AVAILABILITY_ONLY_NOT_CAUSAL_PROOF',
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
