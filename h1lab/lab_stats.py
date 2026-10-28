"""Small, dependency-free statistics for the LAB research engine.

Exact or well-known closed forms only: Wilson score interval, Newcombe
hybrid interval for a difference of proportions, Fisher exact test,
Benjamini-Hochberg q-values. No p-value is ever reported without its n.
"""
from __future__ import annotations

import math

Z95 = 1.959963984540054


def wilson(k, n, z=Z95):
    if not n:
        return None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def newcombe_diff(k1, n1, k2, n2):
    """95% CI for p1 - p2 (Newcombe method 10, hybrid Wilson)."""
    if not n1 or not n2:
        return None
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1)
    l2, u2 = wilson(k2, n2)
    d = p1 - p2
    return (d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2),
            d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2))


def _lchoose(n, k):
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def _hyper(x, n1, n2, K):
    return math.exp(_lchoose(n1, x) + _lchoose(n2, K - x) - _lchoose(n1 + n2, K))


def fisher(k1, n1, k2, n2, alternative="two-sided"):
    """Fisher exact test on [[k1, n1-k1], [k2, n2-k2]].

    alternative: 'two-sided', 'greater' (p1 > p2) or 'less' (p1 < p2).
    """
    if not n1 or not n2:
        return None
    K = k1 + k2
    lo, hi = max(0, K - n2), min(K, n1)
    probs = {x: _hyper(x, n1, n2, K) for x in range(lo, hi + 1)}
    if alternative == "greater":
        p = sum(v for x, v in probs.items() if x >= k1)
    elif alternative == "less":
        p = sum(v for x, v in probs.items() if x <= k1)
    else:
        obs = probs[k1]
        p = sum(v for v in probs.values() if v <= obs * (1 + 1e-7))
    return min(1.0, p)


def bh_qvalues(pvalues):
    """Benjamini-Hochberg adjusted q-values, same order as the input."""
    m = len(pvalues)
    if not m:
        return []
    order = sorted(range(m), key=lambda i: pvalues[i])
    q = [0.0] * m
    prev = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        prev = min(prev, pvalues[i] * m / rank)
        q[i] = prev
    return q


def implied_z(hits, probs):
    """(observed - expected) / sd for Bernoulli outcomes with known model probs."""
    if not probs:
        return None
    exp = sum(probs)
    var = sum(p * (1 - p) for p in probs)
    if var <= 0:
        return None
    return (hits - exp) / math.sqrt(var)


def mean_ci(values):
    n = len(values)
    if n < 2:
        return None
    m = sum(values) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))
    h = Z95 * sd / math.sqrt(n)
    return (m - h, m + h)


def r(x, nd=4):
    return None if x is None else round(x, nd)
