"""Versioned producer contract used only by the B1 diagnostic.

Necessary constraints can prove impossibility. Only replaying concrete pregame
messages through the unchanged producer can prove existence. Bounds or failed
bounded searches never prove existence or impossibility, respectively.
"""
from __future__ import annotations

import math
import json
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from .market_math import LAM_MIN, LAM_MAX, fair_over_share, implied_lambda, valid_line, valid_price
from .research_dataset import VARIABLES, LAMBDA_EPS, trajectory_variables
from .research_dsl import evaluate, variables_used
from .timeline import match_timeline, number, message_number

CONTRACT_VERSION = 'B1_PRODUCER_1'
SAT, UNSAT, UNKNOWN = 'SAT', 'UNSAT', 'UNKNOWN'
SIGNAL_DOMAINS = {'lambda_abs_path': (0, math.inf),
                  **{v: (-.9975, .9975) for v in ('p_home_net', 'p_draw_net', 'p_away_net')}}
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


def variable_unit(v):
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


VARIABLE_UNITS = {v: variable_unit(v) for v in VARIABLES}


@lru_cache(maxsize=128)
def _numeric_domain(name):
    # One catalogue contract for row admission AND logical witnesses. Never
    # prove satisfiability with values that row validation would exclude.
    if name in ('n_messages', 'n_episodes'):
        return 1, math.inf
    if name in ('total_line_first', 'total_line_last'):
        return -math.inf, math.inf
    if name in ('lambda_first', 'lambda_last'):
        return LAM_MIN, LAM_MAX
    if name == 'lambda_net':
        return round(LAM_MIN-LAM_MAX, 4), round(LAM_MAX-LAM_MIN, 4)
    if name == 'lambda_sd':
        return 0, round((LAM_MAX-LAM_MIN)/2, 4)
    if name in SIGNAL_DOMAINS:
        return SIGNAL_DOMAINS[name]
    if name in ('p_home_first', 'p_home_last'):
        return .0005, .998
    if name == 'trigger_total_share':
        return 0, 1
    if name == 'total_overround_last':
        return -.998, 1
    if name in DIRECTIONS:
        return -1, 1
    if name == 'kickoff_hour_utc':
        return 0, 23
    return (0, math.inf) if name in NONNEGATIVE else (-math.inf, math.inf)


def _make_joint_rules(names, literals):
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


@lru_cache(maxsize=512)
def _cached_rules(names, flags):
    return _make_joint_rules(set(names), dict.fromkeys(flags, True))


def _joint_rules(names, literals):
    return _cached_rules(tuple(sorted(names)), tuple(v for v in
        ('line_up_then_lambda_down', 'line_down_then_lambda_up') if literals.get(v) is True))


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



# All time summaries are rounded independently, to a tenth of a minute. These
# closed outward intervals deliberately include both tie endpoints (Python's
# half-even rounding and binary float evaluation select a subset of them).
TIME_HALF_QUANTUM = .05
VALUE_HALF_QUANTUM = .00005


def _interval(windows, name):
    return windows.get(name, _numeric_domain(name))


def _time_interval(windows, name):
    lo, hi = _interval(windows, name)
    return max(0, lo-TIME_HALF_QUANTUM), hi+TIME_HALF_QUANTUM


def _disjoint(a, b, allowance=1e-10):
    return a[0] > b[1]+allowance or b[0] > a[1]+allowance


def temporal_impossible(windows):
    first, last = (_time_interval(windows, v) for v in ('lead_first_min', 'lead_last_min'))
    span, gap = (_time_interval(windows, v) for v in ('span_min', 'max_gap_min'))
    nlo, nhi = _interval(windows, 'n_messages')
    if _disjoint((first[0]-last[1], first[1]-last[0]), span):
        return True
    if nhi == 1:
        if _disjoint(first, last) or span[0] > 0 or gap[0] > 0:
            return True
    elif math.isfinite(nhi) and span[0] > (nhi-1)*gap[1]+1e-9:
        return True
    if gap[0] > span[1]+1e-9:
        return True
    # Total messages are a subset of the timeline; its positive duration is
    # bounded ABOVE by the complete span, in hours. Velocity uses rounded net.
    net, velocity = (_interval(windows, v) for v in ('lambda_net', 'lambda_velocity_h'))
    if 'lambda_velocity_h' in windows:
        vmax = max(abs(velocity[0]), abs(velocity[1])) + VALUE_HALF_QUANTUM
        nmin = max(net[0], -net[1], 0)
        if nmin > vmax*span[1]/60 + 1e-10:
            return True
        if net[0] > 0 and velocity[1] < -VALUE_HALF_QUANTUM:
            return True
        if net[1] < 0 and velocity[0] > VALUE_HALF_QUANTUM:
            return True
    return False


SEQUENCE_NAMES = ('total_msgs', 'n_messages', 'lambda_moves_up', 'lambda_moves_down',
                  'lambda_reversals', 'lambda_max_run', *DIRECTIONS)


def _inside(windows, name, value):
    lo, hi = _interval(windows, name)
    return lo <= value <= hi


@lru_cache(maxsize=8192)
def _sequences(key, cap):
    """Complete finite sign model; zeros do not interrupt runs in the producer.

    Enumerate run counts/lengths, not 3**n strings. With fixed up/down counts,
    max_run=m exists iff each direction can be split into its alternating runs
    with lengths in [1,m], and at least one run can attain m.
    """
    windows = dict(key)
    maximum = min(_interval(windows, 'total_msgs')[1], _interval(windows, 'n_messages')[1],
                  _interval(windows, 'lambda_moves_up')[1]+_interval(windows, 'lambda_moves_down')[1])
    limit = min(cap, int(maximum)) if math.isfinite(maximum) else cap
    found = []
    for k in range(limit+1):
        for up in range(k+1):
            down = k-up
            if not _inside(windows, 'lambda_moves_up', up) or not _inside(windows, 'lambda_moves_down', down):
                continue
            if k == 0:
                if all(_inside(windows, v, 0) for v in (*DIRECTIONS, 'lambda_reversals', 'lambda_max_run')):
                    found.append(())
                continue
            for first in (-1, 1):
                for r in range(k):
                    last = first if r % 2 == 0 else -first
                    if (not _inside(windows, 'lambda_first_dir', first)
                            or not _inside(windows, 'lambda_last_dir', last)
                            or not _inside(windows, 'lambda_reversals', r)):
                        continue
                    nr = r+1
                    ru = (nr+1)//2 if first == 1 else nr//2
                    rd = nr-ru
                    for m in range(1, k+1):
                        if not _inside(windows, 'lambda_max_run', m):
                            continue
                        if not (ru <= up <= ru*m and rd <= down <= rd*m):
                            continue
                        attainable = [d for d, count, runs in ((1, up, ru), (-1, down, rd))
                                      if runs and count >= m+runs-1]
                        if not attainable:
                            continue
                        lengths = [1]*nr
                        directions = [first*(-1)**i for i in range(nr)]
                        chosen = directions.index(attainable[0])
                        lengths[chosen] = m
                        for d, count in ((1, up), (-1, down)):
                            remaining = count-sum(l for l, direction in zip(lengths, directions) if direction == d)
                            for i, direction in enumerate(directions):
                                if direction == d:
                                    take = min(remaining, m-lengths[i])
                                    lengths[i] += take
                                    remaining -= take
                        found.append(tuple(d for d, length in zip(directions, lengths) for _ in range(length)))
    exhaustive = math.isfinite(maximum) and maximum <= cap
    return tuple(found), exhaustive


def sequence_models(windows, cap=12):
    key = tuple((v, tuple(windows[v])) for v in SEQUENCE_NAMES if v in windows)
    return _sequences(key, cap)


def sequence_impossible(windows):
    # Unbounded necessary consequences are checked before the finite search.
    up, down, run, rev = (_interval(windows, v) for v in
                          ('lambda_moves_up', 'lambda_moves_down', 'lambda_max_run', 'lambda_reversals'))
    max_moves = min(_interval(windows, 'n_messages')[1], _interval(windows, 'total_msgs')[1], up[1]+down[1])
    min_moves = up[0]+down[0]
    if min_moves > max_moves or run[0] > max_moves or rev[0] > max(0, max_moves-1):
        return True
    if (run[1] == 0 and min_moves > 0) or (max_moves == 0 and (run[0] > 0 or rev[0] > 0)):
        return True
    if rev[0] > 0 and (up[1] == 0 or down[1] == 0):
        return True
    for name in DIRECTIONS:
        lo, hi = _interval(windows, name)
        if (lo == hi == 0 and min_moves > 0) or (lo > 0 and up[1] == 0) or (hi < 0 and down[1] == 0):
            return True
    if min_moves > run[1]*(rev[1]+1):
        return True
    models, exhaustive = sequence_models(windows)
    return exhaustive and not models


def producer_impossible(windows, literals=None):
    """Necessary conditions ONLY. False means no contradiction proved, not SAT."""
    literals = literals or {}
    rules = _joint_rules(set(windows), literals)
    if _violated_rule(windows, rules) or temporal_impossible(windows) or sequence_impossible(windows):
        return True
    b = lambda name: _interval(windows, name)
    mlo, mhi = b('total_msgs')
    nlo, nhi = b('n_messages')
    mhi = min(mhi, nhi)
    if mhi < 0 or nhi < 1:
        return True
    # Inclusion-exclusion: two subsets of n messages cannot have an arbitrarily
    # small intersection. The upper bounds are in _joint_rules.
    for market, intersection in (('ah_msgs', 'total_ah_same_msg'), ('x12_msgs', 'total_1x2_same_msg')):
        if mlo+b(market)[0]-nhi > b(intersection)[1]:
            return True
    # trigger_total_share is the rounded ratio of an INTEGER trigger count to n.
    # Checking n exhaustively is an impossibility proof only for a bounded range.
    if 'trigger_total_share' in windows and math.isfinite(nhi) and nhi-nlo <= 256:
        share = b('trigger_total_share')
        possible = False
        for n in range(max(1, math.ceil(nlo)), math.floor(nhi)+1):
            low = max(0, math.ceil((share[0]-.00005)*n-1e-10))
            high = min(n, math.floor((share[1]+.00005)*n+1e-10))
            if low <= high:
                possible = True
                break
        if not possible:
            return True
    net, unobs, path, sd = (b(v) for v in ('lambda_net', 'lambda_unobserved_net', 'lambda_abs_path', 'lambda_sd'))
    changes = b('total_unobserved_changes')
    width = LAM_MAX-LAM_MIN
    if max(unobs[0], -unobs[1], 0) > changes[1]*width+.00005+1e-10:
        return True
    if path[0] > mhi*width+.00005+1e-10:
        return True
    observed = net[0]-unobs[1], net[1]-unobs[0]
    if max(observed[0], -observed[1], 0) > path[1]+1e-9:
        return True
    up, down = b('lambda_moves_up'), b('lambda_moves_down')
    # Floating subtraction can classify a difference whose grid value is .05
    # as > .05. Never invent an exact .0501 lower bound for counted movements.
    eps = LAMBDA_EPS-1e-12
    if path[1]+.00005 < (up[0]+down[0])*eps:
        return True
    if math.isfinite(mhi):
        if path[0] > 2*mhi*(sd[1]+.00005)+.00005+1e-9:
            return True
        if max(net[0], -net[1], 0) > 2*math.sqrt(mhi)*(sd[1]+.00005)+1e-9:
            return True
        zeros_max = max(0, mhi-up[0]-down[0])
        obslo = up[0]*eps-down[1]*width-zeros_max*(LAMBDA_EPS+1e-12)
        obshi = up[1]*width-down[0]*eps+zeros_max*(LAMBDA_EPS+1e-12)
        if _disjoint(observed, (obslo, obshi)):
            return True
    if mhi == 1:
        for field in DIRECTIONS:
            direction = b(field)
            if direction[0] >= 1 and net[1] < LAMBDA_EPS-1e-12:
                return True
            if direction[1] <= -1 and net[0] > -LAMBDA_EPS+1e-12:
                return True
            if direction == (0, 0) and (net[0] > LAMBDA_EPS+1e-12 or net[1] < -LAMBDA_EPS-1e-12 or path[0] > LAMBDA_EPS+.00005):
                return True
        if not unobs[0] <= 0 <= unobs[1]:
            return True
        # The two observed lambda endpoints give sd=abs(net)/2 and path=abs(net).
        absnet = (max(net[0], -net[1], 0), max(abs(net[0]), abs(net[1])))
        if _disjoint(path, absnet, .00005) or _disjoint(sd, (absnet[0]/2, absnet[1]/2), .000051):
            return True
    for flag in ('line_up_then_lambda_down', 'line_down_then_lambda_up'):
        if literals.get(flag) and mhi < 2:
            return True
    return False


def value_valid(name, value):
    # Never key a scientific verdict by object identity or an unvalidated custom
    # hash. Include the exact scalar type: True must not reuse the verdict for 1.
    if type(value) not in (int, float, bool, type(None)):
        return False
    return _value_valid_cached(name, type(value), value)


@lru_cache(maxsize=8192)
def _value_valid_cached(name, kind, value):
    if value is None:
        return True  # Availability is checked separately for required features.
    if VARIABLES[name][0] == 'bool':
        return type(value) is bool
    if type(value) not in (int, float):
        return False
    try:
        if not math.isfinite(value) or not _numeric_domain(name)[0] <= value <= _numeric_domain(name)[1]:
            return False
    except OverflowError:
        return False
    if name in COUNTS or name == 'kickoff_hour_utc':
        return value == int(value)
    if name in DIRECTIONS:
        return value in (-1, 0, 1)
    precision = 1 if name in PRODUCER_TIME_FIELDS else PRODUCER_PRECISION.get(name)
    if precision is not None and round(value, precision) != value:
        return False
    # Source table lines are quarter goals with the parser's explicit tolerance.
    if name in ('total_line_first', 'total_line_last', 'ah_line_first', 'ah_line_last'):
        try:
            return number(value, 'line') is not None
        except (OverflowError, ValueError):
            return False
    if name == 'total_overround_last':
        return -.998 <= value <= 1 and round(value, 5) == value
    return True


def summary_impossible(values):
    """Validate supplied values before memoizing immutable catalogue tuples."""
    if any(not value_valid(v, x) for v, x in values.items() if v in VARIABLES):
        return True
    # Missing and None both mean missing evidence in this boundary. The request
    # hash remains independent and always identifies every original JSON value.
    return _summary_cached(tuple(values.get(v) for v in VARIABLES))


@lru_cache(maxsize=4096)
def _summary_cached(scalars):
    values = dict(zip(VARIABLES, scalars))
    known = {v: x for v, x in values.items() if v in VARIABLES and x is not None}
    windows = {v: (x, x) for v, x in known.items() if VARIABLES[v][0] == 'num'}
    literals = {v: x for v, x in known.items() if VARIABLES[v][0] == 'bool'}
    flags = [literals[v] for v in ('ctx_cup', 'ctx_youth_reserve', 'ctx_league_other') if v in literals]
    if sum(flags) > 1 or (len(flags) == 3 and not any(flags)):
        return True
    # Known derived features cannot exist when the corresponding market is absent.
    for market, prefixes in (('total_msgs', ('lambda_', 'total_line_', 'total_overround_', 'line_up_', 'line_down_')),
                             ('ah_msgs', ('ah_line_',)), ('x12_msgs', ('p_',))):
        if values.get(market) == 0 and any(v.startswith(prefixes) for v in known):
            return True
    if values.get('total_msgs') == 0 and values.get('total_unobserved_changes') is not None:
        return True
    # None in admission metadata denotes missing evidence. Required fields are
    # excluded separately; do not convert absence of evidence into impossibility.
    return producer_impossible(windows, literals)


def _produce_witness(witness):
    """Verify source grammar, then replay the UNCHANGED producer. No outcomes/I/O.

    This is a mathematical existence certificate, not event authentication. The
    separate trusted provenance adapter is still unavailable.
    """
    if type(witness) is not dict or set(witness) != {'contract', 'kickoff_utc', 'competition', 'events'}:
        raise ValueError('WITNESS_SCHEMA_INVALID')
    if witness['contract'] != CONTRACT_VERSION or type(witness['competition']) is not str:
        raise ValueError('WITNESS_CONTRACT_INVALID')
    try:
        if (type(witness['kickoff_utc']) is not str
                or re.search(r'[.,]\d{7}', witness['kickoff_utc'])):
            raise ValueError('WITNESS_TIME_INVALID')
        ko = datetime.fromisoformat(witness['kickoff_utc'].replace('Z', '+00:00'))
        if ko.tzinfo is None or ko.microsecond:
            raise ValueError('WITNESS_TIME_INVALID')
        ko = ko.astimezone(timezone.utc)
        source = witness['events']
        if type(source) is not list or not 1 <= len(source) <= 64:
            raise ValueError('WITNESS_COMPLEXITY_LIMIT')
        events, ids, previous = [], set(), None
        for index, event in enumerate(source):
            if (type(event) is not dict or set(event) != {'event_id', 'observed_at', 'trigger_market', 'snapshots'}
                    or type(event['event_id']) is not str or not event['event_id'] or event['event_id'] in ids
                    or event['trigger_market'] not in ('total', '1x2', 'unknown')):
                raise ValueError('WITNESS_EVENT_INVALID')
            ids.add(event['event_id'])
            if type(event['observed_at']) is not str or re.search(r'[.,]\d{7}', event['observed_at']):
                raise ValueError('WITNESS_TIME_INVALID')
            t = datetime.fromisoformat(event['observed_at'].replace('Z', '+00:00'))
            if t.tzinfo is None or t.microsecond or t >= ko or (previous is not None and t < previous):
                raise ValueError('WITNESS_TIME_INVALID')
            previous = t
            snaps = event['snapshots']
            if type(snaps) is not dict or set(snaps)-{'total', 'asian_handicap', 'one_x_two'}:
                raise ValueError('WITNESS_SNAPSHOT_INVALID')
            for market, snap in snaps.items():
                if type(snap) is not dict:
                    raise ValueError('WITNESS_SNAPSHOT_INVALID')
                if market == 'one_x_two':
                    if set(snap) != {'1', 'X', '2'} or any(type(pair) is not dict or set(pair) != {'before', 'after'}
                            or not all(valid_price(p) for p in pair.values()) for pair in snap.values()):
                        raise ValueError('WITNESS_QUOTE_INVALID')
                else:
                    fields = {'line', 'over_price', 'under_price'} if market == 'total' else {'line', 'home_price', 'away_price'}
                    if set(snap) != {'before', 'after'}:
                        raise ValueError('WITNESS_QUOTE_INVALID')
                    for side in snap.values():
                        if (type(side) is not dict or set(side) != fields or number(side['line'], 'line') is None
                                or any(not valid_price(side[k]) for k in fields-{'line'})):
                            raise ValueError('WITNESS_QUOTE_INVALID')
            normalized = deepcopy(event)
            normalized['message_id'] = message_number(event['event_id'])
            normalized['sources'] = ['V4_RECORD']
            for market in normalized['snapshots']:
                normalized['snapshots'][market]['origin'] = 'V4_EXPLICIT'
            events.append(normalized)
        ordered = sorted(events, key=lambda e: (e['observed_at'], e['message_id'] or 0, e['event_id']))
        if ordered != events:
            raise ValueError('WITNESS_ORDER_INVALID')
        # Absolute event IDs and dates cannot affect price/sequence summaries.
        # Normalize only AFTER validating them. Keep all durations exactly.
        end = datetime.fromisoformat(events[-1]['observed_at'].replace('Z', '+00:00'))
        anchor = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
        normalized = deepcopy(events)
        try:
            for i, event in enumerate(normalized):
                t = datetime.fromisoformat(event['observed_at'].replace('Z', '+00:00'))
                event.update(event_id='certificate:'+str(i),
                             observed_at=(anchor+(t-end)).isoformat())
            result = dict(_producer_cached(json.dumps(normalized, sort_keys=True), witness['competition']))
        except OverflowError:
            result = trajectory_variables(events, ko, witness['competition'])
            timeline = match_timeline('B1_EXISTENCE', events, near_seconds=120,
                                      identities=[{'kickoff_utc': ko.isoformat()}])
            result['n_episodes'] = len(timeline['movement_episodes'])
        start = datetime.fromisoformat(source[0]['observed_at'].replace('Z', '+00:00'))
        result.update(lead_first_min=round((ko-start).total_seconds()/60, 1),
                      lead_last_min=round((ko-end).total_seconds()/60, 1), kickoff_hour_utc=ko.hour)
        return result
    except (TypeError, KeyError, OverflowError, AttributeError) as exc:
        raise ValueError('WITNESS_INVALID') from exc


@lru_cache(maxsize=4096)
def _producer_cached(serialized, competition):
    events = json.loads(serialized)
    ko = datetime(2026, 1, 2, 13, tzinfo=timezone.utc)
    result = trajectory_variables(events, ko, competition)
    timeline = match_timeline('B1_EXISTENCE', events, near_seconds=120,
                              identities=[{'kickoff_utc': ko.isoformat()}])
    result['n_episodes'] = len(timeline['movement_episodes'])
    return result


@lru_cache(maxsize=4096)
def _replay_cached(serialized):
    return _produce_witness(json.loads(serialized))


def produce_witness(witness):
    # Cache only exact JSON certificates; callers never receive mutable cached data.
    try:
        serialized = json.dumps(witness, sort_keys=True, separators=(',', ':'), allow_nan=False)
        return dict(_replay_cached(serialized))
    except (TypeError, OverflowError, RecursionError) as exc:
        raise ValueError('WITNESS_INVALID') from exc


def witness_matches(witness, values, required=(), branch=()):
    try:
        produced = produce_witness(witness)
        if any(produced.get(v) is None for v in required):
            return False
        if any(produced[v] != value for v, value in values.items() if v in VARIABLES and value is not None):
            return False
        if summary_impossible(produced):
            return False
        return all(evaluate(node, produced) is True for node in branch)
    except (ValueError, TypeError, OverflowError):
        return False


@lru_cache(maxsize=8192)
def _quote(lam, line):
    if not valid_line(line):
        return None
    share = fair_over_share(lam, line)
    if share is None or not .001001 < share < .998999:
        return None
    # Zero-margin odds stay strictly within the parser's open (1,1000) range.
    q = {'line': line, 'over_price': 1/share, 'under_price': 1/(1-share)}
    return q if implied_lambda(line, q['over_price'], q['under_price']) == lam else None


def _representatives(name, windows, seeds):
    lo, hi = _interval(windows, name)
    precision = 1 if name in PRODUCER_TIME_FIELDS else PRODUCER_PRECISION.get(name, 4)
    scale = 10**precision
    candidates = list(seeds.get(name, ())) + [lo, hi, 0, -.1, .1, -.2, .2, -1, 1, -2, 2, 2.5, 3, 12]
    for x in (lo, hi):
        if math.isfinite(x):
            candidates.extend((math.ceil(x*scale)/scale, math.floor(x*scale)/scale,
                               round(x+1/scale, precision), round(x-1/scale, precision)))
    return sorted({round(x, precision) for x in candidates if math.isfinite(x) and lo <= round(x, precision) <= hi},
                  key=lambda x: (abs(x-2) if name == 'lambda_first' else abs(x), x))[:16]


def _delta_path(dirs, target):
    # Construct signed increments with a small interior step; redistribute the
    # residual without crossing the true floating sign thresholds.
    deltas = [d*.1 for d in dirs]
    residual = target-sum(deltas)
    for i, d in enumerate(dirs):
        lo, hi = ((.0501, 11.95) if d == 1 else (-11.95, -.0501) if d == -1 else (-.0499, .0499))
        take = min(hi-deltas[i], max(lo-deltas[i], residual))
        deltas[i] += take
        residual -= take
    if abs(residual) > .000001:
        return None
    return [round(d, 4) for d in deltas]


def construct_witness(branch, windows, seeds=None, required=(), literals=None, budget=256):
    """Bounded constructive search. A miss is UNKNOWN, never UNSAT.

    Candidates are raw snapshots/timestamps. Every returned certificate is
    replayed and checked against the entire branch and all supplied invariants.
    """
    seeds, literals = seeds or {}, literals or {}
    needed = set(required)
    nlo, nhi = _interval(windows, 'n_messages')
    mlo, mhi = _interval(windows, 'total_msgs')
    min_total = 3 if 'lambda_accel_h' in needed else 2 if 'lambda_velocity_h' in needed else 1
    min_n = max(1, math.ceil(nlo), min_total, math.ceil(mlo))
    ns = sorted({min_n, 2, 3, 4, 6, 8, 12} & set(range(1, 13)))
    ns = [n for n in ns if nlo <= n <= nhi]
    def representatives(name):
        atoms = [node for node in branch if variables_used(node) == {name}]
        return [x for x in _representatives(name, windows, seeds)
                if all(evaluate(node, {name: x}) is True for node in atoms)]
    firsts = representatives('lambda_first')
    nets = representatives('lambda_net')
    for last in representatives('lambda_last')[:4]:
        nets += [round(last-first, 4) for first in firsts[:4]]
    # A single observed increment realizes path=abs(net), sd=abs(net)/2.
    # Prioritize these constructive moment solutions before unrelated flat seeds.
    moment_nets = []
    if 'lambda_abs_path' in windows:
        moment_nets += [direction*x for x in representatives('lambda_abs_path') for direction in (1, -1)]
    if 'lambda_sd' in windows:
        moment_nets += [round(direction*2*x, 4) for x in representatives('lambda_sd') for direction in (1, -1)]
    nets = list(dict.fromkeys(x for x in moment_nets+nets if _inside(windows, 'lambda_net', x)))[:24]
    lines = representatives('total_line_first')
    lines = [x for x in lines if valid_line(x)]
    line_lasts = representatives('total_line_last')
    line_lasts = [x for x in line_lasts if valid_line(x)]
    competitions = ['League', 'Cup', 'Youth U21']
    flags = ('ctx_league_other', 'ctx_cup', 'ctx_youth_reserve')
    competitions = [c for c, chosen in zip(competitions, flags)
                    if all((v == chosen) == value for v, value in literals.items() if v in flags)]
    tries = steps = 0
    for n in ns:
        for m in range(max(1, min_total, math.ceil(mlo)), min(n, int(mhi) if math.isfinite(mhi) else n)+1):
            sw = dict(windows, n_messages=(n, n), total_msgs=(m, m))
            models, _ = sequence_models(sw)
            for sequence in models[:32]:
                dirs = sequence+(0,)*(m-len(sequence))
                for net in nets:
                    if m == 1 and (not _inside(windows, 'lambda_abs_path', abs(net))
                                   or not _inside(windows, 'lambda_sd', round(abs(net)/2, 4))):
                        continue
                    unobserved = representatives('lambda_unobserved_net')[:6]
                    if 'lambda_unobserved_net' not in windows:
                        unobserved = [0, round(net-sum(d*.1 for d in dirs), 4)]
                    for unobs in dict.fromkeys(unobserved):
                        if m == 1 and unobs != 0:
                            continue
                        deltas = _delta_path(dirs, net-unobs)
                        if deltas is None:
                            continue
                        for first in firsts:
                            steps += 1
                            if steps > 512:
                                return None
                            # Place unobserved drift in the first gap. It is a
                            # change between snapshots, never an invented observation.
                            points, current = [], first
                            for i, delta in enumerate(deltas):
                                if i == 1:
                                    current = round(current+unobs, 4)
                                after = round(current+delta, 4)
                                points.append((current, after))
                                current = after
                            if any(not LAM_MIN <= x <= LAM_MAX for pair in points for x in pair):
                                continue
                            for line in lines[:6]:
                                for last_line in line_lasts[:6]:
                                    if not _inside(windows, 'total_line_net', round(last_line-line, 4)):
                                        continue
                                    quotes = []
                                    steps += 2*len(points)
                                    if steps > 512:
                                        return None
                                    for i, (before, after) in enumerate(points):
                                        lb = line if i == 0 else last_line
                                        qa, qb = _quote(before, lb), _quote(after, last_line)
                                        if qa is None or qb is None:
                                            break
                                        quotes.append({'before': dict(qa), 'after': dict(qb)})
                                    if len(quotes) != m:
                                        continue
                                    for competition in competitions:
                                        for span in representatives('span_min')[:8]:
                                            if n == 1 and span != 0:
                                                continue
                                            # Prefer positive duration whenever multiple events exist.
                                            if n > 1 and span == 0 and ('lambda_velocity_h' in needed or 'lambda_accel_h' in needed):
                                                continue
                                            witness = _make_witness(n, m, quotes, span, competition, windows, seeds, needed)
                                            if witness is None:
                                                continue
                                            tries += 1
                                            if witness_matches(witness, {}, required=needed, branch=branch):
                                                return witness
                                            if tries >= budget:
                                                return None
    return None


def _make_witness(n, m, quotes, span, competition, windows, seeds, needed):
    hour = next((h for h in range(24) if _inside(windows, 'kickoff_hour_utc', h)), None)
    if hour is None:
        return None
    ko = datetime(2026, 1, 2, hour, tzinfo=timezone.utc)
    firsts = _representatives('lead_first_min', windows, seeds)
    lasts = _representatives('lead_last_min', windows, seeds)
    # Time values chosen here are exact decimal tenths; replay checks rounding.
    pair = next(((f, l) for f in firsts for l in lasts if l > 0 and abs(f-l-span) < 1e-8), None)
    if pair is None:
        for last in [30, 60, 120, *lasts]:
            first = round(last+span, 1)
            if _inside(windows, 'lead_first_min', first) and _inside(windows, 'lead_last_min', last):
                pair = first, last
                break
    if pair is None:
        return None
    first, last = pair
    trigger = next((k for k in range(n+1) if _inside(windows, 'trigger_total_share', round(k/n, 4))), None)
    if trigger is None:
        return None
    events = []
    ah_required = any(v.startswith('ah_line_') for v in needed) or 'ah_msgs' in needed or 'total_ah_same_msg' in needed
    x_required = any(v.startswith('p_') for v in needed) or 'x12_msgs' in needed or 'total_1x2_same_msg' in needed
    for i in range(n):
        lead = first-(span*i/(n-1) if n > 1 else 0)
        observed = ko-timedelta(minutes=lead)
        snaps = {}
        if i < m:
            snaps['total'] = quotes[i]
        if ah_required and i == 0:
            a = _representatives('ah_line_first', windows, seeds)[0]
            b = next((v for v in _representatives('ah_line_last', windows, seeds)
                      if _inside(windows, 'ah_line_net', round(v-a, 4))), a)
            snaps['asian_handicap'] = {'before': {'line': a, 'home_price': 2., 'away_price': 2.},
                                      'after': {'line': b, 'home_price': 2., 'away_price': 2.}}
        if x_required and i == 0:
            pfirst = _representatives('p_home_first', windows, seeds)
            plast = _representatives('p_home_last', windows, seeds)
            pnet = _representatives('p_home_net', windows, seeds)
            pairp = next(((p, q) for p in pfirst for q in [*plast, *(round(p+d, 4) for d in pnet)]
                          if .001 < p < .998 and .001 < q < .998 and _inside(windows, 'p_home_net', round(q-p, 4))), (.4, .5))
            p, q = pairp
            before, after = [p, (1-p)/2, (1-p)/2], [q, (1-q)/2, (1-q)/2]
            snaps['one_x_two'] = {k: {'before': 1/b, 'after': 1/a} for k, b, a in zip(('1', 'X', '2'), before, after)}
        events.append({'event_id': 'b1:'+str(i), 'observed_at': observed.isoformat(),
                       'trigger_market': 'total' if i < trigger else 'unknown', 'snapshots': snaps})
    return {'contract': CONTRACT_VERSION, 'kickoff_utc': ko.isoformat(), 'competition': competition, 'events': events}
