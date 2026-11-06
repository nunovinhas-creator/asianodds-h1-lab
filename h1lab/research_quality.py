"""B1 diagnostic only: no I/O, outcomes, ranking changes or experiment execution.

Metadata is a separate, outcome-free contract. Missing provenance blocks admission.
Design floors are a priori candidates, not fitted or scientifically validated.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import timedelta
from itertools import islice, product

from .market_math import LAM_MAX, LAM_MIN
from .research_dataset import OUTCOMES, VARIABLES
from .research_dsl import variables_used, evaluate
from .research_executor import MIN_N, OOS_TRAIN_SHARE, membership
from .research_plan import PlanError, REQUIRED, OPTIONAL, inline, validate_plan
from .v6_shadow import utc

VERSION = 'B1_SHADOW_3'
# Probability units are fractions: .05 == five percentage points.
FLOORS = {'p_home_net': (.05, 'PROBABILITY_FRACTION'),
          'p_draw_net': (.05, 'PROBABILITY_FRACTION'),
          'p_away_net': (.05, 'PROBABILITY_FRACTION'),
          'lambda_net': (.10, 'IMPLIED_GOALS'),
          'lambda_abs_path': (.10, 'IMPLIED_GOALS'),
          'total_line_net': (.25, 'TOTAL_LINE'), 'ah_line_net': (.25, 'AH_LINE')}
# Proven by trajectory_variables: absolute sums are nonnegative; differences
# of fair probabilities in [0, 1] are in [-1, 1]. No fitted domain limits.
SIGNAL_DOMAINS = {'lambda_abs_path': (0, math.inf),
                  **{v: (-1, 1) for v in ('p_home_net', 'p_draw_net', 'p_away_net')}}
STRATA_VARIABLES = {'lead_bin': ('lead_first_min',), 'line_bin': ('total_line_last',),
                    'competition_type': ('ctx_cup', 'ctx_youth_reserve', 'ctx_league_other')}
UNAVAILABLE = re.compile(r'\b(bookmaker|operator|operador|live|in.play|btts price|post.kickoff|pós.kickoff|score|scores|ganhos|profit)\b', re.I)


def _finite(value):
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _json_input(value):
    """Reject JSON coercions (tuples, numeric keys, custom objects), not values."""
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError('NON_STRING_JSON_KEY')
        for child in value.values():
            _json_input(child)
    elif type(value) is list:
        for child in value:
            _json_input(child)
    elif type(value) not in (str, int, float, bool, type(None)):
        raise ValueError('NON_JSON_VALUE')
    elif type(value) is float and not _finite(value):
        raise ValueError('NONFINITE_JSON_VALUE')


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
        operand_units = [unit(a) for a in n['args']]
        units = {u for u in operand_units if u is not None}
        if op in ('and', 'or', 'not', 'is_known'):
            return 'BOOL'
        if len(units) > 1:
            rejected.add('MIXED_MOVEMENT_UNITS')
        if op in ('mul', 'div') and sum('const' not in a for a in n['args']) > 1:
            deferred.add('COMPOUND_UNITS_REVIEW')
        if op in ('gt', 'ge', 'lt', 'le', 'eq', 'ne', 'between'):
            return 'BOOL'
        if op == 'div' and operand_units[0] is not None and operand_units[0] == operand_units[1]:
            # Equal dimensions cancel. This does not prove a nonzero divisor,
            # satisfiability or materiality: compound algebra still defers.
            return 'DIMENSIONLESS'
        return next(iter(units)) if units else None

    unit(expr)
    if not variables_used(expr):
        rejected.add('CONSTANT_CONDITION')

    return rejected, deferred


def _logic_paths(n, negate=False):
    """Bounded DNF retaining every explicit dead alternative, including constants.

    An empty conjunction denotes true. False is an explicit atom, never an
    absent branch: OR(false, signal) must still audit the false alternative.
    """
    op, args = n.get('op'), n.get('args', [])
    if op == 'not':
        return _logic_paths(args[0], not negate)
    if op in ('and', 'or'):
        union = (op == 'or') != negate
        result = [] if union else [[]]
        for arg in args:
            part = _logic_paths(arg, negate)
            result = result + part if union else [x+y for x in result for y in part]
            if len(result) > 64:
                raise ValueError('LOGIC_TOO_COMPLEX')
        return result
    if 'const' in n:
        return [[]] if bool(n['const']) != negate else [[{'const': False}]]
    if op == 'between':
        v, lo, hi = args
        return _logic_paths({'op': 'and', 'args': [
            {'op': 'ge', 'args': [v, lo]}, {'op': 'le', 'args': [v, hi]}]}, negate)
    if negate and op in ('gt', 'ge', 'lt', 'le', 'eq', 'ne'):
        op = {'gt': 'le', 'ge': 'lt', 'lt': 'ge', 'le': 'gt', 'eq': 'ne', 'ne': 'eq'}[op]
        return [[{'op': op, 'args': args}]]
    return [[{'op': 'not', 'args': [n]} if negate else n]]


def _path_constraints(branch, *, competition_type=False, available=()):
    """Prove scalar and catalogue constraints; defer unsupported algebra.

    Equality follows the DSL's 1e-9 tolerance, not exact Python equality.
    Outward rounding keeps contradiction proofs conservative at float edges.
    A concrete DSL witness is required before claiming satisfiability.
    """
    domains, literals, known, atoms = {}, {}, {}, {}
    windows, witnesses = {}, {}
    required_known, unknown_exprs, order_edges = set(), [], []

    def identity(node):
        return json.dumps(node, sort_keys=True, separators=(',', ':'))

    def require_known(node):
        required_known.add(identity(node))
        # A known arithmetic/comparison result requires every operand. Boolean
        # AND/OR may be known through a dominating operand with unknown siblings.
        if node.get('op') not in ('and', 'or', 'is_known'):
            for arg in node.get('args', []):
                require_known(arg)

    equalities, inequalities = set(), set()
    predicates = {}
    unproven = False
    contradiction = False
    for n in branch:
        op, args = n.get('op'), n.get('args', [])
        if n == {'const': False}:
            contradiction = True
            continue
        neg = op == 'not'
        atom = args[0] if neg else n
        require_known(atom)
        if not variables_used(n):
            value = evaluate(n, {})
            if value is False:
                contradiction = True
            elif value is None:
                unproven = True
            continue
        if atom.get('op') == 'is_known':
            target = atom['args'][0]
            if neg:
                unknown_exprs.append(target)
            else:
                require_known(target)
        if op in ('gt', 'ge', 'lt', 'le', 'eq', 'ne'):
            left, right = args
            if left == right:
                if op in ('gt', 'lt', 'ne'):
                    contradiction = True
                # Reflexive comparisons require a known value; unknown != false.
                unproven |= 'var' not in left
                continue
            if op in ('gt', 'ge', 'lt', 'le'):
                a, b = (right, left) if op in ('gt', 'ge') else (left, right)
                order_edges.append((identity(a), identity(b), op in ('gt', 'lt')))

        predicate, polarity = atom, not neg
        # Complementary opaque predicates are contradictory too, even when
        # their arithmetic cannot otherwise be solved by this scalar fragment.
        complements = {'le': 'gt', 'lt': 'ge', 'ne': 'eq'}
        if atom.get('op') in complements:
            predicate = dict(atom, op=complements[atom['op']])
            polarity = not polarity
        key = json.dumps(predicate, sort_keys=True, separators=(',', ':'))
        if key in predicates and predicates[key] != polarity:
            contradiction = True
        predicates[key] = polarity
        if 'var' in atom and VARIABLES[atom['var']][0] == 'bool':
            v, value = atom['var'], not neg
            if v in literals and literals[v] != value:
                contradiction = True
            literals[v] = value
            continue
        if atom.get('op') == 'is_known' and 'var' in atom['args'][0]:
            v, value = atom['args'][0]['var'], not neg
            if v in known and known[v] != value:
                contradiction = True
            known[v] = value
            continue
        if op in ('gt', 'ge', 'lt', 'le', 'eq', 'ne') and len(args) == 2:
            left, right = args
            if 'const' in left and 'var' in right:
                left, right = right, left
                op = {'gt': 'lt', 'ge': 'le', 'lt': 'gt', 'le': 'ge', 'eq': 'eq', 'ne': 'ne'}[op]
            if 'var' in left and 'const' in right:
                v, b = left['var'], right['const']
                if op in ('eq', 'ne'):
                    key = (v, b)
                    (equalities if op == 'eq' else inequalities).add(key)
                    if key in equalities and key in inequalities:
                        contradiction = True
                lo, hi, holes = domains.setdefault(v, [(-math.inf, False),
                                                       (math.inf, False), []])
                if op in ('ge', 'gt'):
                    lo = max(lo, (b, op == 'gt'))
                elif op in ('le', 'lt'):
                    hi = min(hi, (b, op == 'le'))
                elif op == 'eq':
                    lo = max(lo, (math.nextafter(b-1e-9, -math.inf), False))
                    hi = min(hi, (math.nextafter(b+1e-9, math.inf), True))
                else:
                    holes.append((math.nextafter(b-1e-9, math.inf),
                                  math.nextafter(b+1e-9, -math.inf)))
                domains[v] = [lo, hi, holes]
                atoms.setdefault(v, []).append(n)
                continue
        unproven = True
    def guaranteed_known(node):
        if identity(node) in required_known or 'const' in node:
            return True
        if node.get('var') in available or (competition_type and
                node.get('var') in STRATA_VARIABLES['competition_type']):
            return True
        op = node.get('op')
        if op == 'is_known':
            return True
        # These operators are total on known finite inputs. ADD/MUL/SUB/DIV
        # are deliberately absent: overflow or zero divisors can yield None.
        if op in ('gt', 'ge', 'lt', 'le', 'eq', 'ne', 'between', 'not',
                  'and', 'or', 'abs', 'neg', 'sign', 'min', 'max'):
            return all(guaranteed_known(a) for a in node['args'])
        return False

    if any(guaranteed_known(node) for node in unknown_exprs):
        contradiction = True
    # Strict ordering is transitive over finite known DSL values. This graph
    # proves impossible cycles without inventing a numeric epsilon or assuming
    # approximate EQ is transitive. Unsupported algebra still defers below.
    reach = {}
    for a, b, strict in order_edges:
        reach[a, b] = reach.get((a, b), False) or strict
    nodes = sorted({v for edge in order_edges for v in edge[:2]})
    for k in nodes:
        for i in nodes:
            for j in nodes:
                if (i, k) in reach and (k, j) in reach:
                    reach[i, j] = reach.get((i, j), False) or reach[i, k] or reach[k, j]
    if any(reach.get((v, v), False) for v in nodes):
        contradiction = True
    flags = STRATA_VARIABLES['competition_type']
    assignments = [{v: v == chosen for v in flags} for chosen in flags]
    flag_witness = next((env for env in assignments if
                         all(env[v] == value for v, value in literals.items() if v in flags)
                         and all(value or v not in flags for v, value in known.items())), None)
    if flag_witness is None:
        contradiction = True
    if any(not value and guaranteed_known({'var': v}) for v, value in known.items()):
        contradiction = True
    if unknown_exprs and not contradiction:
        unproven = True
    for v, (lo, hi, holes) in domains.items():
        # Domain restrictions prove feasibility, not the materiality of a
        # submitted threshold; keep the explicit bounds returned to _design.
        domain_lo, domain_hi = _numeric_domain(v)
        lo = max(lo, (domain_lo, False))
        hi = min(hi, (domain_hi, math.isfinite(domain_hi)))
        low, strict = lo
        high, inclusive = hi
        if low > high or (low == high and (strict or not inclusive)):
            contradiction = True
            continue
        # Remove closed forbidden intervals, retaining open endpoints correctly.
        intervals = [(low, not strict, high, inclusive)]
        for start, end in holes:
            remaining = []
            for l, li, h, hin in intervals:
                if end < l or start > h:
                    remaining.append((l, li, h, hin))
                    continue
                if l < start:
                    remaining.append((l, li, start, False))
                if end < h:
                    remaining.append((end, False, h, hin))
            intervals = remaining
        if not intervals:
            contradiction = True
            continue
        witnesses[v] = set()
        discrete_possible = False
        precision = PRODUCER_PRECISION.get(v, 1 if v in PRODUCER_TIME_FIELDS else None)
        discrete = v in COUNTS or v in DIRECTIONS or v == 'kickoff_hour_utc' or precision is not None
        for l, li, h, hin in intervals:
            candidates = [l if li else math.nextafter(l, math.inf),
                          h if hin else math.nextafter(h, -math.inf),
                          l/2+h/2 if math.isfinite(l) and math.isfinite(h) else 0]
            if v in COUNTS or v == 'kickoff_hour_utc':
                first = math.ceil(l) + int(not li and l == math.ceil(l))
                last = math.floor(h) - int(not hin and h == math.floor(h)) if math.isfinite(h) else math.inf
                discrete_possible |= first <= last
                candidates = [first, last, first+1, last-1]
            elif v in DIRECTIONS:
                candidates = [-1, 0, 1]
                discrete_possible |= any((x > l or (li and x == l)) and
                                         (x < h or (hin and x == h)) for x in candidates)
            elif precision is not None:
                scale = 10**precision
                # Only prove an empty grid in a numerically stable bounded
                # window. Outward endpoints preserve borderline DSL floats.
                first = math.ceil(math.nextafter(l*scale, -math.inf)) if abs(l) <= 10**6 else None
                last = math.floor(math.nextafter(h*scale, math.inf)) if abs(h) <= 10**6 else None
                exhaustive = first is not None and last is not None and last-first <= 64
                if exhaustive:
                    candidates = [i/scale for i in range(first, last+1)]
                else:
                    discrete_possible = True
                    if first is not None:
                        candidates += [first/scale, (first+1)/scale]
                    if last is not None:
                        candidates += [last/scale, (last-1)/scale]
                    candidates = [round(x, precision) for x in candidates if math.isfinite(x)]
            for x in candidates:
                if (math.isfinite(x) and (x > l or (li and x == l))
                        and (x < h or (hin and x == h))
                        and all(evaluate(n, {v: x}) is True for n in atoms[v])):
                    witnesses[v].add(x)
        windows[v] = (min(i[0] for i in intervals), max(i[2] for i in intervals))
        if v in DIRECTIONS or v in COUNTS:
            low, high = windows[v]
            windows[v] = (math.ceil(low), math.floor(high) if math.isfinite(high) else high)
        if not witnesses[v]:
            if discrete and not discrete_possible:
                contradiction = True
            else:
                unproven = True

    referenced = set().union(*(variables_used(node) for node in branch))
    rules = _joint_rules(referenced | set(available), literals)
    # Use domain bounds for required variables which have no scalar atoms.
    windows = {v: windows.get(v, _numeric_domain(v)) for v in referenced | set(available)}
    if _violated_rule(windows, rules):
        contradiction = True
    direction_fields = referenced & set((*DIRECTIONS, 'lambda_moves_up', 'lambda_moves_down'))
    fixed = {v: lo for v, (lo, hi) in windows.items() if v in direction_fields and lo == hi}
    if not _directions_valid(fixed):
        contradiction = True
    if not contradiction and not unproven:
        involved = set().union(*(terms.keys() for terms, _ in rules)) | direction_fields
        for v in involved - witnesses.keys():
            lo, hi = windows[v]
            witnesses[v] = {x for x in (lo, hi, 0, 1, 2) if math.isfinite(x) and lo <= x <= hi}
        names = sorted(witnesses)
        defaults = dict(literals)
        defaults.update({v: flag_witness[v] for v in referenced & set(flags)})
        for v in referenced - defaults.keys() - witnesses.keys():
            defaults[v] = False if VARIABLES[v][0] == 'bool' else _default_value(v)
        for values in islice(product(*(sorted(witnesses[v]) for v in names)), 4096):
            env = dict(defaults, **dict(zip(names, values)))
            if (not _violated_rule({v: (env[v], env[v]) for v in involved}, rules)
                    and _directions_valid(env)
                    and all(evaluate(node, env) is True for node in branch)):
                break
        else:
            unproven = True
    return contradiction, unproven, domains


def _design(expr, *, material=True, competition_type=False, available=()):
    """Every explicit path must be satisfiable; signal paths also material."""
    rejected, deferred = _dimensions(expr)
    available = set(available) | variables_used(expr)
    try:
        branches = _logic_paths(expr)
        if not branches:
            rejected.add('CONSTANT_CONDITION')
        for branch in branches:
            contradictory, uncertain, bounds = _path_constraints(branch, competition_type=competition_type, available=available)
            if contradictory:
                rejected.add('CONTRADICTORY_SIGNAL_PATH')
                continue
            if uncertain:
                deferred.add('SATISFIABILITY_UNPROVEN')
            if not material:
                continue
            branch_motion = set().union(*(variables_used(n) & FLOORS.keys() for n in branch
                                          if n.get('op') != 'is_known' and not _domain_tautology(n)))
            if not branch_motion:
                deferred.add('MATERIALITY_UNPROVEN')
            for v in branch_motion:
                if v not in bounds:
                    deferred.add('MATERIALITY_UNPROVEN')
                    continue
                lower, upper, _ = bounds[v]
                lo, hi = lower[0], upper[0]
                floor = FLOORS[v][0]
                if lo >= floor or hi <= -floor:
                    continue
                finite = [abs(x) for x in (lo, hi) if math.isfinite(x)]
                if finite and max(finite) < floor:
                    rejected.add('IMMATERIAL_MOVEMENT')
                else:
                    deferred.add('MATERIAL_DIRECTION_UNPROVEN')
    except ValueError:
        deferred.add('SATISFIABILITY_UNPROVEN')
        if material:
            deferred.add('MATERIALITY_UNPROVEN')
    return rejected, deferred


def raw_plan(plan):
    """Recover the existing submission contract from a canonical/legacy plan."""
    raw = {k: v for k, v in plan.items() if k in REQUIRED | OPTIONAL}
    raw['indicators'] = [{k: i[k] for k in ('name', 'description', 'expr')}
                         for i in plan.get('indicators', [])]
    return raw


def _stratum_cell(variables, selected):
    """B1-only value contract. Never bin missing, malformed or impossible data.

    The shared executor has other consumers; its permissive _bins is deliberately
    not used here. Return field-level exclusion reasons, without coercing values.
    """
    issues, bins = [], {}
    for stratum in selected:
        names = STRATA_VARIABLES[stratum]
        for name in names:
            value = variables.get(name)
            if value is None:
                issues.append({'variable': name, 'reason': 'CONFOUNDER_DATA_MISSING'})
            elif stratum == 'competition_type':
                if type(value) is not bool:
                    issues.append({'variable': name, 'reason': 'CONFOUNDER_VALUE_TYPE_INVALID'})
            elif type(value) not in (int, float):
                issues.append({'variable': name, 'reason': 'CONFOUNDER_VALUE_TYPE_INVALID'})
            elif not _finite(value):
                issues.append({'variable': name, 'reason': 'CONFOUNDER_VALUE_NONFINITE'})
            elif value < 0:
                issues.append({'variable': name, 'reason': 'CONFOUNDER_VALUE_OUT_OF_DOMAIN'})
        if stratum == 'competition_type':
            values = [variables.get(name) for name in names]
            # Partial unknowns cannot hide a proven double assignment.
            if (sum(value is True for value in values) > 1 or
                    (all(type(value) is bool for value in values) and not any(values))):
                issues.append({'variable': stratum, 'reason': 'CONFOUNDER_COMPETITION_CONTRADICTION'})
        if any(issue['variable'] in (*names, stratum) for issue in issues):
            continue
        if stratum == 'lead_bin':
            value = variables['lead_first_min']
            bins[stratum] = 'LT_6H' if value < 360 else '6_24H' if value <= 1440 else 'GT_24H'
        elif stratum == 'line_bin':
            value = variables['total_line_last']
            bins[stratum] = 'LOW' if value <= 2.25 else 'HIGH' if value >= 3.25 else 'MID'
        else:
            bins[stratum] = ('CUP', 'YOUTH_RESERVE', 'LEAGUE_OTHER')[values.index(True)]
    return (None if issues else tuple(bins[s] for s in selected)), issues


# trajectory_variables rounds lead to 0.1 minute: half a quantum = 3 seconds.
# This tolerance applies only to inferred event times, never feature lateness.
LEAD_ROUNDING_SECONDS = 3
IDENTIFIER = re.compile(r'[^\s\x00-\x1f\x7f]{1,256}')
NONNEGATIVE = frozenset(('n_messages', 'n_episodes', 'lead_first_min', 'lead_last_min',
    'span_min', 'max_gap_min', 'total_msgs', 'total_line_first', 'total_line_last',
    'total_line_ups', 'total_line_downs', 'lambda_first', 'lambda_last', 'lambda_abs_path',
    'lambda_sd', 'lambda_moves_up', 'lambda_moves_down', 'lambda_reversals', 'lambda_max_run',
    'total_unobserved_changes', 'x12_msgs', 'x12_reversals', 'ah_msgs', 'ah_line_moves',
    'total_ah_same_msg', 'total_1x2_same_msg'))
COUNTS = frozenset(v for v in NONNEGATIVE if v not in (
    'lead_first_min', 'lead_last_min', 'span_min', 'max_gap_min', 'total_line_first',
    'total_line_last', 'lambda_first', 'lambda_last', 'lambda_abs_path', 'lambda_sd'))


DIRECTIONS = ('lambda_first_dir', 'lambda_last_dir')
PRODUCER_TIME_FIELDS = frozenset(('lead_first_min', 'lead_last_min', 'span_min', 'max_gap_min'))
PRODUCER_PRECISION = dict.fromkeys((
    'lambda_first', 'lambda_last', 'lambda_net', 'lambda_abs_path', 'lambda_sd',
    'lambda_unobserved_net', 'lambda_velocity_h', 'lambda_accel_h',
    'p_home_first', 'p_home_last', 'p_home_net', 'p_draw_net', 'p_away_net',
    'total_line_net', 'ah_line_net',
    'trigger_total_share'), 4)


def _joint_rules(names, literals):
    """Necessary inequalities from trajectory_variables, projected to available fields."""
    rules = []

    def add(positive, negative=(), limit=0):
        terms = {**dict.fromkeys(positive, 1), **dict.fromkeys(negative, -1)}
        # Existentially project omitted fields using the most favourable
        # values allowed by their producer domains. Never assume a missing
        # endpoint or count has a particular value.
        missing = terms.keys() - names
        projected = {v: sign for v, sign in terms.items() if v in names}
        if not projected:
            return
        for v in sorted(missing):
            lo, hi = _numeric_domain(v)
            minimum = lo if terms[v] == 1 else -hi
            if not math.isfinite(minimum):
                return
            limit -= minimum
            if isinstance(limit, float):
                limit = math.nextafter(limit, math.inf)
        rules.append((projected, limit))

    for count in ('total_msgs', 'x12_msgs', 'ah_msgs', 'n_episodes'):
        add((count,), ('n_messages',))
    for counts, market in (
        (('total_line_ups', 'total_line_downs'), 'total_msgs'),
        (('lambda_moves_up', 'lambda_moves_down'), 'total_msgs'),
        (('lambda_reversals',), 'total_msgs'), (('lambda_max_run',), 'total_msgs'),
        (('x12_reversals',), 'x12_msgs'), (('ah_line_moves',), 'ah_msgs'),
        (('total_ah_same_msg',), 'total_msgs'), (('total_ah_same_msg',), 'ah_msgs'),
        (('total_1x2_same_msg',), 'total_msgs'), (('total_1x2_same_msg',), 'x12_msgs'),
    ):
        add(counts, (market,))
        add(counts, ('n_messages',))
    if 'total_unobserved_changes' in names:
        add(('total_unobserved_changes',), ('total_msgs',), -1)
    for feature, minimum in (('lambda_velocity_h', 2), ('lambda_accel_h', 3)):
        if feature in names:
            add((), ('total_msgs',), -minimum)
            add((), ('n_messages',), -minimum)
    for market, prefix in (('total_msgs', 'lambda_'), ('total_msgs', 'total_line_'),
                           ('ah_msgs', 'ah_line_'), ('x12_msgs', 'p_')):
        if any(name.startswith(prefix) for name in names):
            add((), (market,), -1)
    for first, last, net, rounded_values in (
        ('lambda_first', 'lambda_last', 'lambda_net', 0),
        ('total_line_first', 'total_line_last', 'total_line_net', 1),
        ('ah_line_first', 'ah_line_last', 'ah_line_net', 1),
        ('p_home_first', 'p_home_last', 'p_home_net', 0),
    ):
        # Implied lambda and fair 1X2 probabilities already use the same grid
        # before the subtraction. Raw market lines can require final rounding.
        limit = rounded_values / 20000
        add((first, net), (last,), limit)
        add((last,), (first, net), limit)
    probability_changes = ('p_home_net', 'p_draw_net', 'p_away_net')
    add(probability_changes, limit=6 / 20000)
    add((), probability_changes, limit=6 / 20000)
    add(('lead_last_min',), ('lead_first_min',))
    add(('max_gap_min',), ('span_min',))
    for flag, up, down in (('line_up_then_lambda_down', 'total_line_ups', 'lambda_moves_down'),
                           ('line_down_then_lambda_up', 'lambda_moves_up', 'total_line_downs')):
        if literals.get(flag) is True:
            add((), (up,), -1)
            add((), (down,), -1)
    return rules


def _violated_rule(windows, rules):
    for terms, limit in rules:
        bounds = [windows[v][0] if sign == 1 else -windows[v][1]
                  for v, sign in terms.items()]
        if all(math.isfinite(x) for x in bounds):
            # Integer sums have exact bounds. Rounded features allow floating
            # error from the producer's subtraction and this interval sum.
            if all(v in COUNTS for v in terms):
                if sum(bounds) > limit:
                    return True
            else:
                allowance = sum(math.ulp(x) for x in bounds) if len(bounds) > 2 or limit else 0
                try:
                    if math.fsum(bounds) > limit + allowance:
                        return True
                except OverflowError:
                    continue
    return False


def _directions_valid(env):
    for direction in DIRECTIONS:
        value = env.get(direction)
        if ((value == 1 and env.get('lambda_moves_up') == 0)
                or (value == -1 and env.get('lambda_moves_down') == 0)
                or (value == 0 and any(env.get(v, 0) > 0 for v in ('lambda_moves_up', 'lambda_moves_down')))):
            return False
    return True


def _domain_tautology(node):
    op = node.get('op')
    if op not in ('ge', 'le'):
        return False
    left, right = node['args']
    var, bound = (left, right) if op == 'ge' else (right, left)
    if 'var' in var and 'const' in bound:
        return bound['const'] <= _numeric_domain(var['var'])[0]
    if 'const' in var and 'var' in bound:
        return var['const'] >= _numeric_domain(bound['var'])[1]
    return False


def _default_value(name):
    lo, hi = _numeric_domain(name)
    return min(hi, max(lo, 0))


def _arm_separation(signal, control, available):
    """Prove all pairwise intersections empty, or return a bounded diagnostic."""
    try:
        signals, controls = _logic_paths(signal), _logic_paths(control)
    except ValueError:
        return 'CONTROL_DISJOINTNESS_UNPROVEN'
    if len(signals) * len(controls) > 64:
        return 'CONTROL_DISJOINTNESS_UNPROVEN'
    uncertain = False
    for left, right in product(signals, controls):
        impossible, unproven, _ = _path_constraints(left + right, available=available)
        if not impossible:
            if not unproven:
                return 'LOGICAL_GROUP_CONTROL_OVERLAP'
            uncertain = True
    return 'CONTROL_DISJOINTNESS_UNPROVEN' if uncertain else None


def _numeric_domain(name):
    # One catalogue contract for row admission AND logical witnesses. Never
    # prove satisfiability with values that row validation would exclude.
    if name in ('n_messages', 'n_episodes'):
        return 1, math.inf
    if name in ('lambda_first', 'lambda_last'):
        return LAM_MIN, LAM_MAX
    if name == 'lambda_net':
        return round(LAM_MIN-LAM_MAX, 4), round(LAM_MAX-LAM_MIN, 4)
    if name in SIGNAL_DOMAINS:
        return SIGNAL_DOMAINS[name]
    if name in ('p_home_first', 'p_home_last', 'trigger_total_share'):
        return 0, 1
    if name in DIRECTIONS:
        return -1, 1
    if name == 'kickoff_hour_utc':
        return 0, 23
    return (0, math.inf) if name in NONNEGATIVE else (-math.inf, math.inf)


def _excess_precision(value):
    return type(value) is str and re.search(r'[.,]\d{7}', value) is not None


def _time(value):
    """B1 boundary wrapper; UTC conversion can overflow near year 1/9999."""
    if _excess_precision(value):
        return None
    try:
        return utc(value)
    except (OverflowError, TypeError, ValueError):
        return None


def _identifier(value):
    return type(value) is str and IDENTIFIER.fullmatch(value) is not None


def _variable_issues(variables, names):
    issues = []
    for name in sorted(names):
        value = variables.get(name)
        reason = None
        if value is None:
            reason = 'SIGNAL_DATA_MISSING'
        elif VARIABLES[name][0] == 'bool':
            if type(value) is not bool:
                reason = 'SIGNAL_VALUE_TYPE_INVALID'
        elif type(value) not in (int, float):
            reason = 'SIGNAL_VALUE_TYPE_INVALID'
        else:
            finite = _finite(value)
            if not finite:
                reason = 'SIGNAL_VALUE_NONFINITE'
            elif ((not _numeric_domain(name)[0] <= value <= _numeric_domain(name)[1])
                  or (name in COUNTS and value != int(value))
                  or (name in ('lambda_first_dir', 'lambda_last_dir') and value not in (-1, 0, 1))
                  or (name == 'kickoff_hour_utc' and value != int(value))
                  or (name in PRODUCER_PRECISION and round(value, PRODUCER_PRECISION[name]) != value)):
                reason = 'SIGNAL_VALUE_OUT_OF_DOMAIN'
        if reason:
            issues.append({'variable': name, 'reason': reason})
    return issues


def _support_metrics(cells, eligible_cells, period_cells):
    """Preserve all pregame-assigned cells, including those emptied by attrition."""
    rows = []
    for cell in sorted(cells):
        pre, eligible = cells[cell], eligible_cells.get(cell, Counter())
        periods = period_cells.get(cell, Counter())
        rows.append({'cell': list(cell),
                     'pregame': {s: pre[s] for s in ('group', 'control')},
                     'eligible': {s: eligible[s] for s in ('group', 'control')},
                     'oos': {p+'_'+s: periods[p+'_'+s] for p in ('train', 'test') for s in ('group', 'control')}})
    return rows


def _prior_identity(prior_plans):
    if type(prior_plans) not in (tuple, list):
        raise ValueError('INVALID_PRIOR_PLANS')
    result = []
    for prior in prior_plans:
        if type(prior) is not dict:
            raise ValueError('INVALID_PRIOR_PLAN')
        used = prior.get('variables_used', [])
        if type(used) not in (tuple, list) or any(type(v) is not str for v in used):
            raise ValueError('INVALID_PRIOR_VARIABLES')
        entry = {key: prior.get(key) for key in ('fingerprint', 'outcome')}
        if any(value is not None and type(value) is not str for value in entry.values()):
            raise ValueError('INVALID_PRIOR_IDENTITY')
        result.append(dict(entry, variables_used=sorted(set(used))))
    return sorted(result, key=sha)


def _request_hash(plans, metadata, design, prior_plans):
    try:
        payload = {'contract': VERSION, 'plans': plans, 'metadata': metadata,
                   'design': design, 'prior_plans': _prior_identity(prior_plans)}
        _json_input(payload)
        return sha(payload)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return None


def evaluate_quality(plan, metadata, *, design=None, prior_plans=()):
    """Evaluate one canonical plan using the same identity contract as shadow."""
    input_hash = _request_hash([plan], metadata, design, prior_plans)
    return _evaluate_quality(plan, metadata, design, prior_plans, input_hash)


def _evaluate_quality(plan, metadata, design, prior_plans, input_hash):
    """Diagnostic admission only; strict pregame inputs precede membership.

    Raw assignment never uses FT/baseline availability. Pregame support requires
    known chronology; eligible support additionally requires baseline and verified
    FT. The same cells must have >=2 per arm globally AND in train/test. Exclusions
    report attrition, not a correction for missing-outcome selection bias.
    """
    reject, defer = set(), set()
    if input_hash is None:
        reject.add('INPUT_IDENTITY_UNAVAILABLE')
    rows_ok = type(metadata) is list
    counts = Counter(rows=len(metadata) if rows_ok else 0, group=0, control=0, unknown=0,
                     overlap=0, unassigned=0, ft=0, baseline=0, group_eligible=0, control_eligible=0,
                     group_pregame=0, control_pregame=0, rows_excluded=0)
    metrics = dict(counts, accounting_complete=False)
    exclusions, strata_exclusions, safe = [], [], []
    pregame_days = set()
    cells, eligible_cells, period_cells = {}, {}, {}
    try:
        canonical = validate_plan(raw_plan(plan))
        if canonical['fingerprint'] != plan.get('fingerprint'):
            reject.add('NONCANONICAL_PLAN')
    except (PlanError, KeyError, TypeError, ValueError, AttributeError, OverflowError):
        canonical = None
        reject.add('QUALITY_INPUT_INVALID')
    if not rows_ok:
        reject.add('QUALITY_INPUT_INVALID')
    if canonical and rows_ok:
        expr = inline(canonical['condition'], canonical['indicators'])
        used = set(canonical['variables_used'])
        temporal_used = used | set().union(*(set(STRATA_VARIABLES[s]) for s in canonical['confounders']))
        r, d = _design(expr, available=temporal_used)
        reject |= r
        defer |= d
        ctrl = canonical.get('control_condition')
        if ctrl:
            ctrl = inline(ctrl, canonical['indicators'])
            r, d = _design(ctrl, material=False, available=temporal_used)
            reject |= r
            defer |= d
            if expr == ctrl:
                reject.add('CONTROL_EQUALS_CONDITION')
            separation = _arm_separation(expr, ctrl, temporal_used)
            if separation:
                (reject if separation == 'LOGICAL_GROUP_CONTROL_OVERLAP' else defer).add(separation)
        narrative = ' '.join(str(canonical.get(k, '')) for k in
                             ('question', 'hypothesis', 'rationale', 'alternative_explanations'))
        if UNAVAILABLE.search(narrative):
            reject.add('UNOBSERVED_CONCEPT')
        if not used:
            reject.add('NO_OBSERVABLE_SIGNAL')
        base = OUTCOMES[canonical['market']][canonical['outcome']]
        if design is None:
            design = {}
        elif type(design) is not dict:
            reject.add('QUALITY_INPUT_INVALID')
            design = {}
        frozen = _time(design.get('frozen_at'))
        freeze_unusable = design.get('frozen_at') is not None and frozen is None
        discovery_precision_invalid = (design.get('threshold_origin') == 'DISCOVERY'
                                       and _excess_precision(design.get('discovery_end')))
        if freeze_unusable:
            reject.add('DESIGN_FREEZE_INVALID')
        if discovery_precision_invalid:
            reject.add('TIMESTAMP_PRECISION_UNSUPPORTED')
        if design.get('threshold_origin') not in ('APRIORI', 'DISCOVERY') or not frozen:
            defer.add('THRESHOLD_PROVENANCE_MISSING')
        trajectory_rules = _joint_rules(temporal_used, {})
        contextual_rules = {flag: _joint_rules(temporal_used, {flag: True})[len(trajectory_rules):]
                            for flag in ('line_up_then_lambda_down', 'line_down_then_lambda_up')
                            if flag in temporal_used}
        # Exclude every occurrence of a duplicate, so row order cannot select a winner.
        key_counts = Counter(r.get('match_key') for r in metadata
                             if type(r) is dict and _identifier(r.get('match_key')))
        forbidden = {'outcome', 'score', 'scores', 'home', 'away', 'profit', 'gains'}
        for index, row in enumerate(metadata):
            issues = []

            def issue(variable, reason, *, missing=False):
                (defer if missing else reject).add(reason)
                entry = {'variable': variable, 'reason': reason}
                if entry not in issues:
                    issues.append(entry)

            if type(row) is not dict:
                issue('row', 'METADATA_ROW_INVALID')
                counts['unknown'] += 1
                counts['rows_excluded'] += 1
                exclusions.append({'row_index': index, 'issues': issues})
                continue
            try:
                _json_input(row)
            except (TypeError, ValueError, OverflowError, RecursionError):
                issue('row', 'METADATA_ROW_NOT_CANONICAL_JSON')
            if freeze_unusable:
                issue('design.frozen_at', 'DESIGN_FREEZE_INVALID')
            if discovery_precision_invalid:
                issue('design.discovery_end', 'TIMESTAMP_PRECISION_UNSUPPORTED')
            key = row.get('match_key')
            identity_ok = _identifier(key)
            if not identity_ok:
                issue('match_key', 'MATCH_ID_INVALID')
            elif key_counts[key] != 1:
                issue('match_key', 'DUPLICATE_MATCH_UNIT')
                identity_ok = False
            for name in sorted(forbidden & set(row)):
                issue(name, 'OUTCOME_METADATA_FORBIDDEN')
            variables = row.get('variables')
            variables_ok = type(variables) is dict
            if not variables_ok:
                issue('variables', 'VARIABLES_METADATA_INVALID')
                variables = {}
            signal_issues = _variable_issues(variables, used)
            for entry in signal_issues:
                issue(**entry, missing=entry['reason'] == 'SIGNAL_DATA_MISSING')
            invalid_variables = {entry['variable'] for entry in signal_issues}
            invalid_variables.update(entry['variable'] for entry in
                                     _variable_issues(variables, temporal_used - used))
            known_values = {v: variables[v] for v in temporal_used - invalid_variables}
            rules = trajectory_rules + [rule for flag, additional in contextual_rules.items()
                                        if known_values.get(flag) is True for rule in additional]
            flags = [known_values[v] for v in STRATA_VARIABLES['competition_type'] if v in known_values]
            if sum(flags) > 1 or (len(flags) == 3 and not any(flags)):
                issue('competition_type', 'COMPETITION_FLAGS_INCONSISTENT')
            if (_violated_rule({v: (x, x) for v, x in known_values.items()},
                               ((terms, limit) for terms, limit in rules if terms.keys() <= known_values.keys()))
                    or not _directions_valid(known_values)):
                issue('variables', 'TRAJECTORY_INVARIANTS_VIOLATED')
            cell, strata_issues = _stratum_cell(variables, canonical['confounders'])
            if strata_issues:
                counts['strata_excluded'] += 1
                for entry in strata_issues:
                    issue(**entry, missing=entry['reason'] == 'CONFOUNDER_DATA_MISSING')
                strata_exclusions.append({'match_key': key if _identifier(key) else None,
                                          'issues': strata_issues})
                defer.add('COMMON_STRATUM_SUPPORT_MISSING')
            for field in ('decision_at', 'kickoff_utc', 'feature_frozen_at'):
                if _excess_precision(row.get(field)):
                    issue(field, 'TIMESTAMP_PRECISION_UNSUPPORTED')
            dec, ko = _time(row.get('decision_at')), _time(row.get('kickoff_utc'))
            if dec is None or ko is None:
                issue('decision_at/kickoff_utc', 'DECISION_WINDOW_UNPROVEN', missing=True)
            elif dec >= ko:
                issue('decision_at', 'POST_KICKOFF_INFORMATION')
            if frozen and dec and frozen > dec:
                issue('design.frozen_at', 'DESIGN_NOT_FROZEN_BEFORE_DECISION')
            times = row.get('feature_observed_at')
            if times is None:
                times = {}
            elif type(times) is not dict:
                issue('feature_observed_at', 'FEATURE_METADATA_INVALID')
                times = {}
            ff = _time(row.get('feature_frozen_at'))
            ids = row.get('source_event_ids')
            ids_valid = (type(ids) is list and bool(ids) and all(_identifier(v) for v in ids)
                         and len(set(ids)) == len(ids))
            if ids is not None and not ids_valid:
                issue('source_event_ids', 'PROVENANCE_IDENTIFIERS_INVALID')
            if not ids_valid or ff is None or dec is None or ko is None:
                issue('feature_frozen_at/source_event_ids', 'FEATURE_FREEZE_UNPROVEN', missing=True)
            if ff and ((dec and ff > dec) or (ko and ff >= ko)):
                issue('feature_frozen_at', 'POST_DECISION_FEATURE_FREEZE')
            for v in sorted(temporal_used):
                if _excess_precision(times.get(v)):
                    issue(v, 'TIMESTAMP_PRECISION_UNSUPPORTED')
                t = _time(times.get(v))
                if t is None:
                    issue(v, 'FEATURE_WINDOW_UNPROVEN', missing=True)
                else:
                    if (dec and t > dec) or (ko and t >= ko):
                        issue(v, 'POST_KICKOFF_INFORMATION')
                    if ff and t > ff:
                        issue(v, 'OBSERVATION_AFTER_FREEZE')
            if ko and 'kickoff_hour_utc' in known_values and known_values['kickoff_hour_utc'] != ko.hour:
                issue('kickoff_hour_utc', 'KICKOFF_HOUR_MISMATCH')
            for lead, label in (('lead_first_min', 'FIRST'), ('lead_last_min', 'LAST')):
                if lead not in known_values or ko is None:
                    continue
                try:
                    inferred = ko - timedelta(minutes=known_values[lead])
                    tolerance = timedelta(seconds=LEAD_ROUNDING_SECONDS)
                    for boundary, time in (('decision_at', dec), ('feature_frozen_at', ff),
                                           ('feature_observed_at', _time(times.get(lead))),
                                           ('kickoff_utc', ko)):
                        if time and inferred > time and inferred-time > tolerance:
                            issue(lead, 'LEAD_' + label + '_AFTER_' + boundary.upper())
                except (OverflowError, ValueError):
                    issue(lead, 'LEAD_TIMESTAMP_OUT_OF_RANGE')
            # Validate derived values as well: IS_KNOWN must not turn undefined
            # arithmetic into an eligible complement/control observation.
            derived_issues = []
            if variables_ok and not signal_issues:
                env = dict(variables)
                for indicator in canonical['indicators']:
                    value = evaluate(indicator['expr'], env)
                    env[indicator['name']] = value
                    if value is None:
                        derived_issues.append(indicator['name'])
                def check_expression(node):
                    for arg in node.get('args', []):
                        check_expression(arg)
                    if node.get('op') and evaluate(node, env) is None:
                        derived_issues.append('condition/control_condition')
                check_expression(expr)
                if ctrl:
                    check_expression(ctrl)
            for variable in sorted(set(derived_issues)):
                issue(variable, 'SIGNAL_EXPRESSION_UNKNOWN', missing=True)
            # No invalid/unknown signal operand reaches the coercive shared DSL.
            # Stratification/chronology defects preserve a computable raw arm.
            g, c = None, None
            if variables_ok and identity_ok and not signal_issues and not derived_issues:
                try:
                    g, c = membership(canonical, {'variables': variables})
                except (TypeError, ValueError, OverflowError):
                    issue('condition/control_condition', 'SIGNAL_EVALUATION_INVALID')
            side = None
            if g is None:
                counts['unknown'] += 1
                if not signal_issues:
                    issue('condition/control_condition', 'SIGNAL_RESULT_UNKNOWN', missing=True)
            elif g == 'OVERLAP':
                counts['overlap'] += 1
                issue('condition/control_condition', 'GROUP_CONTROL_OVERLAP')
            elif not g and not c:
                counts['unassigned'] += 1
                issues.append({'variable': 'condition/control_condition', 'reason': 'ARM_UNASSIGNED'})
            else:
                side = 'group' if g else 'control'
                counts[side] += 1
            # FT and baseline are deliberately checked AFTER raw arm assignment.
            pregame_ok = not issues
            if side and cell is not None:
                support = cells.setdefault(cell, Counter())
                if pregame_ok:
                    support[side] += 1
                    counts[side + '_pregame'] += 1
                    pregame_days.add(ko.date().isoformat())
            elif side:
                counts[side + '_strata_excluded'] += 1
            for flag in ('ft_verified', 'ft_source_verified'):
                if row.get(flag) is not None and type(row[flag]) is not bool:
                    issue(flag, 'AVAILABILITY_METADATA_INVALID')
            ft = row.get('ft_verified') is True and row.get('ft_source_verified') is True
            baselines = row.get('baseline_available')
            if baselines is None:
                baselines = {}
            elif type(baselines) is not dict:
                issue('baseline_available', 'AVAILABILITY_METADATA_INVALID')
                baselines = {}
            if base is not None and baselines.get(base) is not None and type(baselines[base]) is not bool:
                issue('baseline_available.' + base, 'AVAILABILITY_METADATA_INVALID')
            baseline = base is None or baselines.get(base) is True
            if side:
                counts['ft'] += int(ft)
                counts[side + '_ft_present'] += int(row.get('ft_verified') is True)
                counts[side + '_ft_verified_source'] += int(ft)
                counts[side + '_baseline'] += int(baseline)
                counts['baseline'] += int(baseline)
            if not ft:
                issue('ft_verified/ft_source_verified', 'VERIFIED_FT_PROVENANCE_MISSING', missing=True)
            if not baseline:
                issue('baseline_available', 'BASELINE_MISSING', missing=True)
            if side and not issues:
                counts[side + '_eligible'] += 1
                eligible_cells.setdefault(cell, Counter())[side] += 1
                safe.append((ko.date().isoformat(), side, cell))
            else:
                counts['rows_excluded'] += 1
            if issues:
                record = {'match_key': key, 'issues': sorted(issues, key=lambda x: (x['variable'], x['reason']))}
                if not _identifier(key):
                    record = {'row_index': index, 'issues': record['issues']}
                exclusions.append(record)
        if not metadata:
            defer.add('NO_METADATA')
        if metadata and counts['unknown'] == 0 and min(counts['group'], counts['control']) == 0:
            reject.add('TRIVIAL_PARTITION')
        if min(counts['group_eligible'], counts['control_eligible']) < MIN_N:
            defer.add('MIN_N_NOT_MET')
        # Freeze the period boundary from valid pregame assignments, before
        # FT/baseline attrition. Missing outcomes cannot move the holdout.
        days = sorted(pregame_days)
        cut = days[min(len(days)-1, max(1, int(len(days)*OOS_TRAIN_SHARE)))] if len(days) >= 4 else None
        oos = Counter({'train_group': 0, 'train_control': 0, 'test_group': 0, 'test_control': 0})
        if cut:
            for day, side, cell in safe:
                name = ('train_' if day < cut else 'test_') + side
                oos[name] += 1
                period_cells.setdefault(cell, Counter())[name] += 1
        if not cut or min(oos.values()) < 5:
            defer.add('CHRONOLOGICAL_OOS_INSUFFICIENT')
        if design.get('threshold_origin') == 'DISCOVERY':
            end = _time(design.get('discovery_end'))
            if not end or not frozen or not cut:
                defer.add('DISCOVERY_BOUNDARY_UNPROVEN')
            elif end > frozen or end.date().isoformat() >= cut:
                reject.add('DISCOVERY_HOLDOUT_CONTAMINATION')
        support = _support_metrics(cells, eligible_cells, period_cells)
        pre_support = bool(support) and all(min(c['pregame'].values()) >= 2 for c in support)
        eligible_support = bool(support) and all(min(c['eligible'].values()) >= 2 for c in support)
        period_support = bool(cut and support) and all(min(c['oos'].values()) >= 2 for c in support)
        if not pre_support or not eligible_support:
            defer.add('COMMON_STRATUM_SUPPORT_MISSING')
        if not period_support:
            defer.add('COMMON_STRATUM_PERIOD_SUPPORT_MISSING')
        try:
            prior_plans = _prior_identity(prior_plans)
        except ValueError:
            reject.add('QUALITY_INPUT_INVALID')
            prior_plans = []
        duplicates = sum(p.get('fingerprint') == canonical['fingerprint'] for p in prior_plans)
        near = sum(p.get('outcome') == canonical['outcome'] and
                   set(p.get('variables_used', ())) == used and
                   p.get('fingerprint') != canonical['fingerprint'] for p in prior_plans)
        if duplicates:
            reject.add('DUPLICATE_QUESTION')
        if near:
            defer.add('NEAR_DUPLICATE_REVIEW')
        metrics = dict(counts, accounting_complete=True, coverage=(counts['group']+counts['control'])/counts['rows'] if counts['rows'] else 0,
                       split_day=cut, oos=dict(oos), duplicates=duplicates, near_duplicates=near,
                       common_support={'pregame': pre_support, 'eligible': eligible_support,
                                       'by_period': period_support, 'cells': support},
                       attrition={s: {'assigned': counts[s], 'pregame': counts[s+'_pregame'],
                                     'eligible': counts[s+'_eligible'],
                                     'excluded_after_assignment': counts[s]-counts[s+'_eligible'],
                                     'ft_source_missing': counts[s]-counts[s+'_ft_verified_source']}
                                  for s in ('group', 'control')})
        if strata_exclusions:
            metrics['strata_exclusions'] = sorted(strata_exclusions, key=lambda x: (x['match_key'] or '', sha(x['issues'])))
        if exclusions:
            metrics['exclusions'] = sorted(exclusions, key=lambda x: (x.get('match_key', ''), x.get('row_index', -1), sha(x['issues'])))
    if input_hash is None:
        # Raw accounting is retained. Results from unaffected rows may explain
        # exclusions, but cannot constitute eligible support for this request.
        for name in ('group_eligible', 'control_eligible', 'oos', 'common_support'):
            if name in metrics:
                metrics.setdefault('unidentified_diagnostics', {})[name] = metrics.pop(name)
        metrics.update(group_eligible=0, control_eligible=0)
        diagnostic = metrics['unidentified_diagnostics']
        if 'oos' in diagnostic:
            metrics['oos'] = dict.fromkeys(diagnostic['oos'], 0)
            metrics['common_support'] = {'pregame': False, 'eligible': False,
                                         'by_period': False, 'cells': []}
        if 'attrition' in metrics:
            metrics['unidentified_diagnostics']['attrition'] = metrics.pop('attrition')
    design_status = 'REJECTED' if reject else 'INSUFFICIENT_DATA' if defer else 'SCIENTIFICALLY_TESTABLE'
    defer.add('TRUSTED_PROVENANCE_ADAPTER_UNAVAILABLE')
    return {'version': VERSION, 'quality_status': 'REJECTED' if reject else 'INSUFFICIENT_DATA',
            'design_quality_status': design_status, 'reasons': sorted(reject | defer),
            'metrics': metrics, 'diagnostic_only': True, 'promotion_eligible': False,
            'alternative_explanations': 'TEXT_NOT_VERIFIED',
            'confounding_scope': 'COMMON_SUPPORT_REQUIRED_NOT_CAUSAL_PROOF',
            'scientific_status': 'EXPLORATORY_NOT_VALIDATED'}


def shadow_report(plans, metadata, *, design=None, prior_plans=()):
    """Zero executions/writes; unhashable input fails closed without fake hashes.

    A canonical JSON hash identifies the exact supplied order and values. NaN,
    unsupported objects or cycles have no such identity; retain diagnostics for
    every auditable row but reject all cards and expose input_sha256=None.
    """
    input_hash = _request_hash(plans, metadata, design, prior_plans)
    identity_reason = 'INPUT_IDENTITY_UNAVAILABLE' if input_hash is None else None
    received = len(plans) if type(plans) is list else None
    if type(metadata) is not list:
        identity_reason = identity_reason or 'QUALITY_INPUT_INVALID'
    if type(plans) is not list:
        plans = []
        identity_reason = 'QUALITY_INPUT_INVALID'
    cards, valid = [], 0
    for raw in plans:
        try:
            p = validate_plan(raw_plan(raw) if type(raw) is dict and 'fingerprint' in raw else raw)
        except (PlanError, TypeError, AttributeError, KeyError, ValueError, OverflowError):
            cards.append({'structural_status': 'REJECTED', 'reasons': ['STRUCTURAL_INVALID']})
            continue
        valid += 1
        submitted = raw if type(raw) is dict and 'fingerprint' in raw else p
        card = dict(fingerprint=p['fingerprint'], structural_status='STRUCTURALLY_VALID',
                    **_evaluate_quality(submitted, metadata, design, prior_plans, input_hash))
        if identity_reason:
            card.update(quality_status='REJECTED', design_quality_status='REJECTED',
                        reasons=sorted(set(card['reasons']) | {identity_reason}))
        cards.append(card)
    statuses = Counter(c.get('quality_status') for c in cards if 'quality_status' in c)
    return {'mode': VERSION, 'input_sha256': input_hash,
            'report_status': 'REJECTED' if identity_reason else 'DIAGNOSTIC_ONLY',
            'reasons': [identity_reason] if identity_reason else [],
            'funnel': {'received': received, 'structurally_valid': valid,
                       'before_eligible_by_syntax': valid, 'after_eligible': 0,
                       'quality': dict(sorted(statuses.items())), 'executed': 0},
            'agenda': cards, 'validated': [], 'memory_written': False}
