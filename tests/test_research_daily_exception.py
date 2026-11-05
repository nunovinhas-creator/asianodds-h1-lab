"""Regression: dated exceptions are retired; budget is shared and UTC-independent."""
import unittest
from h1lab import research_daily_limit as dl
from h1lab.research_quota import DAILY_NEURON_BUDGET, MAX_NEURONS_PER_CALL


class NoDailyExceptions(unittest.TestCase):
    def test_capacity_is_derived_from_one_central_budget(self):
        self.assertEqual(DAILY_NEURON_BUDGET, 8000)
        self.assertEqual(MAX_NEURONS_PER_CALL, 1000)
        self.assertEqual(dl.DAILY_LLM_ATTEMPT_EXCEPTIONS, {})
        for day in ('2026-11-04', '2026-11-05', '2026-11-06', '2027-01-01'):
            self.assertEqual(dl.daily_llm_attempt_limit(day), 8)


if __name__ == '__main__':
    unittest.main()
