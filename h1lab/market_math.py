"""Pure market arithmetic for the LAB research engine (no I/O, no H1 imports).

Why this exists: odds at different Asian total lines are NOT comparable
(audit A3, 27/10). "Over 1.86 @ 3.0 -> 1.96 @ 3.25" looks like the Over
drifting, but the market's implied goal expectation *rises*. Every movement
is therefore also expressed in one common space: the Poisson mean ``lam``
of total goals implied by (line, over, under) after removing the margin.

Settlement-aware inversion
--------------------------
A quarter line splits the stake: 2.75 = half on 2.5 + half on 3.0. For each
component c: Over wins if G > c, loses if G < c, pushes if G == c. With
W = sum of win probabilities, L = sum of loss probabilities, the fair Over
price x satisfies EV = (x - 1) W - L = 0, so 1/x = W / (W + L); likewise the
fair Under price gives 1/y = L / (W + L) and 1/x + 1/y = 1. The observed pair
is de-margined proportionally (p_over = (1/O) / (1/O + 1/U)) and ``lam`` is
the unique value with W/(W+L) = p_over (monotone in lam; solved by bisection).

This is a *model-implied* quantity (Poisson, independence of the observed
book, proportional margin). It is a reference baseline, never a price: a
probability for Over 2.5 derived from a 2.75 line is not an Over 2.5 odd and
is never used to compute ROI.
"""
from __future__ import annotations

import math

MATH_VERSION = 1
LAM_MIN, LAM_MAX = 0.05, 12.0
MAX_GOALS = 40


def valid_price(x):
    return (not isinstance(x, bool) and isinstance(x, (int, float))
            and math.isfinite(x) and 1.0 < x < 1000)


def valid_line(x):
    return (not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(x)
            and 0 <= x <= 15 and abs(x * 4 - round(x * 4)) < 1e-7)


def margin(*prices):
    """Book overround: sum(1/odd) - 1. None if any price is invalid."""
    if not prices or not all(valid_price(p) for p in prices):
        return None
    return sum(1.0 / p for p in prices) - 1.0


def fair_probs(*prices):
    """Proportionally de-margined probabilities (sum to 1)."""
    if not prices or not all(valid_price(p) for p in prices):
        return None
    inv = [1.0 / p for p in prices]
    s = sum(inv)
    return [v / s for v in inv]


def _pmf(lam):
    p = [math.exp(-lam)]
    for k in range(1, MAX_GOALS + 1):
        p.append(p[-1] * lam / k)
    return p


def components(line):
    """Asian total line -> list of component lines (1 or 2)."""
    q = round(line * 4) % 4
    if q in (0, 2):
        return [line]
    return [line - 0.25, line + 0.25]


def over_win_loss(lam, line):
    pmf = _pmf(lam)
    w = l = 0.0
    for c in components(line):
        for g, p in enumerate(pmf):
            if g > c + 1e-9:
                w += p
            elif g < c - 1e-9:
                l += p
    return w, l


def fair_over_share(lam, line):
    w, l = over_win_loss(lam, line)
    return w / (w + l) if w + l > 0 else None


def implied_lambda(line, over, under):
    """Poisson total-goals mean implied by an Asian Total quote, or None."""
    if not valid_line(line) or not valid_price(over) or not valid_price(under):
        return None
    target = fair_probs(over, under)[0]
    lo, hi = LAM_MIN, LAM_MAX
    flo, fhi = fair_over_share(lo, line), fair_over_share(hi, line)
    if flo is None or fhi is None or not (flo <= target <= fhi):
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if fair_over_share(mid, line) < target:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 4)


def prob_total_over(lam, threshold=2.5):
    """Model P(total goals > threshold) for a half-goal threshold."""
    if lam is None:
        return None
    pmf = _pmf(lam)
    return round(sum(p for g, p in enumerate(pmf) if g > threshold), 4)


def total_snapshot_metrics(snap):
    """{lam, margin, p_over_2_5} for one side ('before'/'after') of a Total table."""
    line, o, u = snap.get("line"), snap.get("over_price"), snap.get("under_price")
    lam = implied_lambda(line, o, u)
    m = margin(o, u)
    return {"lam": lam, "margin": None if m is None else round(m, 4),
            "p_over_2_5_model": prob_total_over(lam)}


def one_x_two_probs(prices):
    """{'1','X','2'} -> de-margined probabilities, or None."""
    vals = [prices.get(k) for k in ("1", "X", "2")]
    fp = fair_probs(*vals)
    return None if fp is None else dict(zip(("1", "X", "2"), (round(v, 4) for v in fp)))
