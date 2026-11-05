"""Experiment plans: the only thing an LLM (or the offline proposer) can submit.

A plan is data. It names a market/outcome that really exists in the dataset, a
boolean ``condition`` (the group), an optional ``control_condition`` for comparing
alternative explanations (otherwise the complement), up to three new indicators in
the safe DSL, and free text (question, hypothesis, rationale) that is stored and
displayed but never executed or interpreted as instructions.

Validation happens BEFORE any experiment; an invalid plan is recorded as
PLAN_REJECTED with the structural reason, never silently repaired.
"""
from __future__ import annotations

import hashlib
import json

from .research_dataset import OUTCOMES, VARIABLES
from .research_dsl import DSLError, canonical_json, validate, validate_indicator, variables_used

PLAN_SCHEMA = 1
TEST_VERSION = 'RX1'
TEXT_FIELDS = {'question': (10, 400), 'hypothesis': (10, 600), 'null_hypothesis': (10, 600),
               'rationale': (0, 800)}
STRATA = ('lead_bin', 'line_bin', 'competition_type')
REQUIRED = {'question', 'hypothesis', 'null_hypothesis', 'market', 'outcome', 'condition'}
OPTIONAL = {'control_condition', 'indicators', 'rationale', 'alternative_explanations',
            'confounders', 'related_to'}


class PlanError(ValueError):
    pass


def _text(value, name, lo, hi):
    if not isinstance(value, str) or not lo <= len(value) <= hi:
        raise PlanError('INVALID_TEXT:' + name)
    clean = ''.join(c for c in value if ord(c) >= 32 or c in '\n\t')
    return clean.strip()


def base_types():
    return {k: v[0] for k, v in VARIABLES.items()}


def validate_plan(raw):
    """Return a canonical plan dict or raise PlanError (reason only, no model text)."""
    if not isinstance(raw, dict):
        raise PlanError('PLAN_NOT_OBJECT')
    keys = set(raw)
    if not REQUIRED <= keys or keys - REQUIRED - OPTIONAL:
        raise PlanError('PLAN_KEYS_INVALID')
    plan = {}
    for k, (lo, hi) in TEXT_FIELDS.items():
        if k in raw or k in REQUIRED:
            plan[k] = _text(raw.get(k, ''), k, lo, hi)
    market, outcome = raw['market'], raw['outcome']
    if market not in OUTCOMES or outcome not in OUTCOMES.get(market, {}):
        raise PlanError('UNSUPPORTED_MARKET_OR_OUTCOME')
    plan['market'], plan['outcome'] = market, outcome
    types = base_types()
    indicators = []
    specs = raw.get('indicators', [])
    if not isinstance(specs, list) or len(specs) > 3:
        raise PlanError('TOO_MANY_INDICATORS')
    try:
        for spec in specs:
            ind = validate_indicator(spec, types)
            types[ind['name']] = ind['type']
            indicators.append(ind)
        cond, _ = validate(raw['condition'], types, expect='bool')
        ctrl = None
        if raw.get('control_condition') is not None:
            ctrl, _ = validate(raw['control_condition'], types, expect='bool')
            if canonical_json(ctrl) == canonical_json(cond):
                raise PlanError('CONTROL_EQUALS_CONDITION')
    except DSLError as exc:
        raise PlanError('DSL:' + str(exc)) from None
    used = variables_used(cond) | (variables_used(ctrl) if ctrl else set())
    for ind in reversed(indicators):  # an indicator may only use earlier ones
        if ind['name'] in used:
            used |= set(ind['uses'])
    unused = [i['name'] for i in indicators if i['name'] not in used]
    if unused:
        raise PlanError('INDICATOR_DEFINED_BUT_UNUSED')
    plan['indicators'] = indicators
    plan['condition'] = cond
    plan['control_condition'] = ctrl
    alts = raw.get('alternative_explanations', [])
    if not isinstance(alts, list) or len(alts) > 5:
        raise PlanError('INVALID_ALTERNATIVES')
    plan['alternative_explanations'] = [_text(a, 'alternative', 3, 300) for a in alts]
    conf = raw.get('confounders', list(STRATA))
    if not isinstance(conf, list) or any(c not in STRATA for c in conf) or len(set(conf)) != len(conf):
        raise PlanError('UNSUPPORTED_CONFOUNDER_STRATUM')
    plan['confounders'] = sorted(conf) or list(STRATA)
    rel = raw.get('related_to', [])
    if not isinstance(rel, list) or len(rel) > 10 or any(
            not isinstance(r, str) or not (8 <= len(r) <= 64) or not r.isalnum() for r in rel):
        raise PlanError('INVALID_RELATED_IDS')
    plan['related_to'] = sorted(set(rel))
    plan['variables_used'] = sorted(v for v in used if v in VARIABLES)
    plan['test_version'] = TEST_VERSION
    plan['schema_version'] = PLAN_SCHEMA
    plan['fingerprint'] = fingerprint(plan)
    plan['hypothesis_id'] = 'H' + plan['fingerprint'][:15]
    return plan


def inline(expr, indicators):
    """Replace indicator references by their definitions (names do not matter)."""
    defs = {i['name']: i['expr'] for i in indicators}

    def walk(n):
        if 'var' in n and n['var'] in defs:
            return walk(defs[n['var']])
        if 'args' in n:
            return {'op': n['op'], 'args': [walk(a) for a in n['args']]}
        return n
    return walk(expr)


def fingerprint(plan):
    """Identity of the *scientific question*, independent of wording and of names."""
    inds = plan.get('indicators', [])
    ctrl = plan.get('control_condition')
    core = {'market': plan['market'], 'outcome': plan['outcome'],
            'condition': inline(plan['condition'], inds),
            'control': inline(ctrl, inds) if ctrl else None,
            'test_version': TEST_VERSION}
    return hashlib.sha256(json.dumps(core, sort_keys=True, allow_nan=False).encode()).hexdigest()
