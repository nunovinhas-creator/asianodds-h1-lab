"""Daily LLM attempt limit, with ONE dated, human-authorised exception (stdlib only).

Rule: at most ``BASE_DAILY_LLM_ATTEMPTS`` (4) attempts per UTC day, counted by BOTH the
pre-call ledger (scripts/lab_research_budget.py) and the published memory
(scripts/lab_research_cycle.py). Both import this module, so they can never disagree.

Exception (MASTER BRAIN authorisation after the PR #236 audit): a fifth and final
attempt of the Llama 3.3 70B contract on UTC day 2026-11-05 ONLY. The exception is keyed
by an exact date string, so it expires by itself: from 2026-11-06 the limit is 4 again
with no further change. It cannot be extended by config or environment, it never exceeds
the neuron budget (DAILY_NEURON_BUDGET / MAX_NEURONS_PER_CALL = 5 calls), and the sixth
attempt on that day is refused exactly like any attempt over the limit.
"""
from __future__ import annotations

BASE_DAILY_LLM_ATTEMPTS = 4
HARD_MAX_DAILY_LLM_ATTEMPTS = 5      # = DAILY_NEURON_BUDGET 5,000 / MAX_NEURONS_PER_CALL 1,000
DAILY_LLM_ATTEMPT_EXCEPTIONS = {'2026-11-05': 5}


def daily_llm_attempt_limit(utc_day):
    """Attempt limit for a UTC day given as 'YYYY-MM-DD' (anything else -> base limit)."""
    limit = DAILY_LLM_ATTEMPT_EXCEPTIONS.get(utc_day, BASE_DAILY_LLM_ATTEMPTS) if isinstance(utc_day, str) \
        else BASE_DAILY_LLM_ATTEMPTS
    return min(limit, HARD_MAX_DAILY_LLM_ATTEMPTS)
