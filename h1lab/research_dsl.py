"""Safe declarative indicator language for LLM-proposed variables.

An expression is a JSON tree, never code:

    {"var": "lambda_net"}                       a catalogued pre-kickoff variable
    {"const": 0.2}  /  {"const": true}           finite literal
    {"op": "gt", "args": [<expr>, <expr>]}       an allow-listed operator

There is no string evaluation, attribute access, function call, loop, I/O, SQL or
write operation. Variables are resolved only from ``row['variables']`` (pre-kickoff
data); outcomes, scores and FT fields are unreachable by construction and their
names are rejected. Missing input propagates as ``None`` (three-valued logic): a
match with unknown inputs is never silently moved to a control group.

Validation is structural and typed (num/bool), bounded in depth/size, and returns
a canonical form whose SHA-256 identifies the indicator.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

MAX_DEPTH = 8
MAX_NODES = 64
MAX_CONST = 1e4
NAME_RE = re.compile(r'X_[A-Z0-9_]{2,40}')
VAR_RE = re.compile(r'[a-z][a-z0-9_]{1,40}')
# Whole-token match (a substring rule rejected legitimate names such as X_..._ONLY_MOVE
# or X_..._AWAY_NET because they contain "y_").
FORBIDDEN_NAME_TOKENS = frozenset({'score', 'scores', 'outcome', 'outcomes', 'result', 'results',
                                   'ft', 'win', 'wins', 'won', 'cover', 'covers', 'covered',
                                   'btts', 'y', 'label', 'target', 'final'})
FORBIDDEN_NAME_SEQUENCES = ('over_2_5', 'under_2_5', 'home_goals', 'away_goals', 'total_goals',
                            'goals_scored')


def name_suggests_outcome(name):
    low = name.lower()
    tokens = low.split('_')
    return bool(FORBIDDEN_NAME_TOKENS & set(tokens)) or any(
        ('_' + s + '_') in ('_' + low + '_') for s in FORBIDDEN_NAME_SEQUENCES)
# op -> (argument types, result type); '*' = variadic of the given type (2..6 args)
OPS = {
    'add': (('num', '*'), 'num'), 'sub': (('num', 'num'), 'num'),
    'mul': (('num', '*'), 'num'), 'div': (('num', 'num'), 'num'),
    'neg': (('num',), 'num'), 'abs': (('num',), 'num'), 'sign': (('num',), 'num'),
    'min': (('num', '*'), 'num'), 'max': (('num', '*'), 'num'),
    'gt': (('num', 'num'), 'bool'), 'ge': (('num', 'num'), 'bool'),
    'lt': (('num', 'num'), 'bool'), 'le': (('num', 'num'), 'bool'),
    'eq': (('num', 'num'), 'bool'), 'ne': (('num', 'num'), 'bool'),
    'between': (('num', 'num', 'num'), 'bool'),
    'and': (('bool', '*'), 'bool'), 'or': (('bool', '*'), 'bool'), 'not': (('bool',), 'bool'),
    'is_known': (('any',), 'bool'),
}


class DSLError(ValueError):
    pass


def _check_var_name(name, variables):
    if not isinstance(name, str) or not (VAR_RE.fullmatch(name) or NAME_RE.fullmatch(name)):
        raise DSLError('INVALID_VARIABLE_NAME')
    if name not in variables:
        raise DSLError('UNKNOWN_VARIABLE:' + name)
    return variables[name]


def validate(expr, variables, *, expect=None):
    """Return (canonical_expr, type). ``variables``: name -> 'num'|'bool'."""
    counter = [0]

    def walk(node, depth):
        counter[0] += 1
        if counter[0] > MAX_NODES:
            raise DSLError('EXPRESSION_TOO_LARGE')
        if depth > MAX_DEPTH:
            raise DSLError('EXPRESSION_TOO_DEEP')
        if not isinstance(node, dict) or len(node) not in (1, 2):
            raise DSLError('INVALID_NODE')
        if set(node) == {'var'}:
            return {'var': node['var']}, _check_var_name(node['var'], variables)
        if set(node) == {'const'}:
            c = node['const']
            if isinstance(c, bool):
                return {'const': c}, 'bool'
            if not isinstance(c, (int, float)) or not math.isfinite(c) or abs(c) > MAX_CONST:
                raise DSLError('INVALID_CONSTANT')
            return {'const': round(float(c), 6)}, 'num'
        if set(node) != {'op', 'args'}:
            raise DSLError('INVALID_NODE_KEYS')
        op, args = node['op'], node['args']
        if not isinstance(op, str) or op not in OPS:
            raise DSLError('OPERATOR_NOT_ALLOWED')
        if not isinstance(args, list):
            raise DSLError('INVALID_ARGS')
        sig, out = OPS[op]
        if len(sig) == 2 and sig[1] == '*':
            if not 2 <= len(args) <= 6:
                raise DSLError('ARITY:' + op)
            want = [sig[0]] * len(args)
        else:
            if len(args) != len(sig):
                raise DSLError('ARITY:' + op)
            want = list(sig)
        canon = []
        for a, w in zip(args, want):
            c, t = walk(a, depth + 1)
            if w != 'any' and t != w:
                raise DSLError('TYPE_ERROR:%s expects %s' % (op, w))
            canon.append(c)
        return {'op': op, 'args': canon}, out

    canon, typ = walk(expr, 1)
    if expect and typ != expect:
        raise DSLError('EXPECTED_%s_EXPRESSION' % expect.upper())
    return canon, typ


def variables_used(expr):
    out = set()

    def walk(n):
        if 'var' in n:
            out.add(n['var'])
        for a in n.get('args', ()):
            walk(a)
    walk(expr)
    return out


def canonical_json(expr):
    return json.dumps(expr, sort_keys=True, separators=(',', ':'), allow_nan=False)


def expr_id(expr):
    return hashlib.sha256(canonical_json(expr).encode()).hexdigest()[:16]


def evaluate(expr, env):
    """Evaluate a VALIDATED expression. ``env``: name -> value (None = unknown)."""
    if 'var' in expr:
        v = env.get(expr['var'])
        if isinstance(v, bool) or v is None:
            return v
        return float(v)
    if 'const' in expr:
        return expr['const']
    op = expr['op']
    if op == 'is_known':
        return evaluate(expr['args'][0], env) is not None
    vals = [evaluate(a, env) for a in expr['args']]
    if op == 'and':
        if any(v is False for v in vals):
            return False
        return None if any(v is None for v in vals) else True
    if op == 'or':
        if any(v is True for v in vals):
            return True
        return None if any(v is None for v in vals) else False
    if any(v is None for v in vals):
        return None
    if op == 'not':
        return not vals[0]
    a = vals[0]
    b = vals[1] if len(vals) > 1 else None
    if op == 'add':
        r = sum(vals)
    elif op == 'sub':
        r = a - b
    elif op == 'mul':
        r = 1.0
        for v in vals:
            r *= v
    elif op == 'div':
        if abs(b) < 1e-12:
            return None
        r = a / b
    elif op == 'neg':
        r = -a
    elif op == 'abs':
        r = abs(a)
    elif op == 'sign':
        r = 1.0 if a > 0 else -1.0 if a < 0 else 0.0
    elif op == 'min':
        r = min(vals)
    elif op == 'max':
        r = max(vals)
    elif op == 'gt':
        return a > b
    elif op == 'ge':
        return a >= b
    elif op == 'lt':
        return a < b
    elif op == 'le':
        return a <= b
    elif op == 'eq':
        return abs(a - b) <= 1e-9
    elif op == 'ne':
        return abs(a - b) > 1e-9
    elif op == 'between':
        return vals[1] <= a <= vals[2]
    else:  # pragma: no cover - validated earlier
        raise DSLError('OPERATOR_NOT_ALLOWED')
    return r if math.isfinite(r) else None


def validate_indicator(spec, variables):
    """A new LLM indicator: {'name': 'X_...', 'description': str, 'expr': tree}."""
    if not isinstance(spec, dict) or set(spec) != {'name', 'description', 'expr'}:
        raise DSLError('INVALID_INDICATOR_CONTRACT')
    name = spec['name']
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise DSLError('INVALID_INDICATOR_NAME')
    if name_suggests_outcome(name):
        raise DSLError('INDICATOR_NAME_SUGGESTS_OUTCOME')
    if name in variables:
        raise DSLError('INDICATOR_NAME_COLLISION')
    desc = spec['description']
    if not isinstance(desc, str) or not 5 <= len(desc) <= 200 or any(ord(c) < 32 for c in desc):
        raise DSLError('INVALID_INDICATOR_DESCRIPTION')
    canon, typ = validate(spec['expr'], variables)
    return {'name': name, 'description': desc, 'expr': canon, 'type': typ,
            'id': expr_id(canon), 'uses': sorted(variables_used(canon))}
