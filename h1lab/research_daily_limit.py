"""Compatibility view of unmetered capacity; no dated exceptions.

Actual admission uses research_quota.Controller and measured estimates/reservations.
This function is retained for older offline consumers, not for live admission.
"""
from .research_quota import DAILY_NEURON_BUDGET, MAX_NEURONS_PER_CALL
BASE_DAILY_LLM_ATTEMPTS = DAILY_NEURON_BUDGET // MAX_NEURONS_PER_CALL
HARD_MAX_DAILY_LLM_ATTEMPTS = BASE_DAILY_LLM_ATTEMPTS
DAILY_LLM_ATTEMPT_EXCEPTIONS = {}


def daily_llm_attempt_limit(utc_day):
    return BASE_DAILY_LLM_ATTEMPTS
